#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from grafana_workload import Grafana
from helpers import get_unit_address
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
async def test_relating_to_grafana(ops_test):
    await ops_test.model.deploy(
        "grafana-k8s", channel="edge", application_name="grafana", trust=True
    )
    await ops_test.model.add_relation("grafana", app_name)
    await ops_test.model.wait_for_idle(apps=["grafana"], status="active", timeout=1000)


async def test_dashboard_files_ingested_by_grafana(ops_test):
    action = await ops_test.model.applications["grafana"].units[0].run_action("get-admin-password")
    await action.wait()
    admin_output = await ops_test.model.get_action_output(action.id)
    # Output looks like this:
    # {'Code': '0', 'admin-pasword': 'HP0IOA0tKte5'}
    admin_password = admin_output["admin-password"]

    unit_ip = await get_unit_address(ops_test, "grafana", 0)
    client = Grafana(host=unit_ip, pw=admin_password)

    # first, make sure no dashboards are present
    assert len(await client.dashboards_all()) == 0

    # update config and wait for all apps to settle
    await ops_test.model.applications[app_name].set_config(
        {
            "git_repo": "https://github.com/canonical/cos-configuration-k8s-operator.git",
            "git_branch": "main",
            "grafana_dashboards_path": "tests/samples/grafana_dashboards",
        }
    )

    # now grafana should go back to active, but cos-config might still be blocked if files showed
    # up on disk after the last hook fired
    await ops_test.model.wait_for_idle(apps=["grafana"], status="active", timeout=1000)

    # in case the files show up on disk after the last hook fired, have an update_status fire now
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await asyncio.sleep(20)
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    # now wait for cos-config too to become active
    await ops_test.model.wait_for_idle(status="active", timeout=1000)

    # now, make sure dashboards are present
    all_dashboards = await client.dashboards_all()
    dashboard_titles = [dash["title"] for dash in all_dashboards]
    assert "up with dropdowns" in dashboard_titles
