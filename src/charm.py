#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for configuring COS on Kubernetes."""

import hashlib
import logging
import os
import shutil
from typing import Final, List, Optional, Tuple, cast

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import APIError, ChangeError, ExecError

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class ServiceRestartError(Exception):
    """Raise when a service can't/won't restart for whatever reason."""


class SyncError(Exception):
    """Raised when git-sync command fails."""

    def __init__(self, message: str, details: str = None):
        self.message = f"Sync error: {message}"
        self.details = details

        super().__init__(self.message)


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

        if not self._configured:
            self.unit.status = BlockedStatus("Config options missing - use `juju config`")
            self._remove_repo_folder()
            self._update_hash_and_rel_data()
            return

        try:
            self._exec_sync_repo()
        except SyncError as e:
            # This could be a temporary network error; do not remove repo folder or update relation
            # data - just set status to blocked: we don't want to drop rules/dashboards just
            # because a sync failed.
            # Note that this also applies if the user provided an invalid branch name.
            self.unit.status = BlockedStatus("Sync failed: " + e.message)
            return

        self._update_hash_and_rel_data()

        if self._stored_hash in [self._hash_placeholder, None]:
            self.unit.status = BlockedStatus("No hash file yet - confirm config is valid")
        else:
            self.unit.status = ActiveStatus()

    def _on_sync_now_action(self, event: ActionEvent):
        """Hook for the sync-now action."""
        if not self.container.can_connect():
            event.fail("Container not ready")
            return
        elif not self._configured:
            event.fail("Config options missing - use `juju config`")
            return

        event.log("Calling git-sync with --one-time...")

        try:
            stdout, stderr = self._exec_sync_repo()
        except SyncError as e:
            if e.details:
                for line in e.details.splitlines():
                    event.log(line.strip())
            event.fail(e.message)
            return

        if stderr:
            for line in stderr.splitlines():
                event.log(f"Warning: {line.strip()}")

        event.set_results({"git-sync-stdout": stdout})

        # Go through the common exit hook to update the store hash
        self._common_exit_hook()

    @property
    def _configured(self) -> bool:
        """Check if charm is in 'configured' state.

        The charm is considered 'configured' if the `git_repo` config option is set.
        """
        return bool(self.config.get("git_repo"))

    def _exec_sync_repo(self) -> Tuple[str, str]:
        """Execute the sync command in the workload container.

        Raises:
            SyncError, if the sync failed.

        Returns:
            stdout, from the sync command.
            stderr, from the sync command.
        """
        try:
            process = self.container.exec(self._git_sync_command_line(one_time=True))
        except APIError as e:
            raise SyncError(str(e)) from e

        try:
            stdout, stderr = process.wait_output()
        except ExecError as e:
            raise SyncError(f"Exited with code {e.exit_code}.", e.stderr) from e
        except ChangeError as e:
            raise SyncError(str(e)) from e

        if stderr:
            for line in stderr.splitlines():
                logger.info(f"git-sync: {line.strip()}")

        return stdout, stderr

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

    def _git_sync_command_line(self, one_time=False) -> List[str]:
        """Construct the command line for running git-sync.

        See https://github.com/kubernetes/git-sync.

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
            # TODO: is this needed for every relation? app data should be the same for all
            relation.data[self.app]["hash"] = sha

    def _update_hash_and_rel_data(self):
        # Use the contents of the hash file as an indication for a change in the repo.
        # When the charm is first deployed, relation data is empty. Need to change it to the
        # placeholder value, indicating there is no hash file present yet, or to the contents of
        # the hash file if it is present.
        current_hash = self._get_current_hash()
        if current_hash != self._stored_hash and self.unit.is_leader():
            logger.info(
                "Updating stored hash: git-sync hash changed from %s (%s) to %s (%s)",
                self._stored_hash,
                type(self._stored_hash),
                current_hash,
                type(current_hash),
            )
            self.prom_rules_provider._reinitialize_alert_rules()
            self.loki_rules_provider._reinitialize_alert_rules()
            self.grafana_dashboards_provider._reinitialize_dashboard_data()
            self._stored_hash = current_hash

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
        """Event handler for StartEvent."""
        self._common_exit_hook()

    def _on_config_changed(self, _):
        """Event handler for ConfigChangedEvent."""
        self._common_exit_hook()


if __name__ == "__main__":
    main(COSConfigCharm, use_juju_for_storage=True)
