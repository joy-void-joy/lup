"""Behavior tests for the one hooks write left in making a worktree.

`<common>/hooks/` holds scripts git executes on the host, so it is held
read-only inside the writable share — the same door `config` opens, with no
key in between. Holding it costs nothing because arming is a once-per-clone
act: `git rev-parse --git-path hooks` in a linked worktree names the shared
directory, so a guard armed once is armed for every worktree cut afterwards.

Which is what the refusal in front of it has to know. Asked about the
outstanding arming, it stays out of the way of a clone whose guards are
already current, and still stops a clone that would otherwise be handed a
worktree whose commits skip the drift gate without saying so.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer

from lup.devtools.dev import worktree
from lup.devtools.dev.git_guards import DECLARED_GUARDS, install_guards
from lup.devtools.harness.launch import relocation_hint
from tests.unit.repos import commit_file, initialized_repo

needs_a_mode_that_refuses = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root creates a file in a mode-555 directory, so the mode cannot "
    "stand in for the mount that would refuse it",
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with one commit, standing where the command would run."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def tree_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The sibling directory worktrees are created in, as `create` resolves it."""
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(worktree, "get_tree_dir", lambda: tree)
    return tree


@pytest.fixture
def hooks(repo: Path) -> Iterator[Path]:
    """This clone's hooks directory, with whatever a test held it by undone.

    Restored on the way out, or the temporary tree cannot be removed.
    """
    directory = repo / ".git" / "hooks"
    directory.mkdir(parents=True, exist_ok=True)
    yield directory
    directory.chmod(0o755)


def hold(directory: Path) -> None:
    """Hold a directory the way a read-only mount does.

    A mode this process cannot create inside stands in for the mount: it is
    the same refusal of the same syscall, and the one shape a test can take
    without a mount namespace of its own.
    """
    directory.chmod(0o555)


def arm_on_the_host(repo: Path) -> None:
    """Arm the declared guards as a clone's one host act does."""
    install_guards(DECLARED_GUARDS, repo)


@needs_a_mode_that_refuses
def test_an_armed_clone_is_not_stopped_by_hooks_it_cannot_write(
    repo: Path, hooks: Path
) -> None:
    """The write is outstanding for nobody here, so nothing is refused."""
    arm_on_the_host(repo)
    hold(hooks)

    worktree.refuse_a_blocked_arming()


@needs_a_mode_that_refuses
def test_an_unarmed_clone_meets_the_diagnosis_up_front(
    repo: Path, hooks: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case the refusal exists for, said before anything is cut."""
    hold(hooks)

    with pytest.raises(typer.Exit) as raised:
        worktree.refuse_a_blocked_arming()

    reported = capsys.readouterr().err
    assert raised.value.exit_code == 1
    assert "guard not installed" in reported
    assert "dev git-hooks install" in reported


@needs_a_mode_that_refuses
def test_a_stale_guard_is_refused_by_name_rather_than_left_standing(
    repo: Path, hooks: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The hook git runs is not the one the declaration describes.

    The case an answer keyed on presence cannot cover: the file is there and
    git runs it, so the moment reads as guarded while the body executing is
    one nobody declared.
    """
    arm_on_the_host(repo)
    installed = hooks / "pre-commit"
    installed.write_text(
        installed.read_text(encoding="utf-8") + "# an older body\n", encoding="utf-8"
    )
    hold(hooks)

    with pytest.raises(typer.Exit):
        worktree.refuse_a_blocked_arming()

    assert "is an older body" in capsys.readouterr().err


def test_an_unarmed_clone_that_can_write_is_let_through(repo: Path) -> None:
    """Nothing is refused where the arming it guards would simply happen."""
    worktree.refuse_a_blocked_arming()


@needs_a_mode_that_refuses
def test_a_worktree_is_still_made_where_the_hooks_directory_is_held(
    repo: Path, tree_dir: Path, hooks: Path
) -> None:
    """The whole point, end to end: a cut worktree inherits the armed guard.

    Hooks resolve through the shared directory, so the worktree this makes
    reads its `pre-commit` out of the same place the host armed it, and setup
    writes nothing into a directory it may not write.
    """
    arm_on_the_host(repo)
    hold(hooks)

    worktree.create(
        "topic",
        no_sync=True,
        no_copy_data=True,
        base_branch=None,
        launcher=relocation_hint,
    )

    assert (tree_dir / "topic").is_dir()
