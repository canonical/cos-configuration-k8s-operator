#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Deploy lma-rules to a Kubernetes environment."""
import hashlib
import logging
import os
from abc import ABC, abstractmethod

from charms.prometheus_k8s.v0.prometheus_scrape import RuleFilesProvider
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import ChangeError, Layer

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class LayerBuilder(ABC):
    """Base helper class for building OF layers."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def _command(self) -> str:
        ...

    def build(self, override: str = "replace", startup: str = "enabled") -> Layer:
        """Builds the layer!"""
        return Layer(
            {
                "summary": f"{self.name} layer",
                "description": f"pebble config layer for {self.name}",
                "services": {
                    self.name: {
                        "override": override,
                        "summary": f"{self.name} service",
                        "startup": startup,
                        "command": self._command(),
                    },
                },
            }
        )


class LayerConfigError(ValueError):
    """Custom exception for invalid layer configurations."""


class GitSyncLayer(LayerBuilder):
    """Helper class for building a git-sync layer.

    This layer is used for launching a git-sync (https://github.com/kubernetes/git-sync) container
    with custom arguments.

    Raises:
        LayerConfigError, if the config is invalid.
    """

    def __init__(self, service_name: str, repo: str, branch: str, wait: int):
        super().__init__(service_name)
        if not repo:
            raise LayerConfigError("git-sync config error: invalid repo")
        elif not branch:
            raise LayerConfigError("git-sync config error: invalid branch")
        elif wait <= 0:
            raise LayerConfigError("git-sync config error: wait time must be > 0")

        self.repo = repo
        self.branch = branch
        self.wait = wait

    def _command(self) -> str:
        cmd = (
            "/git-sync "
            f"-repo {self.repo} "
            f"-branch {self.branch} "
            "-depth 1 "
            f"-wait {self.wait} "
            # "-git-config k:v,k2:v2 "
            "-root /git "  # TODO do not hardcode
            "-dest repo"  # so charm code doesn't need to delete
        )
        logger.debug("command: %s", cmd)
        return cmd


class ServiceRestartError(RuntimeError):
    """Custom exception for when a service can't/won't restart for whatever reason."""


class LMARulesCharm(CharmBase):
    """A Juju charm for lma-rules."""

    _container_name = "git-sync"  # automatically determined from charm name
    _layer_name = "git-sync"  # layer label argument for container.add_layer
    _service_name = "git-sync"  # chosen arbitrarily to match charm name
    _peer_relation_name = "replicas"  # must match metadata.yaml peer role name

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(servers={}, config_hash=None)

        self.container = self.unit.get_container(self._container_name)

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.git_sync_pebble_ready, self._on_git_sync_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)

        self.prom_config_subset = RuleFilesProvider(
            self,
            "prometheus-config",
            dir_path=os.path.join(
                self.meta.storages["content-from-git"].location,
                "repo",  # TODO do not hardcode
                self.config["prometheus_relpath"],
            ),
            recursive=True,
            aux_events=[
                self.on.git_sync_pebble_ready,  # reload rules when git-sync is up after the charm
                self.on.config_changed,
                self.on.update_status,  # in lieu of inotify or manual relation-set
            ],
        )

        logger.info("charm location: [%s]", self.meta.storages["content-from-git"].location)

    def _common_exit_hook(self) -> None:
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        # Update pebble layer
        try:
            # self._update_config()
            self._update_layer()
        except ServiceRestartError as e:
            self.unit.status = BlockedStatus(str(e))
        except LayerConfigError as e:
            self.unit.status = BlockedStatus(str(e))
        except ChangeError as e:
            self.unit.status = BlockedStatus(str(e))
        else:
            self.unit.status = ActiveStatus()

    # def _update_config(self) -> bool:
    #     """Update the lma-rules yml config file to reflect changes in configuration.
    #
    #     Returns:
    #       True if config changed; False otherwise
    #     """
    #     return False

    def _update_layer(self) -> None:
        """Update service layer to reflect changes in peers (replicas).

        Args:
          restart: a flag indicating if the service should be restarted if a change was detected.

        Returns:
          True if anything changed; False otherwise
        """
        overlay = GitSyncLayer(
            service_name=self._service_name,
            repo=str(self.config.get("git-sync::repo")),
            branch=str(self.config.get("git-sync::branch")),
            wait=int(self.config.get("git-sync::wait")),  # type: ignore[arg-type]
        ).build()

        plan = self.container.get_plan()

        if (
            self._service_name not in plan.services
            or overlay.services != plan.services
            or not self.container.get_service(self._service_name).is_running()
        ):
            # this still returns ModelError:
            # ( if (service := self.container.get_service(self._service_name))
            # and service.is_running():
            try:
                self.container.stop(self._service_name)
            except:  # noqa E722
                pass
            self.container.remove_path("/git/repo", recursive=True)
            self.container.add_layer(self._layer_name, overlay, combine=True)
            self._restart_service()

    def _on_upgrade_charm(self, _):
        """Event handler for the upgrade event during which we will update the K8s service."""
        # After upgrade (refresh), the unit ip address is not guaranteed to remain the same, and
        # the config may need update. Calling the common hook to update.
        self._common_exit_hook()

    def _on_git_sync_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_start(self, _):
        """Event handler for StartEvent.

        With Juju 2.9.5 encountered a scenario in which pebble_ready and config_changed fired,
        but IP address was not available and the status was stuck on "Waiting for IP address".
        Adding this hook reduce the likelihood of that scenario.
        """
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook()

    def _restart_service(self) -> None:
        """Helper function for restarting the underlying service."""
        logger.info("Restarting service %s", self._service_name)

        if not self.container.can_connect():
            raise ServiceRestartError("Cannot (re)start service: container is not ready.")

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not yet exist
        if not self.container.get_services().get(self._service_name):
            raise ServiceRestartError("Cannot (re)start service: service does not (yet) exist.")

        self.container.restart(self._service_name)

        service_running = (
            service := self.container.get_service(self._service_name)
        ) and service.is_running()
        if not service_running:
            raise ServiceRestartError("Attempted to restart service but it is not running")


if __name__ == "__main__":
    main(LMARulesCharm, use_juju_for_storage=True)
