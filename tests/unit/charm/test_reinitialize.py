#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import unittest
from unittest.mock import patch

import hypothesis.strategies as st
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LokiPushApiConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from helpers import TempFolderSandbox
from hypothesis import given
from ops.testing import Harness

from charm import COSConfigCharm

logger = logging.getLogger(__name__)


class TestReinitializeCalledOnce(unittest.TestCase):
    """Feature: Charm should reinitialize relation data only after a change.

    Background: The charm is calling `reinitialize` for prometheus, loki and grafana, which may
    have undesirable side-effects such as workload restart. Therefore reinitialisation should
    happen only when a change is introduced, and not every time charm code runs.
    """

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self):
        # mock charm container's mount
        self.sandbox = TempFolderSandbox()
        self.abs_repo_path = os.path.join(self.sandbox.root, "repo")
        COSConfigCharm._repo_path = self.abs_repo_path

        self.harness = Harness(COSConfigCharm)
        self.addCleanup(self.harness.cleanup)

        self.app_name = "cos-configuration-k8s"
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)
        self.harness.begin_with_initial_hooks()

        self.container_name = self.harness.charm._container_name

        # paths relative to sandbox root
        self.git_hash_file_path = os.path.relpath(
            self.harness.charm._git_hash_file_path, self.sandbox.root
        )

    @patch.object(GrafanaDashboardProvider, "_reinitialize_dashboard_data")
    @patch.object(LokiPushApiConsumer, "_reinitialize_alert_rules")
    @patch.object(PrometheusRulesProvider, "_reinitialize_alert_rules")
    @given(st.integers(1, 5))
    def test_leader_doesnt_reinitialize_when_no_config_and_update_status_fires(
        self, prom_mock, loki_mock, graf_mock, num_units
    ):
        """Scenario: Leader unit is deployed without config and update-status fires."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit is a leader unit
            self.harness.set_leader(True)

            # WHEN no config is provided

            # AND update-status fires
            self.harness.charm.on.update_status.emit()

            # THEN no reinitialization takes place
            self.assertEqual(prom_mock.call_count, 0)
            self.assertEqual(loki_mock.call_count, 0)
            self.assertEqual(graf_mock.call_count, 0)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            prom_mock.resert_mock()
            loki_mock.resert_mock()
            graf_mock.resert_mock()

    @given(st.integers(1, 5))
    def test_leader_reinitialize_once_with_config_and_update_status_fires(self, num_units):
        """Scenario: Leader unit is deployed with config and then update-status fires."""
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

                # AND the current unit is a leader unit
                self.harness.set_leader(True)

                # WHEN the repo URL is set
                self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

                # AND hash file present
                self.sandbox.put_file(self.git_hash_file_path, "hash 012345")

                # AND update-status fires
                self.harness.charm.on.update_status.emit()

                # AND again
                self.harness.charm.on.update_status.emit()

                # THEN reinitialization takes place only once
                self.assertEqual(prom_mock.call_count, 1)
                self.assertEqual(loki_mock.call_count, 1)
                self.assertEqual(graf_mock.call_count, 1)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
            self.harness.update_config(unset=["git_repo"])
            self.sandbox.clear()

    @given(st.integers(1, 5))
    def test_leader_reinitialize_once_when_repo_unset(self, num_units):
        """Scenario: Leader unit is deployed with config and then repo is unset."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit is a leader unit
            self.harness.set_leader(True)

            # AND hash file present and the repo URL is set
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})
            self.sandbox.put_file(self.git_hash_file_path, "hash 012345")
            self.harness.charm.on.update_status.emit()

            with patch.object(
                GrafanaDashboardProvider, "_reinitialize_dashboard_data"
            ) as graf_mock, patch.object(
                LokiPushApiConsumer, "_reinitialize_alert_rules"
            ) as loki_mock, patch.object(
                PrometheusRulesProvider, "_reinitialize_alert_rules"
            ) as prom_mock:
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
            # cleanup added units to prep for reentry by hypothesis' strategy
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
            self.harness.update_config(unset=["git_repo", "git_branch"])
            self.sandbox.clear()
