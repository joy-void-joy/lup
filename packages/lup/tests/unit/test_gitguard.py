"""The guard that catches a suite writing into the checkout it runs inside."""

from pathlib import Path

import sh

from lup.devtools.dev.git_guards import (
    DECLARED_GUARDS,
    DRIFT_COMMAND,
    GitGuard,
    hooks_directory,
    install_guards,
    read_hooks,
)
from lup.gitguard import (
    GIT_ENVIRONMENT,
    guard_report,
    moved_refs,
    repository_refs,
    repository_state,
    watched_config,
)
from lup.policy.assets.host import undo_namespace


def test_every_installed_hook_scrubs_the_environment_before_its_check() -> None:
    """A hook is handed this repository in the environment, which outranks `-C`.

    That is the one way in that a suite cannot close from its own side, however
    carefully each helper binds its git, so the hook closes it instead. Before
    the check rather than anywhere inside it: the names have to be gone by the
    time anything the check runs asks git which repository it is in.
    """
    for guard in DECLARED_GUARDS:
        check = guard.check()

        assert guard.environment == GIT_ENVIRONMENT
        assert f"unset {' '.join(guard.environment)}" in check
        assert check.index("unset ") < check.index(f"exec {guard.command}")


def test_a_guard_that_wants_nothing_dropped_writes_no_scrub() -> None:
    """The names are a default, so a project can decline them.

    Declining has to leave a hook that still runs, rather than one carrying a
    bare `unset` and a comment explaining a line that is not there.
    """
    check = GitGuard(environment=()).check()

    assert "unset" not in check
    assert check.endswith(f"exec {DRIFT_COMMAND}\n")


def test_a_hook_at_a_moment_nothing_declares_is_reported_then_cleared(
    tmp_path: Path,
) -> None:
    """The half a declaration cannot report on its own.

    Every other reading here starts from the declaration, so a moment leaving
    it takes its own reporting with it: git goes on running the file while
    the gate that would have said so has stopped looking at that path. A
    checkout armed by an older declaration would keep paying for a guard
    nobody asks for, and read as fully armed while doing it.
    """
    sh.Command("git").bake("-C", str(tmp_path), _tty_out=False)("init", "-b", "main")
    declared = [GitGuard()]
    install_guards(
        [*declared, GitGuard(hook="pre-push", command="echo gate")], tmp_path
    )
    hooks = hooks_directory(tmp_path)
    assert (hooks / "pre-push").is_file()

    reading = read_hooks(declared, tmp_path)
    cleared = install_guards(declared, tmp_path)

    assert [state.path.name for state in reading.orphaned] == ["pre-push"]
    assert [state.status for state in cleared] == ["current", "retired"]
    assert not (hooks / "pre-push").exists()
    assert read_hooks(declared, tmp_path).orphaned == []


def test_a_hook_this_did_not_write_is_left_where_it_is(tmp_path: Path) -> None:
    """Clearing a moment is about this command's own files and nothing else.

    A repository may guard a moment lup never declared, for reasons of its
    own. Reading the marker is what tells the two apart, so the sweep that
    retires a dropped guard cannot reach a hook somebody else installed.
    """
    sh.Command("git").bake("-C", str(tmp_path), _tty_out=False)("init", "-b", "main")
    hooks = hooks_directory(tmp_path)
    hooks.mkdir(parents=True, exist_ok=True)
    theirs = hooks / "pre-push"
    theirs.write_text("#!/bin/sh\nexec ./their-own-check\n", encoding="utf-8")

    install_guards([GitGuard()], tmp_path)

    assert read_hooks([GitGuard()], tmp_path).orphaned == []
    assert theirs.read_text(encoding="utf-8") == "#!/bin/sh\nexec ./their-own-check\n"


def test_a_session_that_touched_nothing_reports_nothing() -> None:
    """The quiet case is every run, so it must never cost a false failure."""
    refs = {"refs/heads/dev": "a" * 40}

    assert moved_refs(refs, refs) == []
    assert guard_report(refs, refs) == ""


def test_every_way_a_ref_can_move_is_named() -> None:
    """Moved, created, and deleted are three different accidents to recover from."""
    before = {"refs/heads/dev": "a" * 40, "refs/heads/gone": "b" * 40}
    after = {"refs/heads/dev": "c" * 40, "refs/heads/new": "d" * 40}

    assert moved_refs(before, after) == [
        "refs/heads/dev: aaaaaaaaaaaa -> cccccccccccc",
        "refs/heads/new: created",
        "refs/heads/gone: deleted",
    ]


def test_the_report_names_the_refs_and_how_to_get_them_back() -> None:
    """A developer reading this has a moved branch and no idea which fixture.

    So the report has to carry both halves: which refs moved, and that the
    reflog is where each one is recovered from.
    """
    report = guard_report({"refs/heads/dev": "a" * 40}, {"refs/heads/dev": "b" * 40})

    assert "refs/heads/dev: aaaaaaaaaaaa -> bbbbbbbbbbbb" in report
    assert "git reflog show <ref>" in report


