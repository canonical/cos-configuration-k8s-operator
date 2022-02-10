#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for configuring COS on Kubernetes."""

import hashlib
import logging
import os
import shutil
from typing import Final, List, Optional, cast

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import APIError, ChangeError, ExecError, Layer

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class ServiceRestartError(RuntimeError):
    """Custom exception for when a service can't/won't restart for whatever reason."""


class COSConfigCharm(CharmBase):
    """A Juju charm for configuring COS."""

    _container_name = "git-sync"  # automatically determined from charm name
    _layer_name = "git-sync"  # layer label argument for container.add_layer
    _service_name = "git-sync"  # chosen arbitrarily to match charm name
    _peer_relation_name = "replicas"  # must match metadata.yaml peer role name
    _git_sync_port = 9000  # port number for git-sync's HTTP endpoint

    # Directory name under `-root` (passed to `-dest`) into where the repo will be cloned.
    # Having this option is useful in lieu of a git "overwrite all" flag: any changes will
    # overwrite any existing files.
    # Since this is an implementation detail, it is captured here as a class variable.
    SUBDIR: Final = "repo"

    # path to the repo in the _charm_ container
    _git_sync_mount_point = "/var/lib/juju/storage/content-from-git/0"
    _repo_path = os.path.join(_git_sync_mount_point, SUBDIR)

    prometheus_relation_name = "prometheus-config"
    loki_relation_name = "loki-config"
    grafana_relation_name = "grafana-dashboards"

    _hash_placeholder = "failed to fetch hash"

    def __init__(self, *args):
        super().__init__(*args)

        self.container = self.unit.get_container(self._container_name)

        # Core lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.leader_elected, self._on_leader_changed)
        self.framework.observe(self.on.leader_settings_changed, self._on_leader_changed)
        self.framework.observe(self.on.git_sync_pebble_ready, self._on_git_sync_pebble_ready)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)

        # Relation events
        # These are registered here to make sure the charm's status reflects relation data:
        # if files show up on disk after the last hook fires, and then a relation to, say loki, is
        # joined, then the loki charm lib would read the alerts from disk and populate relation
        # data, but the charm's status would remain blocked until the next update status.
        # By registering these events, the status has a chance of being updated sooner. If however
        # relation is joined before files show up on disk then status update would have to wait for
        # update-status.
        for e in [
            self.on[self.prometheus_relation_name].relation_joined,
            self.on[self.loki_relation_name].relation_joined,
            self.on[self.grafana_relation_name].relation_joined,
        ]:
            self.framework.observe(e, self._on_relation_joined)

        # Action events
        self.framework.observe(self.on.sync_now_action, self._on_sync_now_action)

        # logger.info("repo location: [%s]", self.meta.storages["content-from-git"].location)

        # git-sync stores in a `.git` _file_ (e.g. /git/repo/.git) a relpath to the worktree, which
        # includes the commit hash, which looks like this:
        #
        #     gitdir: ../.git/worktrees/901551c1bdd2ff5a10f14027667c15a6b3a16777
        #
        # A change in the contents of that file is an indication for a change.
        # Path to the hash file in the _charm_ container
        self._git_hash_file_path = os.path.join(self._repo_path, ".git")

        # path to the root storage of the git-sync _sidecar_ container
        self._git_sync_mount_point_sidecar = (
            self.meta.containers[self._container_name].mounts["content-from-git"].location
        )

        self.prom_rules_provider = PrometheusRulesProvider(
            self,
            self.prometheus_relation_name,
            dir_path=os.path.join(self._repo_path, self.config["prometheus_alert_rules_path"]),
            recursive=True,
        )

        self.loki_rules_provider = LokiPushApiConsumer(
            self,
            self.loki_relation_name,
            alert_rules_path=os.path.join(self._repo_path, self.config["loki_alert_rules_path"]),
            recursive=True,
        )

        self.grafana_dashboards_provider = GrafanaDashboardProvider(
            self,
            self.grafana_relation_name,
            dashboards_path=os.path.join(self._repo_path, self.config["grafana_dashboards_path"]),
        )

        self.service_patcher = KubernetesServicePatch(
            self,
            [(f"{self.app.name}-git-sync", self._git_sync_port, self._git_sync_port)],
        )

    def _common_exit_hook(self) -> None:  # noqa: C901
        """Event processing hook that is common to all events to ensure idempotency."""
        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for pod startup to complete")
            return

        if not self.model.get_relation(self._peer_relation_name):
            # peer relation's app data is used for storing the hash - need to wait for it to come
            # up before proceeding
            self.unit.status = MaintenanceStatus("Waiting for peer relation to be created")
            return

        # Check if stored hash was initialized (it can only be None when a new deployment starts,
        # at which point no services should be running).
        if not self._stored_hash:
            if not self.unit.is_leader():
                # Relation app data is uninitialized and this is not a leader unit.
                # Abort; startup sequence will resume when leader updates relation data and
                # relation-changed fires.
                self.unit.status = BlockedStatus("Waiting for leader unit to initialize the hash")
                return

            # Cleanup
            self._update_relation_data()

        # The only mandatory config option is the `git_repo` option. If it is unset, the repo
        # folder and hash should reset and the service stopped.
        # Emptying the folder and stopping the service is required because otherwise the charm libs
        # (prometheus, loki, grafana) will keep seeing rules/dashboards present.
        # TODO move into config changed?
        if not self.config.get("git_repo"):
            # Stop service and remove the repo folder
            # Ideally this would be done once, not _every_ time the hook is called, but no harm
            self._stop_service()
            self._remove_repo_folder()

            self._update_relation_data()
            self.unit.status = BlockedStatus("Repo URL is not set; use `juju config`")
            return

        # Update pebble layer to reflect changes in config options
        overlay = self._layer()
        plan = self.container.get_plan()

        if (
            self._service_name not in plan.services
            or overlay.services != plan.services
            or not self.container.get_service(self._service_name).is_running()
        ):
            try:
                # The git-sync sidecar not always clears up on its own any old existing content
                # self._restart_service()
                self._stop_service()
                self._remove_repo_folder()
                self.container.add_layer(self._layer_name, overlay, combine=True)
                self._restart_service()
            except (ChangeError, ServiceRestartError) as e:
                self.unit.status = BlockedStatus(str(e))
                return

        # Need to call this again in case files showed up on disk after the last hook fired.
        self._update_relation_data()

        if self._stored_hash in [self._hash_placeholder, None]:
            self.unit.status = BlockedStatus("No hash file yet - wait for update-status")
        else:
            if not isinstance(self.unit.status, ActiveStatus):
                logger.info("CONFIGURED state reached")
            self.unit.status = ActiveStatus()

    def _on_sync_now_action(self, event: ActionEvent):
        """Hook for the sync-now action."""
        if not self.container.can_connect():
            event.fail("Container not ready")
            return

        event.log("Calling git-sync with --one-time...")

        try:
            process = self.container.exec(self._command(one_time=True))
        except APIError as e:
            event.fail(str(e))
            return

        try:
            stdout, warnings = process.wait_output()
        except ExecError as e:
            for line in e.stderr.splitlines():
                event.log(line)
            event.fail("Exited with code {e.exit_code}.")
            return
        except ChangeError as e:
            event.fail(str(e))
            return

        if warnings:
            for line in warnings.splitlines():
                event.log(f"Warning: {line.strip()}")

        event.set_results({"git-sync-stdout": stdout})

        # Do the same thing _update_status() is doing to make sure relation data is up-to-date
        self._common_exit_hook()

    def _remove_repo_folder(self):
        """Remove the repo folder."""
        # This can be done using pebble:
        #
        #   _repo_path_sidecar = os.path.join(
        #             self._git_sync_mount_point_sidecar, GitSyncLayer.SUBDIR
        #         )
        #   self.container.remove_path(_repo_path_sidecar, recursive=True)
        #
        # but to keep unittest simpler, doing it from the charm container's mount point
        shutil.rmtree(self._repo_path, ignore_errors=True)

    def _command(self, one_time=False) -> List[str]:
        """Construct the command line for running git-sync.

        Args:
            one_time: flag for adding the `--one-time` argument to have git-sync exit after the
            first sync.
        """
        repo = cast(str, self.config.get("git_repo"))
        branch = cast(str, self.config.get("git_branch"))
        rev = cast(str, self.config.get("git_rev"))
        wait = str(self.config.get("git_wait"))  # converting to str so that 0 evaluates as True

        cmd = ["/git-sync"]
        cmd.extend(["--repo", repo])
        if branch:
            cmd.extend(["--branch", branch])
        if rev:
            cmd.extend(["--rev", rev])
        cmd.extend(
            [
                "--depth",
                "1",
                "--root",
                self._git_sync_mount_point_sidecar,
                "--dest",
                self.SUBDIR,  # so charm code doesn't need to delete
            ]
        )

        if one_time:
            cmd.append("--one-time")
        else:
            if wait:
                cmd.extend(["--wait", wait])
            cmd.extend(
                [
                    "--http-bind",
                    f":{self._git_sync_port}",
                    "--http-metrics",
                    "true",
                ]
            )

        return cmd

    def _layer(self) -> Layer:
        """Build overlay layer for the git-sync service.

        This layer is used for launching a git-sync (https://github.com/kubernetes/git-sync)
        container with custom arguments.
        """
        return Layer(
            {
                "summary": f"{self._service_name} layer",
                "description": f"pebble config layer for {self._service_name}",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "summary": f"{self._service_name} service",
                        "startup": "disabled",
                        "command": " ".join(self._command()),
                    },
                },
            }
        )

    def _on_relation_joined(self, _):
        """Event handler for the relation joined event of prometheus, loki or grafana."""
        self._common_exit_hook()

    def _on_upgrade_charm(self, _):
        """Event handler for the upgrade event during which we will update the service."""
        self._common_exit_hook()

    def _get_current_hash(self) -> str:
        """Get the hash of the current revision from git-sync's filesystem.

        Returns:
            The contents of the hash file, if it is readable; the placeholder value otherwise.
        """
        if not self.container.can_connect():
            # This may happen if called before pebble_ready
            logger.warning("Reinitialize aborted: git-sync container is not ready")
            return self._hash_placeholder
        try:
            with open(self._git_hash_file_path, "rt") as f:
                return f.read().strip()
        except (OSError, IOError, FileNotFoundError) as e:
            logger.debug("Error reading hash file: %s", e)
            return self._hash_placeholder

    @property
    def _stored_hash(self) -> Optional[str]:
        return self.model.get_relation(self._peer_relation_name).data[self.app].get("hash", None)

    @_stored_hash.setter
    def _stored_hash(self, sha: str):
        """Update peer relation data with the given hash."""
        if not self.unit.is_leader():
            logger.info("store hash: abort: not leader")
            return
        for relation in self.model.relations[self._peer_relation_name]:
            logger.info(
                "setting stored hash from [%s] to [%s]", relation.data[self.app].get("hash"), sha
            )
            relation.data[self.app]["hash"] = sha

    def _update_hash(self) -> bool:
        # Use the contents of the hash file as an indication for a change in the repo.
        # If the git hash is not yet in peer relation data, add it now.
        # When the charm is first deployed, relation data is empty. Need to change it to the
        # placeholder value, indicating there is no hash file present yet, or to the contents of
        # the hash file if it is present.
        if not self.unit.is_leader():
            return False

        hash_changed = True
        current_hash = self._get_current_hash()
        if not self._stored_hash:
            self._stored_hash = current_hash
            logger.info("IDLE state reached")
        elif current_hash != self._stored_hash:
            logger.info(
                "Updating stored hash: git-sync hash changed from %s (%s) to %s (%s)",
                self._stored_hash,
                type(self._stored_hash),
                current_hash,
                type(current_hash),
            )
            self._stored_hash = current_hash
        else:
            hash_changed = False

        return hash_changed

    def _update_relation_data(self):
        """Reinitialize relation data, if the underlying data changed."""
        if not self.unit.is_leader():
            return

        if self._update_hash():
            self.prom_rules_provider._reinitialize_alert_rules()
            self.loki_rules_provider._reinitialize_alert_rules()
            self.grafana_dashboards_provider._reinitialize_dashboard_data()

    def _on_git_sync_pebble_ready(self, _):
        """Event handler for PebbleReadyEvent."""
        self._common_exit_hook()

    def _on_update_status(self, _):
        # reload rules in lieu of inotify or manual relation-set
        self._common_exit_hook()

    def _on_leader_changed(self, _):
        """Event handler for LeaderElected and LeaderSettingsChanged."""
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

    def _stop_service(self):
        """Helper to stop the service, suppressing exceptions (in case it is not running)."""
        try:
            self.container.stop(self._service_name)
        except:  # noqa E722
            pass

    def _restart_service(self) -> None:
        """Helper function for restarting the underlying service."""
        logger.info("Restarting service %s", self._service_name)

        if not self.container.can_connect():
            raise ServiceRestartError("Cannot (re)start service: container is not ready.")

        # Check if service exists, to avoid ModelError from being raised when the service does
        # not yet exist
        if self._service_name not in self.container.get_plan().services:
            raise ServiceRestartError("Cannot (re)start service: service does not (yet) exist.")

        self.container.restart(self._service_name)

        service_running = (
            service := self.container.get_service(self._service_name)
        ) and service.is_running()
        if not service_running:
            raise ServiceRestartError("Attempted to restart service but it is not running")


if __name__ == "__main__":
    main(COSConfigCharm, use_juju_for_storage=True)
