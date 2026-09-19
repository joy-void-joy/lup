"""What a break owes a project built on this one, and what the gate refuses.

The split these pin is the one the whole design rests on: a capability that
moved is derived from two trees and needs nobody to write it down, while one
that *went* needs a sentence somebody wrote — so the gate fails on the second
and says nothing about the first.
"""

from pathlib import Path

from lup.devtools.dev.migrations import (
    Migration,
    MigrationStep,
    rendered,
    unapplied,
    unnamed,
)
from lup.devtools.dev.preservation import Capability
from lup.execution.shell import git
from tests.unit.test_ledger_placement import committed, repository

GONE = Capability(identity="create_ledger_tools", location="lup.ledger.tools")

TAKEN = Migration(
    subjects=["create_ledger_tools"],
    reason="the verbs bind to a project's own kinds rather than to lup's",
    steps=[
        MigrationStep(
            instruction="Pass the kinds this project records, from its own declaration."
        )
    ],
)


def test_a_capability_no_migration_names_is_what_fails() -> None:
    """The gate's whole question, and the only thing it asks."""
    assert unnamed([GONE], []) == [GONE]
    assert unnamed([GONE], [TAKEN]) == []


def test_a_migration_speaks_for_every_name_one_decision_took() -> None:
    """One break takes several names, and reads as one record."""
    retired = Migration(
        subjects=["LibraryMode.LINKED", "link_library"],
        reason="the library moved with no command and nothing recorded",
        steps=[MigrationStep(instruction="Pin the branch carrying the change.")],
    )

    assert not unnamed(
        [
            Capability(identity="LibraryMode.LINKED", location="lup.x"),
            Capability(identity="link_library", location="lup.x"),
        ],
        [retired],
    )


def test_a_declaration_naming_no_commit_is_pending_everywhere(tmp_path: Path) -> None:
    """A commit being written cannot name itself, and its break is still owed."""
    root = repository(tmp_path / "upstream")
    (root / "one.py").write_text("x = 1\n", encoding="utf-8")
    committed(root, "one")
    standing = git.out("-C", str(root), "rev-parse", "HEAD")

    assert unapplied([TAKEN], standing, root) == [TAKEN]


def test_a_project_past_the_break_is_told_nothing(tmp_path: Path) -> None:
    """Ancestry decides it, so a branch that never carried the commit still owes it."""
    root = repository(tmp_path / "upstream")
    (root / "one.py").write_text("x = 1\n", encoding="utf-8")
    committed(root, "one")
    broke = git.out("-C", str(root), "rev-parse", "HEAD")
    (root / "two.py").write_text("y = 2\n", encoding="utf-8")
    committed(root, "two")
    after = git.out("-C", str(root), "rev-parse", "HEAD")
    landed = TAKEN.model_copy(update={"commit": broke})

    assert unapplied([landed], after, root) == []
    assert unapplied([landed], broke, root) == []
    assert landed.applied_at(after, root)


def test_what_a_release_carries_is_the_prose_and_the_steps() -> None:
    """The derived half is left out: a map re-derives, a sentence does not."""
    lines = rendered([TAKEN])

    assert lines[0].startswith("create_ledger_tools — the verbs bind")
    assert "Pass the kinds this project records" in lines[1]


def test_a_step_carries_the_command_that_does_it_where_one_does() -> None:
    step = MigrationStep(
        instruction="Pin the branch carrying the change.",
        command=["uv", "run", "lup-devtools", "dev", "library", "git"],
    )

    assert step.spelled().endswith("uv run lup-devtools dev library git")
