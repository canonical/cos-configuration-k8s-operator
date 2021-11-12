#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import unittest
from unittest.mock import patch

import hypothesis.strategies as st
from helpers import TempFolderSandbox
from hypothesis import given
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import COSConfigCharm

logger = logging.getLogger(__name__)


class TestStatusVsConfig(unittest.TestCase):
    """Feature: Charm's status should reflect the completeness of the config.

    Background: For the git-sync sidecar to run, a mandatory config option is needed: repo's URL.
    As long as it is missing, the charm should be "Blocked".
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

    @given(st.booleans(), st.integers(1, 5))
    def test_unit_is_blocked_if_no_config_provided(self, is_leader, num_units):
        """Scenario: Unit is deployed without any user-provided config."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit could be either a leader or not
            self.harness.set_leader(is_leader)

            # WHEN no config is provided

            # THEN the unit goes into blocked state
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

            # AND pebble plan is empty
            plan = self.harness.get_container_pebble_plan(self.harness.charm._container_name)
            self.assertEqual(plan.to_dict(), {})

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            self.harness.set_leader(False)
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

    @given(st.booleans(), st.integers(1, 5))
    def test_unit_is_blocked_if_repo_url_provided_but_hash_missing(self, is_leader, num_units):
        """Scenario: Unit is deployed, the repo url config is set after, but hash file missing."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit could be either a leader or not
            self.harness.set_leader(is_leader)

            # WHEN the repo URL is set
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

            # AND hash file missing

            # THEN pebble plan contains the service AND service is running (only if a leader unit)
            if is_leader:
                plan = self.harness.get_container_pebble_plan(self.container_name)
                self.assertIn(self.harness.charm._service_name, plan.services)
                services = self.harness.model.unit.get_container(
                    self.container_name
                ).get_services()
                self.assertTrue(all(service.is_running() for service in services))

            # AND the unit goes into blocked state
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            self.harness.set_leader(False)
            for i in reversed(range(1, num_units)):
                self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
            self.harness.update_config(unset=["git_repo"])

    @given(st.integers(1, 5))
    def test_unit_is_active_if_repo_url_provided_and_hash_present(self, num_units):
        """Scenario: Unit is deployed, the repo url config is set after, and hash file present."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            # for i in range(1, num_units):
            #     self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit is a leader (otherwise won't be able to update app data)
            self.harness.set_leader(True)

            # WHEN the repo URL is set
            self.harness.update_config({"git_repo": "http://does.not.really.matter/repo.git"})

            # AND hash file present
            print("PUT FILE")
            self.sandbox.put_file(self.git_hash_file_path, "hash 012345")

            # THEN pebble plan contains the service
            plan = self.harness.get_container_pebble_plan(self.container_name)
            self.assertIn(self.harness.charm._service_name, plan.services)

            # AND service is running
            services = self.harness.model.unit.get_container(self.container_name).get_services()
            self.assertTrue(all(service.is_running() for service in services))

            # AND the unit goes into active state
            # first need to emit update-status because hash file showed up after hooks fired
            self.harness.charm.on.update_status.emit()
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        finally:
            # cleanup added units to prep for reentry by hypothesis' strategy
            # for i in reversed(range(1, num_units)):
            #     self.harness.remove_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")
            self.harness.update_config(unset=["git_repo"])
            self.sandbox.clear()
