"""Behavior tests for a worktree that exists without being ready.

Creation registers the worktree in one git call and makes it usable in
several more, so any failure between them leaves a directory whose existence
says nothing about its state. What is pinned here is that the difference is
observable and acted on: a re-run finishes what was left, and a run that
cannot finish says which steps did not, rather than reporting the success
that sends an agent off diagnosing phantom errors in correct code.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
import sh
import typer

from lup.devtools.dev import worktree
from lup.devtools.harness.launch import relocation_hint
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout with an origin, which is what worktrees are cut in.

    The remote is part of the fixture rather than one test's setup because a
    branch is given one at creation: without it every case here would run the
    offline path, and the step that pushes would never be exercised at all.
    """
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    sh.Command("git")("init", "--bare", str(tmp_path / "origin.git"), _tty_out=False)
    git("remote", "add", "origin", str(tmp_path / "origin.git"))
    git("push", "-u", "origin", "main")
    return work


@pytest.fixture
def tree_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The sibling directory worktrees are created in, as `create` resolves it."""
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(worktree, "get_tree_dir", lambda: tree)
    return tree


def repo_git(work: Path) -> sh.Command:
    return sh.Command("git").bake("-C", str(work), _tty_out=False)


def create(name: str, no_sync: bool = True, no_copy_data: bool = True) -> None:
    """Create a worktree the way the CLI does, without the slow steps."""
    worktree.create(
        name,
        no_sync=no_sync,
        no_copy_data=no_copy_data,
        base_branch=None,
        launcher=relocation_hint,
    )


def interrupted_creation(repo: Path, tree_dir: Path, name: str) -> Path:
    """The exact half-made worktree an interrupted config write leaves.

    Registered by `worktree add`, then abandoned before anything recorded a
    base or built an environment — which is what a config lock, or any other
    failure between the git call and the rest, leaves on disk.
    """
    repo_git(repo)("worktree", "add", str(tree_dir / name), "-b", name)
    return tree_dir / name


def test_dependency_sync_matches_ci_without_inheriting_the_source_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = Mock()
    invocation = Mock()
    command.return_value = invocation
    monkeypatch.setattr(sh, "Command", command)

    worktree.sync_dependencies(tmp_path)

    command.assert_called_once_with("env")
    invocation.assert_called_once_with(
        "-u",
        "VIRTUAL_ENV",
        "uv",
        "sync",
        "--all-extras",
        _cwd=str(tmp_path),
    )


@pytest.mark.usefixtures("tree_dir")
def test_a_finished_worktree_reports_itself_active(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`already active` is kept for the case where it is true."""
    monkeypatch.chdir(repo)
    create("topic")

    with pytest.raises(typer.Exit) as exit_info:
        create("topic")

    assert exit_info.value.exit_code == 0


