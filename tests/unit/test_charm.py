# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.model import ActiveStatus
from ops.testing import Harness

from charm import LMARulesCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(LMARulesCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _check_services_running(self, app):
        """Check that the supplied service is running and charm is ActiveStatus."""
        service = self.harness.model.unit.get_container(app).get_service(app)
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    def test_dummy(self):
        pass
