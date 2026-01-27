#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
from pathlib import Path, PosixPath

from ops.testing import Model

logger = logging.getLogger(__name__)
container_name = "git-sync"


def get_ssh_key(container_fs: PosixPath, ssh_key_file_name: Path):
    ssh_key_file = container_fs / ssh_key_file_name.relative_to("/")
    return ssh_key_file.read_text()


def test_private_key_written_to_disk(
    ctx,
    base_state,
    git_repo,
    private_key_plain_text,
    private_key_secret,
):
    ssh_switches = ["--ssh", "--ssh-key-file"]

    # GIVEN git_ssh_key and git_ssh_key_secret are not set
    # WHEN the config changes
    with ctx(ctx.on.config_changed(), base_state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the key is wiped (or not updated) on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert "" == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
    for switch in ssh_switches:
        assert switch not in charm._git_sync_command_line()

    # GIVEN git_ssh_key is set to a plain-text SSH key
    in_state = dataclasses.replace(
        base_state, config=git_repo | {"git_ssh_key": private_key_plain_text}
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), in_state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the key exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert private_key_plain_text == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
    for switch in ssh_switches:
        assert switch in charm._git_sync_command_line()

    # GIVEN git_ssh_key is set to a secret containing the SSH key
    in_state = dataclasses.replace(
        base_state,
        config=git_repo
        | {"git_ssh_key_secret": f"secret://{private_key_secret.id}/private-ssh-key"},
        secrets=[private_key_secret],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), in_state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the key exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert private_key_plain_text == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
    for switch in ssh_switches:
        assert switch in charm._git_sync_command_line()


def test_incorrect_ssh_key_config_wipes_key(ctx, base_state, git_repo, private_key_secret):
    # GIVEN git_ssh_key_secret is not set to secret://<secret-id>/<key>
    incorrect_cfgs = [
        "foo",
        private_key_secret.id,
        f"secret:{private_key_secret.id}",
        f"secret://{private_key_secret.id}",
        f"secret://{private_key_secret.id}/incorrect-key",
        f"secret://some-model/{private_key_secret.id}/private-ssh-key",
    ]
    for cfg in incorrect_cfgs:
        # GIVEN an invalid git_ssh_key config
        in_state = dataclasses.replace(
            base_state,
            config=git_repo | {"git_ssh_key_secret": cfg},
            model=Model("some-model"),
            secrets=[private_key_secret],
        )

        # WHEN the config changes
        with ctx(ctx.on.config_changed(), in_state) as mgr:
            charm = mgr.charm
            state_out = mgr.run()

        # THEN the key is wiped (or not updated) on disk
        container_fs = state_out.get_container(container_name).get_filesystem(ctx)
        assert "" == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
        # THEN the the user is warned of their mistake
        assert "secret not found" in state_out.unit_status.message


def test_both_cfgs_set_key_written_to_disk(
    ctx,
    base_state,
    git_repo,
    private_key_plain_text,
    private_key_secret,
):
    ssh_switches = ["--ssh", "--ssh-key-file"]

    # GIVEN both git_ssh_key and git_ssh_key_secret are set
    in_state = dataclasses.replace(
        base_state,
        config=git_repo
        | {"git_ssh_key": private_key_plain_text}
        | {"git_ssh_key_secret": f"secret://{private_key_secret.id}/private-ssh-key"},
        secrets=[private_key_secret],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), in_state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the private key from the secret is preferred and exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert private_key_plain_text == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
    for switch in ssh_switches:
        assert switch in charm._git_sync_command_line()


def test_private_key_warns_user(ctx, base_state, git_repo, private_key_plain_text):
    # GIVEN git_ssh_key is set to a plain-text SSH key
    in_state = dataclasses.replace(
        base_state, config=git_repo | {"git_ssh_key": private_key_plain_text}
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), in_state) as mgr:
        state_out = mgr.run()

    # THEN the the user is warned of their mistake
    assert 'WARNING: "git_ssh_key" exposes your private key' in state_out.unit_status.message
