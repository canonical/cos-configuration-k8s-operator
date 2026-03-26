#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pure helper utilities for cos-configuration-k8s (no ops dependency)."""

import re
from typing import Optional


def extract_remote(repo_url: str) -> Optional[str]:
    """Extract the SSH remote hostname from a git repo URL.

    Supports:
      - git@<remote>:<user>/...
      - git+ssh://<user>@<remote>/...

    Returns the hostname, or None if no SSH remote could be parsed.
    """
    matches = re.findall(r"@(.+?)[:/]", repo_url)
    return matches[0] if matches else None


def remote_in_known_hosts(remote: str, known_hosts_content: str) -> bool:
    """Check whether *remote* appears as a host entry in *known_hosts_content*."""
    for line in known_hosts_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split()[0] == remote:
            return True
    return False
