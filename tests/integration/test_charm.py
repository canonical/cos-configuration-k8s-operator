#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import urllib.request
from pathlib import Path

import pytest
import yaml
from helpers import get_unit_address  # type: ignore[import]

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # build and deploy charm from local source folder
    charm_under_test = await ops_test.build_charm(".")
    resources = {"git-sync-image": METADATA["resources"]["git-sync-image"]["upstream-source"]}
    await ops_test.model.deploy(charm_under_test, resources=resources, application_name="rules")

    # due to a juju bug, occasionally some charms finish a startup sequence with "waiting for IP
    # address"
    # issuing dummy update_status just to trigger an event
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})

    await ops_test.model.wait_for_idle(apps=["rules"], status="active", timeout=1000)
    assert ops_test.model.applications["rules"].units[0].workload_status == "active"

    # effectively disable the update status from firing
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


@pytest.mark.abort_on_fail
async def test_relating_to_prometheus(ops_test):
    await ops_test.model.deploy("prometheus-k8s", channel="edge", application_name="prom")
    await ops_test.model.add_relation("prom", "rules")
    await ops_test.model.wait_for_idle(apps=["prom"], status="active", timeout=1000)


@pytest.mark.abort_on_fail
async def test_rule_files_ingested_by_prometheus(ops_test):
    prom_url = f"http://{get_unit_address(ops_test, 'prom', 0)}:9090/api/v1/rules"

    def _get():
        # Response looks like this:
        # {
        #   "status": "success",
        #   "data": {
        #     "groups": []
        #   }
        # }
        response = urllib.request.urlopen(prom_url, data=None, timeout=2.0)
        assert response.code == 200
        return json.loads(response.read())

    # first, make sure no rules are present
    assert _get()["data"]["groups"] == []

    # update config and wait for all apps to settle
    await ops_test.model.applications["rules"].set_config(
        {
            "git-sync::repo": "https://github.com/canonical/prometheus-operator.git",
            "git-sync::branch": "main",
            "prometheus_relpath": "tests/unit/prometheus_alert_rules",
        }
    )
    await ops_test.model.wait_for_idle(status="active", timeout=1000)

    # now, make sure rules are present
    assert len(_get()["data"]["groups"]) > 0
