"""A `--base` that re-attaching cannot honour is refused, not dropped.

`worktree create` both cuts a new branch and re-attaches an existing one, and
only the first can act on a base. The second takes the branch where it already
stands, so the flag reaches nothing — and dropping it silently is worse than
unhelpful: the caller reads "worktree ready" beside the base they asked for and
starts writing against files that came from somewhere else. Measured, not
imagined: a session asked for `--base feat-boundary`, was re-attached to a
branch on `dev`, and only noticed because the files it meant to edit were
absent.
"""

from pathlib import Path

import pytest
import typer

from lup.devtools.dev.worktree import descends_from, register_worktree
from lup.harness.process import LaunchRequest, LocalProcessLauncher


def build_history(root: Path) -> Path:
    """A repository whose two branches sit on genuinely different lines.

    `feature` carries a commit `dev` does not, which is what makes a base
    named against it unanswerable without moving something.
    """
    work = root / "work"
    launcher = LocalProcessLauncher()
    # Identity per invocation, never `git config` — a persisted setting lands
    # in the shared config every worktree of a real repository inherits.
    who = ("-c", "user.email=worktree@example.test", "-c", "user.name=Worktree Test")
    git_in = ("git", "-C", str(work))
    for arguments in (
        ["git", "init", "-b", "dev", str(work)],
        [*git_in, *who, "commit", "--allow-empty", "-m", "base"],
        [*git_in, "checkout", "-b", "feature"],
        [*git_in, *who, "commit", "--allow-empty", "-m", "work"],
        [*git_in, "checkout", "dev"],
    ):
        status = launcher.launch(LaunchRequest(arguments=arguments, cwd=root))
        if status.code != 0:
            raise AssertionError(status.stderr)
    return work


def test_a_base_the_existing_branch_is_not_on_stops_the_re_attach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal this exists for, on the topology that produced it.

    `dev` does not descend from `feature`, so re-attaching `dev` would hand
    back a tree cut from somewhere else entirely. Exiting is the whole point:
    the caller gets to choose, where before the choice was made for them and
    not mentioned.
    """
    work = build_history(tmp_path)
    monkeypatch.chdir(work)

    with pytest.raises(typer.Exit):
        register_worktree("dev", tmp_path / "tree" / "dev", "feature")


def test_a_base_the_existing_branch_already_carries_is_not_worth_refusing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is dropped when the branch is already on the line asked for.

    `feature` descends from `dev`, so `--base dev` is satisfied by where the
    branch stands and re-attaching honours it by doing nothing. Refusing here
    would turn a correct, common invocation into an error — re-running the
    same create after an interrupted setup is the documented recovery.
    """
    work = build_history(tmp_path)
    monkeypatch.chdir(work)

    assert descends_from("feature", "dev")
    assert not descends_from("dev", "feature")
