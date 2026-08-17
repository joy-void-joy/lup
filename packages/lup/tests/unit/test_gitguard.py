"""The guard that catches a suite writing into the checkout it runs inside."""

from pathlib import Path

import sh

from lup.devtools.dev.git_guards import DECLARED_GUARDS, DRIFT_COMMAND, GitGuard
from lup.gitguard import (
    GIT_ENVIRONMENT,
    guard_report,
    moved_refs,
    repository_refs,
    repository_state,
    watched_config,
)


def test_every_installed_hook_scrubs_the_environment_before_its_check() -> None:
    """A hook is handed this repository in the environment, which outranks `-C`.

    That is the one way in that a suite cannot close from its own side, however
    carefully each helper binds its git, so the hook closes it instead. Before
    the check rather than anywhere inside it: the names have to be gone by the
    time anything the check runs asks git which repository it is in.
    """
    for guard in DECLARED_GUARDS:
        body = guard.body()

        assert guard.environment == GIT_ENVIRONMENT
        assert f"unset {' '.join(guard.environment)}" in body
        assert body.index("unset ") < body.index(f"exec {guard.command}")


def test_a_guard_that_wants_nothing_dropped_writes_no_scrub() -> None:
    """The names are a default, so a project can decline them.

    Declining has to leave a hook that still runs, rather than one carrying a
    bare `unset` and a comment explaining a line that is not there.
    """
    body = GitGuard(environment=()).body()

    assert "unset" not in body
    assert body.endswith(f"exec {DRIFT_COMMAND}\n")


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
