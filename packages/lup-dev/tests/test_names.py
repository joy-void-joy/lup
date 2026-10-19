"""The launches' names: claimed unique at registration, and taken by default from the worktree's branch."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import cli
from lup_dev.host.names import claimed, container_name, shaped
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


def test_a_container_is_named_after_its_repository_and_its_launch() -> None:
    assert container_name(Path("/srv/lup.git"), "dev") == "lup-lup-dev"
    assert container_name(Path("/srv/atlas/.git"), "feat-x") == "lup-atlas-feat-x"
    assert container_name(Path("/srv/my café"), "dev") == "lup-my-caf-dev"
    assert container_name(Path("/srv/x"), "é.1") == "lup-x-.1"


def test_a_name_whose_container_another_launch_holds_is_held() -> None:
    def of(launch: str, repository: str, name: str) -> Register:
        return asking(launch, name).model_copy(
            update={
                "repository": Path(f"/srv/{repository}.git"),
                "container": container_name(Path(f"/srv/{repository}.git"), name),
            }
        )

    dashboard = of("one", "lup-dashboard", "dev")
    wanting = of("two", "lup", "dashboard-dev").model_copy(update={"container": None})
    assert claimed(wanting, [dashboard]) == "dashboard-dev-2"
    with pytest.raises(
        HostError,
        match=(
            r"`dashboard-dev` would name its container `lup-lup-dashboard-dev`, "
            r"which is launch one's, claude in /srv/work \(`dev`\)"
        ),
    ):
        claimed(wanting.model_copy(update={"exact": True}), [dashboard])


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
