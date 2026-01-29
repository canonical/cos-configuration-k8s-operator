#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from unittest.mock import PropertyMock, patch

import pytest
from ops.testing import (
    Container,
    Context,
    Exec,
    PeerRelation,
    Secret,
    State,
    Storage,
)

from src.charm import COSConfigCharm

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def git_sync_container():
    yield Container(
        "git-sync", execs={Exec(["/git-sync"], return_code=0, stdout="0.0")}, can_connect=True
    )


@pytest.fixture
def ctx(git_hash_file_mock):
    with patch.object(
        COSConfigCharm,
        "_repo_path",
        new_callable=PropertyMock,
        return_value=git_hash_file_mock.parent,
        create=True,
    ), patch.object(
        COSConfigCharm,
        "_git_hash_file_path",
        new_callable=PropertyMock,
        return_value=git_hash_file_mock,
        create=True,
    ):
        yield Context(COSConfigCharm)


@pytest.fixture(autouse=True)
def private_key_cleartext():
    yield """-----BEGIN OPENSSH PRIVATE KEY-----
foo
-----END OPENSSH PRIVATE KEY-----
"""


@pytest.fixture(autouse=True)
def private_key_secret(private_key_cleartext):
    yield Secret(
        id="d5oi8u7mp25c7ekusut0",
        tracked_content={"private-ssh-key": private_key_cleartext},
    )


@pytest.fixture(autouse=True)
def git_repo():
    yield {"git_repo": "http://does.not.really.matter/repo.git"}


@pytest.fixture(autouse=True)
def base_state(git_sync_container, git_repo):
    state = State(
        leader=True,
        containers=[git_sync_container],
        relations=[PeerRelation("replicas", local_app_data={"hash": "foo"})],
        config=git_repo,
        storages=[Storage("content-from-git")],
    )
    yield state


@pytest.fixture
def git_hash_file_mock(tmp_path):
    """Create a mock .git file for worktree-like structures and yield its path."""
    git_dir = tmp_path / "repo" / ".git"
    git_dir.parent.mkdir(parents=True)
    git_dir.write_text("gitdir: ../.git/worktrees/foo")
    yield git_dir
