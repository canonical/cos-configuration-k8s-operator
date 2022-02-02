#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import get_unit_address
from prometheus_workload import Prometheus
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"git-sync-image": METADATA["resources"]["git-sync-image"]["upstream-source"]}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, charm_under_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})

    # build and deploy charm from local source folder
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name=app_name)

    # without a repo configured, charm should go into blocked state
    await ops_test.model.wait_for_idle(apps=[app_name], status="blocked", timeout=1000)
    assert ops_test.model.applications[app_name].units[0].workload_status == "blocked"


@pytest.mark.abort_on_fail
async def test_relating_to_prometheus(ops_test):
    await ops_test.model.deploy("prometheus-k8s", channel="edge", application_name="prom")
    await ops_test.model.add_relation("prom", app_name)
    await ops_test.model.wait_for_idle(apps=["prom"], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_rule_files_ingested_by_prometheus(ops_test):
    client = Prometheus(host=await get_unit_address(ops_test, "prom", 0))

    # first, make sure no rules are present
    assert await client.rules("alert") == []

    # update config and wait for all apps to settle
    await ops_test.model.applications[app_name].set_config(
        {
            "git_repo": "https://github.com/canonical/cos-configuration-k8s-operator.git",
            "git_branch": "feature/fix_config_changed",
            "prometheus_alert_rules_path": "tests/samples/prometheus_alert_rules",
        }
    )

    # now prom should go back to active, but cos-config might still blocked if files showed up on
    # disk after the last hook fired
    await ops_test.model.wait_for_idle(apps=["prom"], status="active", timeout=1000)

    # in case the files show up on disk after the last hook fired, have an update_status fire now
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await asyncio.sleep(20)
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    # now wait for cos-config too to become active
    await ops_test.model.wait_for_idle(status="active", timeout=1000)

    # now, make sure rules are present
    assert (await client.rules("alert")) > []
