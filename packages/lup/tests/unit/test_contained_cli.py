"""A session opened by a program is contained by the program it is started as.

The wrapper is the whole seam: both runtimes take a path to run instead of
the CLI they would have found, so what is asserted here is what that file
says and which mounts the argv behind it was built from — not that a
container started, which needs an engine no unit test has.
"""

import os

import sh
from pathlib import Path
from unittest.mock import Mock

import pytest

from lup.devtools.harness import contained
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.sandbox.rail import Lease, worker_lease

ARGV = ["podman", "run", "-i", "image"]


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """The argv builder, stubbed, so the call it was made with can be read."""
    builder = Mock(return_value=ARGV)
    monkeypatch.setattr(contained, "contained_argv", builder)
    return builder


def written(tmp_path: Path, recorded: Mock, lease: Lease | None = None) -> Path:
    """One wrapper written over a checkout, with the defaults under test."""
    root = tmp_path / "checkout"
    root.mkdir()
    sh.Command("git").bake("-C", str(root), _tty_out=False)("init", "-b", "main")
    return contained.contained_cli(
        tmp_path / "enter.sh",
        Mock(),
        Mock(),
        root,
        "claude",
        CLAUDE_LOGIN,
        lease=lease,
    )


def test_the_wrapper_is_a_program_a_runtime_can_start(
    tmp_path: Path, recorded: Mock
) -> None:
    """Executable, because being named as a program is what a runtime does."""
    wrapper = written(tmp_path, recorded)

    assert os.access(wrapper, os.X_OK)
    assert "claude" in wrapper.read_text()


def test_a_contained_session_is_held_to_the_tree_it_was_given(
    tmp_path: Path, recorded: Mock
) -> None:
    """The default lease, for a session nobody is watching open."""
    written(tmp_path, recorded)

    assert recorded.call_args.kwargs["lease"] == worker_lease(tmp_path / "checkout")


def test_a_caller_naming_its_own_mounts_gets_them(
    tmp_path: Path, recorded: Mock
) -> None:
    """A session meant to reach further, or nothing at all, says so."""
    lease = Lease(read_only={tmp_path: str(tmp_path)})

    written(tmp_path, recorded, lease)

    assert recorded.call_args.kwargs["lease"] == lease


def test_the_streams_are_the_protocol_the_sdk_speaks(
    tmp_path: Path, recorded: Mock
) -> None:
    """Not offered: a session opened through the SDK has no terminal."""
    written(tmp_path, recorded)

    assert recorded.call_args.kwargs["streams"] == "piped"
