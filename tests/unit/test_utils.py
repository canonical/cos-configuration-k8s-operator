#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Ops-independent unit tests for src/utils.py."""

import pytest

from src.utils import extract_remote, remote_in_known_hosts

SAMPLE_KNOWN_HOSTS = """\
# github.com:22 SSH-2.0-9ee1b2f
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB...
github.com ssh-ed25519 AAAAC3NzaC1lZD...
git.launchpad.net ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB...
"""


# ---------------------------------------------------------------------------
# extract_remote
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url, expected",
    [
        ("git@github.com:canonical/cos-configuration-k8s-operator.git", "github.com"),
        ("git@git.launchpad.net:user/project", "git.launchpad.net"),
        ("git+ssh://user@example.org/repo.git", "example.org"),
        ("git+ssh://deploy@my-host.internal:2222/repo.git", "my-host.internal"),
        pytest.param(
            "https://github.com/canonical/cos-configuration-k8s-operator.git",
            None,
            id="https_url",
        ),
        pytest.param("http://does.not.really.matter/repo.git", None, id="http_url"),
        pytest.param("", None, id="empty_string"),
    ],
)
def test_extract_remote(url, expected):
    assert extract_remote(url) == expected


@pytest.mark.parametrize(
    "remote, known_hosts, expected",
    [
        ("github.com", SAMPLE_KNOWN_HOSTS, True),
        ("git.launchpad.net", SAMPLE_KNOWN_HOSTS, True),
        ("custom-host.example.com", SAMPLE_KNOWN_HOSTS, False),
        ("github.com", "", False),
        ("github.com", "# github.com ssh-rsa AAA...", False),
        ("github.com", "\n\n  \ngithub.com ssh-rsa KEY\n\n", True),
    ],
)
def test_remote_in_known_hosts(remote, known_hosts, expected):
    assert remote_in_known_hosts(remote, known_hosts) is expected
