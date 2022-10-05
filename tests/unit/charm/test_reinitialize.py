#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import string
import unittest
from unittest.mock import patch

import hypothesis.strategies as st
import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from helpers import FakeProcessVersionCheck
from hypothesis import given
from ops.model import Container
from ops.testing import Harness

from charm import COSConfigCharm

logger = logging.getLogger(__name__)

ops.testing.SIMULATE_CAN_CONNECT = True


class TestReinitializeCalledOnce(unittest.TestCase):
    """Feature: Charm should reinitialize relation data only after a change.

    Background: The charm is calling `reinitialize` for prometheus, loki and grafana, which may
    have undesirable side-effects such as workload restart. Therefore reinitialisation should
    happen only when a change is introduced, and not every time charm code runs.
    """

    def setUp(self):
        self.app_name = "cos-configuration-k8s"

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    @given(st.integers(1, 5))
    def test_leader_doesnt_reinitialize_when_no_config_and_update_status_fires(self, num_units):
        """Scenario: Leader unit is deployed without config and update-status fires."""
        self.harness = Harness(COSConfigCharm)
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # GIVEN the current unit is a leader unit
        self.harness.set_leader(True)

        # AND storage is attached
        self.harness.add_storage("content-from-git", attach=True)

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("git-sync")

        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            with patch.object(
                GrafanaDashboardProvider, "_reinitialize_dashboard_data"
            ) as graf_mock, patch.object(
                LokiPushApiConsumer, "_reinitialize_alert_rules"
            ) as loki_mock, patch.object(
                PrometheusRulesProvider, "_reinitialize_alert_rules"
            ) as prom_mock:
                # GIVEN any number of units present
                for i in range(1, num_units):
                    self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

                # WHEN no config is provided

                # AND update-status fires
                self.harness.charm.on.update_status.emit()

                # THEN no reinitialization takes place
                self.assertEqual(prom_mock.call_count, 0)
                self.assertEqual(loki_mock.call_count, 0)
                self.assertEqual(graf_mock.call_count, 0)

        finally:
            self.harness.cleanup()

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    @given(st.integers(1, 5))
    def test_leader_reinitialize_once_with_config_and_update_status_fires(self, num_units):
        """Scenario: Leader unit is deployed with config and then update-status fires."""
        self.harness = Harness(COSConfigCharm)

        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # GIVEN the current unit is a leader unit
        self.harness.set_leader(True)

        # AND storage is attached
        self.harness.add_storage("content-from-git", attach=True)

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("git-sync")

        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            with patch.object(
                GrafanaDashboardProvider, "_reinitialize_dashboard_data"
            ) as graf_mock, patch.object(
                LokiPushApiConsumer, "_reinitialize_alert_rules"
            ) as loki_mock, patch.object(
                PrometheusRulesProvider, "_reinitialize_alert_rules"
            ) as prom_mock:
                # GIVEN any number of units present
                for i in range(1, num_units):
                    self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

                # WHEN the repo URL is set
                self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

                # AND hash file present
                container = self.harness.model.unit.get_container("git-sync")
                hash_file_path = os.path.join(
                    self.harness.charm._git_sync_mount_point_sidecar,
                    self.harness.charm.SUBDIR,
                    ".git",
                )
                container.push(hash_file_path, "gitdir: ./abcd1234", make_dirs=True)

                # AND update-status fires
                self.harness.charm.on.update_status.emit()

                # AND again
                self.harness.charm.on.update_status.emit()

                # THEN reinitialization takes place only once
                self.assertEqual(prom_mock.call_count, 1)
                self.assertEqual(loki_mock.call_count, 1)
                self.assertEqual(graf_mock.call_count, 1)

        finally:
            self.harness.cleanup()

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    @given(st.integers(1, 5))
    def test_leader_reinitialize_once_when_repo_unset(self, num_units):
        """Scenario: Leader unit is deployed with config and then repo is unset."""
        self.harness = Harness(COSConfigCharm)

        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # GIVEN the current unit is a leader unit
        self.harness.set_leader(True)

        # AND storage is attached
        self.harness.add_storage("content-from-git", attach=True)

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("git-sync")

        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND hash file present
            container = self.harness.model.unit.get_container("git-sync")
            hash_file_path = os.path.join(
                self.harness.charm._git_sync_mount_point_sidecar, self.harness.charm.SUBDIR, ".git"
            )
            container.push(hash_file_path, "gitdir: ./abcd1234", make_dirs=True)

            # AND the repo URL is set
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})
            self.harness.charm.on.update_status.emit()

            with patch.object(
                GrafanaDashboardProvider, "_reinitialize_dashboard_data"
            ) as graf_mock, patch.object(
                LokiPushApiConsumer, "_reinitialize_alert_rules"
            ) as loki_mock, patch.object(
                PrometheusRulesProvider, "_reinitialize_alert_rules"
            ) as prom_mock:
                print("INSIDE CTXMGR")
                # WHEN repo url is unset
                self.harness.update_config(unset=["git_repo"])
                # Unset is better than manually setting to an empty string because it would capture
                # the case of the default value being changed from empty string.

                # AND additional hooks fire
                self.harness.charm.on.update_status.emit()
                self.harness.update_config({"git_branch": "first"})
                self.harness.update_config({"git_branch": "second"})
                self.harness.charm.on.update_status.emit()

                # THEN reinitialization occurred only once more since repo was unset
                self.assertEqual(prom_mock.call_count, 1)
                self.assertEqual(loki_mock.call_count, 1)
                self.assertEqual(graf_mock.call_count, 1)

        finally:
            self.harness.cleanup()


