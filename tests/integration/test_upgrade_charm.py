#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

# Cross-base upgrades (e.g. 24.04 -> 26.04) are not supported via juju refresh.
# The charmhub charm is built for 24.04 (Python 3.12), while the local charm
# targets 26.04 (Python 3.14). Juju refresh only replaces charm code, not the
# container image, so the old container's Python cannot load the new venv.
pytestmark = pytest.mark.skip(reason="Cross-base upgrade from 24.04 to 26.04 not supported")

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
# app_name = "am"
app_name = METADATA["name"]
resources = {"git-sync-image": METADATA["resources"]["git-sync-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    assert ops_test.model
    logger.info("build charm from local source folder")

    logger.info("deploy charm from charmhub")
    await ops_test.model.deploy(
        "cos-configuration-k8s", application_name=app_name, channel="2/edge"
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="blocked", timeout=1000)

    logger.info("upgrade deployed charm with local charm %s", charm_under_test)
    await ops_test.model.applications[app_name].refresh(path=charm_under_test, resources=resources)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="blocked", timeout=1000, raise_on_error=False
    )