def test_refs_are_read_from_a_real_repository(tmp_path: Path) -> None:
    """Read through git, so a worktree's refs are found where git keeps them."""
    git = sh.Command("git").bake(
        "-C",
        str(tmp_path),
        "-c",
        "user.email=guard@example.test",
        "-c",
        "user.name=Guard",
        _tty_out=False,
    )
    git("init", "-b", "main")
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-m", "one")

    before = repository_refs(tmp_path)
    git("branch", "sneaky")

    assert "refs/heads/main" in before
    assert moved_refs(before, repository_refs(tmp_path)) == [
        "refs/heads/sneaky: created"
    ]


def test_a_directory_outside_any_repository_yields_no_refs(tmp_path: Path) -> None:
    """A suite run outside a checkout must not fail on the guard's own footing."""
    assert repository_refs(tmp_path / "nowhere") == {}


def guarded_repository(tmp_path: Path) -> sh.Command:
    """A checkout with one commit, bound to a git that commits as somebody."""
    git = sh.Command("git").bake(
        "-C",
        str(tmp_path),
        "-c",
        "user.email=guard@example.test",
        "-c",
        "user.name=Guard",
        _tty_out=False,
    )
    git("init", "-b", "main")
    git("commit", "--allow-empty", "-m", "one")
    return git


def test_a_snapshot_taken_while_the_suite_runs_is_not_the_suites_doing(
    tmp_path: Path,
) -> None:
    """The dispatcher writes one of these in front of every command it allows.

    So an agent running the suite has refs appearing under that namespace
    throughout, from outside the suite and on a schedule it does not control.
    Failing on them made every agent-run check report eight teardown failures,
    one per worker, naming refs no fixture had touched — which is the guard
    crying wolf on exactly the runs somebody was watching it.
    """
    git = guarded_repository(tmp_path)
    before = repository_state(tmp_path)
    git("update-ref", f"{undo_namespace()}/20260822T030458856293-25ed70890b45", "HEAD")

    assert moved_refs(before, repository_state(tmp_path)) == []


def test_a_branch_moving_beside_a_snapshot_is_still_caught(tmp_path: Path) -> None:
    """Narrowing what is watched must not narrow what the narrowing was for."""
    git = guarded_repository(tmp_path)
    before = repository_state(tmp_path)
    git("update-ref", f"{undo_namespace()}/20260822T030502482427-25ed70890b45", "HEAD")
    git("branch", "escaped")

    assert moved_refs(before, repository_state(tmp_path)) == [
        "refs/heads/escaped: created"
    ]


def test_a_suite_watching_its_own_namespace_still_watches_the_real_one(
    tmp_path: Path,
) -> None:
    """`undo_snapshot` takes a namespace, so the guard has to take the same one.

    A suite exercising snapshots points them somewhere of its own; the refs it
    must still be answerable for are the ones the dispatcher would have
    written, which is the namespace it is not using.
    """
    git = guarded_repository(tmp_path)
    before = repository_state(tmp_path, namespace="refs/lup/undo-under-test")
    git("update-ref", f"{undo_namespace()}/20260822T030505499617-25ed70890b45", "HEAD")

    assert moved_refs(
        before, repository_state(tmp_path, "refs/lup/undo-under-test")
    ) == [f"{undo_namespace()}/20260822T030505499617-25ed70890b45: created"]


def test_a_fixture_that_writes_a_committer_identity_is_caught(tmp_path: Path) -> None:
    """The quieter half, and the one that actually bit.

    A fixture setting `user.email` on the enclosing repository is inherited by
    every worktree cut from it, so work committed hours later in another
    session carries that author. Nothing about it is visible at the time.
    """
    git = sh.Command("git").bake("-C", str(tmp_path), _tty_out=False)
    git("init", "-b", "main")
    before = repository_state(tmp_path)
    git("config", "user.email", "fixture@example.test")

    assert watched_config(tmp_path) == {"config user.email": "fixture@example.test"}
    assert moved_refs(before, repository_state(tmp_path)) == [
        "config user.email: created"
    ]


def test_a_fixture_that_writes_a_hooks_path_is_caught(tmp_path: Path) -> None:
    """The half that takes the alarm out with it.

    `core.hooksPath` in the shared config points every worktree cut from the
    repository at a directory a fixture built, so the checkout runs no hooks
    at all — and one whose guards are gone reports exactly what one whose
    guards pass reports. Watched here because nothing else would say so: the
    guards cannot report their own absence.
    """
    git = sh.Command("git").bake("-C", str(tmp_path), _tty_out=False)
    git("init", "-b", "main")
    before = repository_state(tmp_path)
    git("config", "core.hooksPath", str(tmp_path / "hooks"))

    assert moved_refs(before, repository_state(tmp_path)) == [
        "config core.hooksPath: created"
    ]


def test_a_repository_leaving_identity_to_the_global_config_reads_empty(
    tmp_path: Path,
) -> None:
    """Absent is the normal case, so it must not read as a change from nothing."""
    sh.Command("git").bake("-C", str(tmp_path), _tty_out=False)("init", "-b", "main")

    assert watched_config(tmp_path) == {}