class TestConfigChanged(unittest.TestCase):
    """Feature: When repo, branch or rev config options change, relation data needs to be updated.

    Background: Some config options are expected to change the contents of the repo folder on disk.
    In this case, the charm have the changes reflected in relation data so they are communicated
    over to the related apps.
    """

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: "", "")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    @given(
        st.tuples(
            st.sampled_from(["git_repo", "git_branch", "git_rev"]),
            st.text(alphabet=list(string.ascii_lowercase + string.ascii_uppercase), min_size=1),
        )
    )
    def test_reinitialize_is_called_when_config_changes(self, config_option):
        """Scenario: Unit is deployed with a certain config, and then config is changed."""
        # mock charm container's mount
        self.harness = Harness(COSConfigCharm)
        self.peer_rel_id = self.harness.add_relation("replicas", self.harness.model.app.name)

        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            # GIVEN the current unit is a leader unit
            self.harness.set_leader(True)

            # AND storage is attached
            self.harness.add_storage("content-from-git", attach=True)

            self.harness.begin_with_initial_hooks()
            self.harness.container_pebble_ready("git-sync")

            # AND some initial config is provided
            fake_repo_url = "http://does.not.really.matter/repo.git"
            self.harness.update_config({"git_repo": fake_repo_url})

            container = self.harness.model.unit.get_container("git-sync")
            hash_file_path = os.path.join(
                self.harness.charm._git_sync_mount_point_sidecar, self.harness.charm.SUBDIR, ".git"
            )
            container.push(hash_file_path, "gitdir: ./abcd1234", make_dirs=True)

            self.harness.charm.on.update_status.emit()

            with patch.object(
                GrafanaDashboardProvider, "_reinitialize_dashboard_data"
            ) as graf_mock, patch.object(
                LokiPushApiConsumer, "_reinitialize_alert_rules"
            ) as loki_mock, patch.object(
                PrometheusRulesProvider, "_reinitialize_alert_rules"
            ) as prom_mock:
                # WHEN config option is updated
                self.harness.update_config({config_option[0]: config_option[1]})

                container = self.harness.model.unit.get_container("git-sync")
                hash_file_path = os.path.join(
                    self.harness.charm._git_sync_mount_point_sidecar,
                    self.harness.charm.SUBDIR,
                    ".git",
                )
                container.push(hash_file_path, "gitdir: ./" + config_option[1], make_dirs=True)

                # AND update-status fires
                self.harness.charm.on.update_status.emit()

                # THEN reinitialization occurred only once more since config changed
                self.assertGreater(prom_mock.call_count, 0)
                self.assertGreater(loki_mock.call_count, 0)
                self.assertGreater(graf_mock.call_count, 0)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            self.harness.cleanup()