def test_a_half_made_worktree_is_finished_by_re_running(
    repo: Path,
    tree_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The failure the success message used to hide: setup that never ran.

    The base is the observable half — `uv sync` is not run in tests — and it
    is exactly the record whose config write fails under a held lock.
    """
    path = interrupted_creation(repo, tree_dir, "topic")
    monkeypatch.chdir(repo)
    assert path.exists()

    create("topic")

    recorded = repo_git(repo)("config", "--get", "branch.topic.lup-base")
    assert str(recorded).strip() == "main"
    assert "setup never finished" in capsys.readouterr().out


def test_a_half_made_worktree_does_not_report_success(
    repo: Path, tree_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unfinishable step exits non-zero rather than claiming the worktree is ready.

    The environment stands in for every step that can fail: `uv sync` is
    stubbed to leave no `.venv`, which is precisely the state that makes
    pyright report errors in code nobody touched.
    """
    interrupted_creation(repo, tree_dir, "topic")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(worktree, "sync_dependencies", lambda _path: None)

    with pytest.raises(typer.Exit) as exit_info:
        create("topic", no_sync=False)

    assert exit_info.value.exit_code == 1


def test_the_steps_that_did_not_run_are_named(
    repo: Path,
    tree_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Naming the missing step is what costs less than the diagnosis it prevents."""
    interrupted_creation(repo, tree_dir, "topic")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(worktree, "sync_dependencies", lambda _path: None)

    with pytest.raises(typer.Exit):
        create("topic", no_sync=False)

    reported = capsys.readouterr().out
    assert "not ready" in reported
    assert "the synced environment (.venv)" in reported


def test_an_environment_that_was_built_is_not_rebuilt(
    repo: Path, tree_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness is read off the worktree, so a finished step is not repeated."""
    (interrupted_creation(repo, tree_dir, "topic") / ".venv").mkdir()
    monkeypatch.chdir(repo)

    def refuse(_worktree_path: Path) -> None:
        raise AssertionError("a synced environment was rebuilt")

    monkeypatch.setattr(worktree, "sync_dependencies", refuse)

    create("topic", no_sync=False)


def test_an_opted_out_step_is_not_owed(
    repo: Path, tree_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-sync` removes the step, so its absence cannot make a worktree unready."""
    interrupted_creation(repo, tree_dir, "topic")
    monkeypatch.chdir(repo)

    create("topic", no_sync=True)

    assert not (tree_dir / "topic" / ".venv").exists()


def test_a_recorded_base_is_left_as_it_was(
    repo: Path, tree_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finishing a worktree completes what is missing and rewrites nothing."""
    interrupted_creation(repo, tree_dir, "topic")
    repo_git(repo)("config", "branch.topic.lup-base", "deliberate")
    monkeypatch.chdir(repo)

    create("topic")

    recorded = repo_git(repo)("config", "--get", "branch.topic.lup-base")
    assert str(recorded).strip() == "deliberate"


def test_the_gitignored_extras_are_finished_too(
    repo: Path, tree_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree missing the source tree's local settings is not ready either."""
    path = interrupted_creation(repo, tree_dir, "topic")
    (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    create("topic", no_copy_data=False)

    assert (path / ".env.local").read_text(encoding="utf-8") == "SECRET=1\n"


@pytest.mark.usefixtures("tree_dir")
def test_a_new_branch_is_given_a_remote_to_track(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upstream is what a later session's pull and push both name.

    Without one the freshness reading has nothing to keep this checkout level
    with, and the branch has no copy anywhere but this disk until somebody
    opens a pull request.
    """
    monkeypatch.chdir(repo)

    create("topic")

    tracked = repo_git(repo)(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "topic@{upstream}"
    )
    assert str(tracked).strip() == "origin/topic"


def test_a_checkout_with_no_remote_is_still_handed_over(
    repo: Path,
    tree_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A worktree that could not be pushed is a worktree to work in.

    Every other step answers for whether the checkout is usable; this one
    answers for whether a remote was told about it, and failing the command
    over that would cost more than the step is worth.
    """
    repo_git(repo)("remote", "remove", "origin")
    monkeypatch.chdir(repo)

    create("topic")

    assert "the remote branch tracking topic" in capsys.readouterr().out
    assert (tree_dir / "topic").is_dir()


def test_commits_no_remote_holds_are_left_for_the_gated_push(
    repo: Path,
    tree_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Creation pushes a tip the remote already has, and nothing else.

    The pre-push guard is armed a step earlier and runs the whole gate on any
    push, so creation only ever pushes where there is nothing to gate. A
    branch that has advanced is `dev pr push`'s to send, with the guard doing
    what it is there for.
    """
    interrupted_creation(repo, tree_dir, "topic")
    commit_file(
        repo_git(tree_dir / "topic"),
        tree_dir / "topic",
        "mine.txt",
        "mine",
        "feat: mine",
    )
    monkeypatch.chdir(repo)

    create("topic")

    assert "Not pushing topic" in capsys.readouterr().out
