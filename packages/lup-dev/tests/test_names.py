"""The launches' names: claimed unique at registration, and taken by default from the worktree's branch."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import cli
from lup_dev.host.names import claimed, shaped
from lup_dev.host.protocol import HostError, Limits, Register

if TYPE_CHECKING:
    from conftest import Shell


def asking(launch: str, name: str | None, *, exact: bool = False) -> Register:
    """A launch asking `name`, in a worktree called `work`."""
    return Register(
        launch=launch,
        runtime="claude",
        worktree=Path("/srv/work"),
        repository=Path("/srv/.git"),
        judge=Path("/srv/lup-dev"),
        container=f"lup-{launch}",
        limits=Limits(actions=[], protected=[]),
        github=None,
        name=name,
        exact=exact,
    )


def test_a_name_asked_is_taken_where_free_and_numbered_where_held() -> None:
    held = [asking("one", "dev"), asking("two", "dev-2")]
    assert claimed(asking("three", "review"), held) == "review"
    assert claimed(asking("three", "dev"), held) == "dev-3"


def test_a_name_asked_exactly_is_refused_where_held_saying_whose() -> None:
    with pytest.raises(HostError, match="`dev` is launch one's, claude in /srv/work"):
        claimed(asking("two", "dev", exact=True), [asking("one", "dev")])


def test_a_record_from_before_names_takes_its_worktree_s() -> None:
    assert claimed(asking("one", None), []) == "work"


def test_a_runtime_s_title_is_shaped_or_left() -> None:
    assert shaped("Fix the gate's cache") == "fix-the-gate-s-cache"
    assert shaped("x" * 65) is None


def test_a_launch_is_named_after_its_branch_by_default(
    repo: Path, shell: Shell
) -> None:
    assert cli.branch_name(repo) == "main"
    shell.git(repo, "switch", "-q", "-c", "feat/naming")
    assert cli.branch_name(repo) == "feat-naming"
    shell.git(repo, "switch", "-q", "--detach")
    assert cli.branch_name(repo) == repo.name
