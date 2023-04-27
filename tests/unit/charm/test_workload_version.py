#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import ops
from charm import COSConfigCharm
from helpers import FakeProcessVersionCheck
from ops.model import Container
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True


class TestWorkloadVersion(unittest.TestCase):
    """Workload version should be set correctly in juju."""

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self):
        self.harness = Harness(COSConfigCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.add_storage("content-from-git", attach=True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("git-sync")

    def test_workload_version_is_set(self):
        """Check that the workload version is set correctly."""
        self.assertEqual(self.harness.get_workload_version(), "0.1.0")
