"""Whether the read-only binds a lease asked for are in the mount table.

A read-only *file* bind is detached by the kernel when the host renames over
the file, which is how git rewrites `config`; what is left is a writable file
the lease still calls held. These hold the two readings of the table -- the
probe a launch runs behind its argv, and the check a session runs on itself
-- to the table rather than to the lease. No container is started: a stub
`findmnt` answers for a table, which is the one input both readings take.
"""

from os import defpath
from pathlib import Path

import pytest

import lup.sandbox.observed as observed
from lup.execution.shell import LazyCommand
from lup.harness.requirements import BindProbe, HostFacts
from lup.harness.toolchain import read_only_binds_requirement


def stub_table(tmp_path: Path, held: list[Path]) -> Path:
    """A `findmnt` answering `--mountpoint P --options ro` from a list of paths."""
    listed = tmp_path / "held"
    listed.write_text("".join(f"{path}\n" for path in held), encoding="utf-8")
    directory = tmp_path / "bin"
    directory.mkdir()
    stub = directory / "findmnt"
    stub.write_text(f'#!/bin/sh\ngrep -qxF "$2" {listed}\n', encoding="utf-8")
    stub.chmod(0o755)
    return directory


def test_a_probe_names_every_bind_the_table_does_not_hold(tmp_path: Path) -> None:
    config = tmp_path / "repo.git" / "config"
    hooks = tmp_path / "repo.git" / "hooks"
    directory = stub_table(tmp_path, [hooks])
    facts = HostFacts(read_only_binds=[config, hooks])

    outcome = (
        BindProbe().given(facts).behind(["env", f"PATH={directory}:{defpath}"]).run()
    )

    assert not outcome.proved
    assert str(config) in outcome.detail
    assert str(hooks) not in outcome.detail


def test_a_probe_over_a_held_lease_proves_itself(tmp_path: Path) -> None:
    shared = tmp_path / "a path with spaces.git"
    directory = stub_table(tmp_path, [shared])
    facts = HostFacts(read_only_binds=[shared])

    outcome = (
        BindProbe().given(facts).behind(["env", f"PATH={directory}:{defpath}"]).run()
    )

    assert outcome.proved


def test_an_unaimed_probe_tested_nothing_and_says_so() -> None:
    outcome = BindProbe().run()
    assert not outcome.exercised
    assert not outcome.proved


def test_the_binds_are_verified_at_launch_inside_the_container() -> None:
    required = read_only_binds_requirement()
    assert required.at_launch
    assert required.where == "image"
    assert required.absence.refuses()


def test_a_session_names_the_bind_a_host_rewrite_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = str(tmp_path / "repo.git" / "config")
    hooks = str(tmp_path / "repo.git" / "hooks")
    directory = stub_table(tmp_path, [Path(hooks)])
    monkeypatch.setattr(
        observed, "findmnt", LazyCommand(str(directory / "findmnt"), tty_out=False)
    )

    assert observed.unheld([config, hooks]) == [config]
