"""Telling a sibling worktree's commit apart from a fixture escaping.

Every worktree cut from a repository shares its ref store, so the guard
reading `for-each-ref` in one of them sees every branch the repository holds.
Somebody committing in a sibling while the suite runs moved a ref for real,
and blaming this run for it turns a routine event into a failure that reads
exactly like the accident the guard exists for — which is how a real one comes
to be waved through.
"""

import os
from pathlib import Path

import sh

from lup.gitguard import (
    TEST_IDENTITY,
    ForeignCheckouts,
    repository_state,
)


def committed(where: Path, message: str) -> None:
    """One empty commit in ``where``, as the suite's own identity."""
    sh.Command("git")(
        "-C",
        str(where),
        "commit",
        "--allow-empty",
        "-m",
        message,
        _tty_out=False,
        _env={**os.environ, **TEST_IDENTITY.environment()},
    )


def repository_with_a_sibling(tmp_path: Path) -> Path:
    """A checkout with one worktree beside it, each on its own branch."""
    main = tmp_path / "main"
    main.mkdir()
    git = sh.Command("git").bake("-C", str(main), _tty_out=False)
    git("init", "-b", "trunk")
    committed(main, "root")
    git("worktree", "add", "-b", "sibling", str(tmp_path / "sibling"))
    return main


def test_a_sibling_branch_is_attributed_to_the_worktree_holding_it(
    tmp_path: Path,
) -> None:
    foreign = ForeignCheckouts.beside(repository_with_a_sibling(tmp_path))

    assert foreign.holder("refs/heads/sibling") == str((tmp_path / "sibling").resolve())
    assert foreign.holder("refs/heads/trunk") is None


def test_a_commit_in_a_sibling_is_noticed_without_failing(tmp_path: Path) -> None:
    """The case that made this necessary: concurrent work, not an escape."""
    main = repository_with_a_sibling(tmp_path)
    foreign = ForeignCheckouts.beside(main)
    before = repository_state(main)
    committed(tmp_path / "sibling", "their work")

    verdict = foreign.verdict(before, repository_state(main))

    assert verdict.failure == ""
    assert "refs/heads/sibling" in verdict.notice
    assert "not this run" in verdict.notice


def test_the_branch_this_checkout_holds_still_fails(tmp_path: Path) -> None:
    """Narrowing who is answerable must not narrow what is caught."""
    main = repository_with_a_sibling(tmp_path)
    foreign = ForeignCheckouts.beside(main)
    before = repository_state(main)
    committed(main, "an escaped fixture")

    verdict = foreign.verdict(before, repository_state(main))

    assert "refs/heads/trunk" in verdict.failure
    assert "modified the repository it is running inside" in verdict.failure


def test_a_ref_that_appeared_from_nowhere_is_nobody_elses(tmp_path: Path) -> None:
    """No worktree holds a branch a fixture just created, so it is this run's."""
    main = repository_with_a_sibling(tmp_path)
    foreign = ForeignCheckouts.beside(main)
    before = repository_state(main)
    sh.Command("git")("-C", str(main), "branch", "invented", _tty_out=False)

    verdict = foreign.verdict(before, repository_state(main))

    assert "refs/heads/invented: created" in verdict.failure


def test_config_is_never_another_worktrees_to_have_written(tmp_path: Path) -> None:
    """The quieter half is shared outright, so no worktree can be blamed for it."""
    main = repository_with_a_sibling(tmp_path)
    foreign = ForeignCheckouts.beside(main)
    before = repository_state(main)
    sh.Command("git")(
        "-C", str(main), "config", "user.email", "fixture@example.test", _tty_out=False
    )

    verdict = foreign.verdict(before, repository_state(main))

    assert "config user.email: created" in verdict.failure


def test_a_repository_git_cannot_read_blames_the_suite_for_everything(
    tmp_path: Path,
) -> None:
    """The narrower question failing must not answer the wider one yes."""
    assert ForeignCheckouts.beside(tmp_path / "nowhere").holders == {}


def test_a_detached_or_bare_entry_claims_no_ref() -> None:
    """Only a `branch` line names a ref; the others hold none to attribute."""
    listing = (
        "worktree /a\nHEAD abc\ndetached\n\n"
        "worktree /b\nHEAD def\nbranch refs/heads/held\n\n"
        "worktree /c\nbare\n"
    )

    assert ForeignCheckouts.declared(listing, Path("/other")) == {
        "refs/heads/held": str(Path("/b").resolve())
    }


def test_the_checkout_under_test_never_counts_as_foreign() -> None:
    """Its own branch is exactly the one the guard must keep answering for."""
    listing = "worktree /a\nHEAD abc\nbranch refs/heads/mine\n"

    assert ForeignCheckouts.declared(listing, Path("/a").resolve()) == {}
