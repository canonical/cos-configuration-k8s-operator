#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
async def charm_under_test(ops_test: OpsTest) -> Path:
    """Charm used for integration testing."""
    path_to_built_charm = await ops_test.build_charm(".")

    return path_to_built_charm
