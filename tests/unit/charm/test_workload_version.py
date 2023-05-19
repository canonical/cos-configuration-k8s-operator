#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charm import COSConfigCharm
from ops.testing import Harness


class TestWorkloadVersion(unittest.TestCase):
    """Workload version should be set correctly in juju."""

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self):
        patcher = patch.object(COSConfigCharm, "_git_sync_version", property(lambda *_: "1.2.3"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness = Harness(COSConfigCharm)
        self.harness.add_storage("content-from-git", attach=True)
        self.harness.begin_with_initial_hooks()
        self.addCleanup(self.harness.cleanup)
        self.harness.container_pebble_ready("git-sync")

    def test_workload_version_is_set(self):
        """Check that the workload version is set correctly."""
        self.assertEqual(self.harness.get_workload_version(), "1.2.3")
