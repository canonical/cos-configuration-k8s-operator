#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import ops
from ops.testing import Harness

import charm
from charm import COSConfigCharm, SlothSloProvider

logger = logging.getLogger(__name__)

ops.testing.SIMULATE_CAN_CONNECT = True  # pyright: ignore


class TestSlothSloProvider(unittest.TestCase):
    """Feature: SlothSloProvider should read SLO files and forward them to sloth."""

    def setUp(self):
        self.app_name = "cos-configuration-k8s"

        patcher = patch.object(COSConfigCharm, "_git_sync_version", property(lambda *_: "1.2.3"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        # Mock out other providers' reinitialize methods to focus on sloth
        patcher = patch.object(charm.PrometheusRulesProvider, "_reinitialize_alert_rules")
        self.prom_mock = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(charm.GrafanaDashboardProvider, "_reinitialize_dashboard_data")
        self.graf_mock = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(charm.LokiPushApiConsumer, "_reinitialize_alert_rules")
        self.loki_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_slo_files_empty_directory(self):
        """Scenario: SlothSloProvider._read_slo_files returns empty string for non-existent dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent_dir = os.path.join(tmpdir, "does-not-exist")
            mock_charm = MagicMock()
            provider = SlothSloProvider(mock_charm, "sloth", non_existent_dir)

            result = provider._read_slo_files()

            self.assertEqual(result, "")

    def test_read_slo_files_single_file(self):
        """Scenario: SlothSloProvider._read_slo_files reads a single YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slo_file = os.path.join(tmpdir, "test.yaml")
            with open(slo_file, "w") as f:
                f.write("version: prometheus/v1\nservice: test-service")

            mock_charm = MagicMock()
            provider = SlothSloProvider(mock_charm, "sloth", tmpdir)

            result = provider._read_slo_files()

            self.assertIn("version: prometheus/v1", result)
            self.assertIn("service: test-service", result)

    def test_read_slo_files_multiple_files(self):
        """Scenario: SlothSloProvider._read_slo_files combines multiple YAML files with ---."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slo_file1 = os.path.join(tmpdir, "test1.yaml")
            with open(slo_file1, "w") as f:
                f.write("version: prometheus/v1\nservice: service1")

            slo_file2 = os.path.join(tmpdir, "test2.yaml")
            with open(slo_file2, "w") as f:
                f.write("version: prometheus/v1\nservice: service2")

            mock_charm = MagicMock()
            provider = SlothSloProvider(mock_charm, "sloth", tmpdir)

            result = provider._read_slo_files()

            self.assertIn("service: service1", result)
            self.assertIn("service: service2", result)
            self.assertIn("---", result)

    def test_read_slo_files_only_yaml_extensions(self):
        """Scenario: SlothSloProvider._read_slo_files only reads .yaml/.yml files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = os.path.join(tmpdir, "test.yaml")
            with open(yaml_file, "w") as f:
                f.write("version: prometheus/v1\nservice: yaml-service")

            yml_file = os.path.join(tmpdir, "test.yml")
            with open(yml_file, "w") as f:
                f.write("version: prometheus/v1\nservice: yml-service")

            txt_file = os.path.join(tmpdir, "test.txt")
            with open(txt_file, "w") as f:
                f.write("version: prometheus/v1\nservice: txt-service")

            mock_charm = MagicMock()
            provider = SlothSloProvider(mock_charm, "sloth", tmpdir)

            result = provider._read_slo_files()

            self.assertIn("yaml-service", result)
            self.assertIn("yml-service", result)
            self.assertNotIn("txt-service", result)

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: ("", ""))
    def test_sloth_reinitialize_called_on_hash_change(self):
        """Scenario: SlothSloProvider._reinitialize_slo_specs is called when hash changes."""
        self.harness = Harness(COSConfigCharm)
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # GIVEN the current unit is a leader unit
        self.harness.set_leader(True)
        self.harness.add_storage("content-from-git", attach=True)
        self.harness.begin_with_initial_hooks()

        try:
            # Mock the sloth provider's reinitialize method
            with patch.object(
                self.harness.charm.sloth_slo_provider, "_reinitialize_slo_specs"
            ) as sloth_mock:
                # WHEN the repo URL is set
                self.harness.update_config({"git_repo": "http://test.repo/repo.git"})

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

                # THEN sloth reinitialization takes place
                self.assertEqual(sloth_mock.call_count, 1)

                # WHEN update-status fires again without hash change
                self.harness.charm.on.update_status.emit()

                # THEN sloth reinitialization is not called again
                self.assertEqual(sloth_mock.call_count, 1)

        finally:
            self.harness.cleanup()

    @patch("charm.COSConfigCharm._exec_sync_repo", lambda *a, **kw: ("", ""))
    def test_sloth_relation_joined_triggers_common_exit_hook(self):
        """Scenario: Sloth relation joined event triggers reinitialization."""
        self.harness = Harness(COSConfigCharm)
        self.peer_rel_id = self.harness.add_relation("replicas", self.app_name)

        # GIVEN the current unit is a leader unit
        self.harness.set_leader(True)
        self.harness.add_storage("content-from-git", attach=True)
        self.harness.begin_with_initial_hooks()

        try:
            # WHEN the repo URL is set
            self.harness.update_config({"git_repo": "http://test.repo/repo.git"})

            # AND hash file present
            container = self.harness.model.unit.get_container("git-sync")
            hash_file_path = os.path.join(
                self.harness.charm._git_sync_mount_point_sidecar,
                self.harness.charm.SUBDIR,
                ".git",
            )
            container.push(hash_file_path, "gitdir: ./abcd1234", make_dirs=True)

            with patch.object(
                self.harness.charm.sloth_slo_provider, "_reinitialize_slo_specs"
            ) as sloth_mock:
                # WHEN sloth relation is joined
                sloth_rel_id = self.harness.add_relation("sloth", "sloth-k8s")
                self.harness.add_relation_unit(sloth_rel_id, "sloth-k8s/0")

                # THEN sloth reinitialization takes place
                self.assertEqual(sloth_mock.call_count, 1)

        finally:
            self.harness.cleanup()
