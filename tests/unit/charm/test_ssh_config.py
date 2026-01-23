import logging
from pathlib import Path, PosixPath

import pytest
from ops.testing import Container, Context, Exec, Model, PeerRelation, Secret, State, Storage

from src.charm import COSConfigCharm

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def git_sync_container():
    yield Container(
        "git-sync", execs={Exec(["/git-sync"], return_code=0, stdout="0.0")}, can_connect=True
    )


@pytest.fixture
def ctx():
    yield Context(COSConfigCharm)


@pytest.fixture(autouse=True)
def private_key_plain_text():
    yield """-----BEGIN OPENSSH PRIVATE KEY-----
foo
-----END OPENSSH PRIVATE KEY-----
"""


@pytest.fixture(autouse=True)
def private_key_secret(private_key_plain_text):
    yield Secret(
        id="d5oi8u7mp25c7ekusut0",
        tracked_content={"private-ssh-key": private_key_plain_text},
    )


def get_ssh_key(container_fs: PosixPath, ssh_key_file_name: Path):
    ssh_key_file = container_fs / ssh_key_file_name.relative_to("/")
    return ssh_key_file.read_text()


def test_private_key_written_to_disk(
    ctx, git_sync_container, private_key_plain_text, private_key_secret
):
    container_name = "git-sync"
    git_repo = {"git_repo": "http://does.not.really.matter/repo.git"}

    # GIVEN git_ssh_key and git_ssh_key_secret are not set
    state = State(
        leader=True,
        containers=[git_sync_container],
        config=git_repo,  # pyright: ignore[reportArgumentType]
        storages=[Storage("content-from-git")],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN no key exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    with pytest.raises(FileNotFoundError):
        get_ssh_key(container_fs, Path(charm._ssh_key_file_name))

    # GIVEN git_ssh_key is set to a plain-text SSH key
    state = State(
        leader=True,
        containers=[git_sync_container],
        config=git_repo | {"git_ssh_key": private_key_plain_text},  # pyright: ignore[reportArgumentType]
        storages=[Storage("content-from-git")],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the key exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert private_key_plain_text == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))

    # GIVEN git_ssh_key is set to a secret containing the SSH key
    state = State(
        leader=True,
        containers=[git_sync_container],
        config=git_repo | {"git_ssh_key_secret": f"secret://{private_key_secret.id}"},  # pyright: ignore[reportArgumentType]
        secrets=[private_key_secret],
        storages=[Storage("content-from-git")],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), state) as mgr:
        charm = mgr.charm
        state_out = mgr.run()

    # THEN the key exists on disk
    container_fs = state_out.get_container(container_name).get_filesystem(ctx)
    assert private_key_plain_text == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))


def test_private_key_warns_user(ctx, git_sync_container, private_key_plain_text):
    git_repo = {"git_repo": "http://does.not.really.matter/repo.git"}

    # GIVEN git_ssh_key is set to a plain-text SSH key
    state = State(
        leader=True,
        containers=[git_sync_container],
        config=git_repo | {"git_ssh_key": private_key_plain_text},  # pyright: ignore[reportArgumentType]
        storages=[Storage("content-from-git")],
    )

    # WHEN the config changes
    with ctx(ctx.on.config_changed(), state) as mgr:
        state_out = mgr.run()

    # THEN the the user is warned of their mistake
    assert 'WARNING: "git_ssh_key" exposes your private key' in state_out.app_status.message


def test_unset_git_ssh_key_config_wipes_key(ctx, git_sync_container, private_key_plain_text, private_key_secret):
    container_name = "git-sync"
    git_repo = {"git_repo": "http://does.not.really.matter/repo.git"}

    # TODO: Turn this in a paramatrize test to see the input, expected side-by-side
    incorrect_cfgs = [
        "foo",
        private_key_secret.id,
        f"secret:{private_key_secret.id}",
        f"secret://some-model/{private_key_secret.id}",
    ]
    for cfg in incorrect_cfgs:
        # GIVEN an invalid git_ssh_key config
        state = State(
            leader=True,
            model=Model("some-model"),
            containers=[git_sync_container],
            config=git_repo | {"git_ssh_key_secret": cfg},  # pyright: ignore[reportArgumentType]
            storages=[Storage("content-from-git")],
        )

        # WHEN the config changes
        with ctx(ctx.on.config_changed(), state) as mgr:
            charm = mgr.charm
            state_out = mgr.run()

        # THEN an empty key exists on disk
        container_fs = state_out.get_container(container_name).get_filesystem(ctx)
        assert "" == get_ssh_key(container_fs, Path(charm._ssh_key_file_name))
