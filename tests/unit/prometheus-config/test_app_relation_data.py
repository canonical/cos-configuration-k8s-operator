#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import unittest
from unittest.mock import patch

import hypothesis.strategies as st
import ops
import yaml
from hypothesis import given
from ops.model import ActiveStatus
from ops.testing import Harness

from charm import COSConfigCharm

logger = logging.getLogger(__name__)

ops.testing.SIMULATE_CAN_CONNECT = True


class TestAppRelationData(unittest.TestCase):
    """Feature: Charm's app relation data should contain alert rules read from disk.

    Background: Given a folder of rules on disk (which in reality is synced from a git repo), the
    charm should forward them over app relation data.
    """

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self):
        self.harness = Harness(COSConfigCharm)
        self.addCleanup(self.harness.cleanup)

        self.app_name = "cos-configuration-k8s"
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        storage_id = self.harness.add_storage("content-from-git")[0]
        self.harness.attach_storage(storage_id)

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("git-sync")

        # paths
        self.prom_alert_dir = os.path.join(
            self.harness.charm._git_sync_mount_point_sidecar,
            self.harness.charm.SUBDIR,
            self.harness.charm.config["prometheus_alert_rules_path"],
        )
        self.prom_alert_filepath = os.path.join(self.prom_alert_dir, "alert.rule")

        self.loki_alert_dir = os.path.join(
            self.harness.charm._git_sync_mount_point_sidecar,
            self.harness.charm.SUBDIR,
            self.harness.charm.config["loki_alert_rules_path"],
        )
        self.loki_alert_filepath = os.path.join(self.loki_alert_dir, "alert.rule")

        self.git_hash_file_path = os.path.join(
            self.harness.charm._git_sync_mount_point_sidecar, self.harness.charm.SUBDIR, ".git"
        )

        # the star of the show
        self.free_standing_rule = yaml.safe_dump(
            {
                "alert": "free_standing",
                "expr": "avg(some_vector[5m]) > 5",
            }
        )

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    def test_files_appear_on_disk_after_the_last_hook_fired(self):
        """Scenario: Alert rules show up show up on disk only after config_changed etc. fired."""
        # GIVEN the current unit is the leader
        self.harness.set_leader(True)

        # AND prometheus-config relation formed
        rel_id = self.harness.add_relation("prometheus-config", "prom")
        self.harness.add_relation_unit(rel_id, "prom/0")

        # AND empty app relation data
        relation = self.harness.charm.model.get_relation("prometheus-config")
        assert relation is not None
        rel_data = relation.data[self.harness.charm.app]
        self.assertEqual(rel_data["alert_rules"], "{}")

        # WHEN the user configures the repo url
        self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

        # AND the files appear on disk AFTER the last hook fired
        container = self.harness.model.unit.get_container("git-sync")
        container.push(self.prom_alert_filepath, self.free_standing_rule, make_dirs=True)
        container.push(self.git_hash_file_path, "hash 012345", make_dirs=True)

        # AND update_status fires some time later
        self.harness.charm.on.update_status.emit()

        # THEN app relation data gets updated
        rel_data = relation.data[self.harness.charm.app]
        self.assertNotEqual(rel_data["alert_rules"], "{}")

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    @given(
        st.sampled_from(
            [
                COSConfigCharm.prometheus_relation_name,
                COSConfigCharm.loki_relation_name,
                COSConfigCharm.grafana_relation_name,
            ]
        )
    )
    def test_unit_is_active_if_repo_url_provided_hash_present_and_relation_joins(self, rel_name):
        """Scenario: Files are on disk and the charm is blocked, but now a relation joins."""
        rel_id = None
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            # GIVEN the current unit is the leader
            self.harness.set_leader(True)

            # AND the user configures the repo url
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

            # AND the files appear on disk AFTER the last hook fired
            container = self.harness.model.unit.get_container("git-sync")
            container.push(self.git_hash_file_path, "hash 012345", make_dirs=True)

            # WHEN a relation joins
            # rel_id = self.harness.add_relation("prometheus-config", "prom")
            # self.harness.add_relation_unit(rel_id, "prom/0")
            rel_id = self.harness.add_relation(rel_name, f"{rel_name}-charm")
            self.harness.add_relation_unit(rel_id, f"{rel_name}-charm/0")

            # THEN the unit goes into active state
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            self.harness.set_leader(False)
            self.harness.update_config(unset=["git_repo"])
            if rel_id:
                self.harness.remove_relation(rel_id)

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    @given(
        st.sampled_from(
            [
                COSConfigCharm.prometheus_relation_name,
                COSConfigCharm.loki_relation_name,
                # COSConfigCharm.grafana_relation_name, # TODO sandbox.put_file dashboard dummy
            ]
        )
    )
    def test_unit_is_active_if_relation_joins_first_and_then_charm_config(self, rel_name):
        """Scenario: A relation joins first, and only then the repo url is set."""
        rel_id = None
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            # GIVEN the current unit is the leader
            self.harness.set_leader(True)

            # AND a relation joins
            rel_id = self.harness.add_relation(rel_name, f"{rel_name}-charm")
            self.harness.add_relation_unit(rel_id, f"{rel_name}-charm/0")

            # WHEN the user configures the repo url
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

            # AND the files appear on disk AFTER the last hook fired
            container = self.harness.model.unit.get_container("git-sync")
            container.push(self.prom_alert_filepath, self.free_standing_rule, make_dirs=True)
            container.push(self.loki_alert_filepath, self.free_standing_rule, make_dirs=True)
            container.push(self.git_hash_file_path, "hash 012345", make_dirs=True)

            # THEN after update status app relation data gets updated
            self.harness.charm.on.update_status.emit()
            relation = self.harness.charm.model.get_relation(rel_name)
            assert relation is not None
            rel_data = relation.data[self.harness.charm.app]
            self.assertNotEqual(rel_data["alert_rules"], "{}")

            # AND the unit goes into active state
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            self.harness.set_leader(False)
            self.harness.update_config(unset=["git_repo"])
            if rel_id:
                self.harness.remove_relation(rel_id)
