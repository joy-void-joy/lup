"""What a break owes a project built on this one, and what the gate refuses.

The split these pin is the one the whole design rests on: a capability that
moved is derived from two trees and needs nobody to write it down, while one
that *went* needs a sentence somebody wrote — so the gate fails on the second
and says nothing about the first.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.migrations import (
    DECLARED,
    Migration,
    MigrationStep,
    rendered,
    unapplied,
    undeclared_breaks,
    unnamed,
)
from lup.devtools.dev.preservation import Capability
from lup.devtools.project import DevProject
from lup.execution.shell import git
from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.claude.profile_store import (
    AccountFile,
    ClaudeProfileNames,
    ClaudeProfileRegistrar,
)
from lup.providers.profiles import ProfileDirectory
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


def test_the_profile_split_recipe_preserves_an_existing_registry(
    tmp_path: Path,
) -> None:
    """The documented replacement composes around the caller's existing storage."""
    registry = tmp_path / "profiles.json"
    existing_home = Path("existing-home")
    accounts = AccountFile(registry)
    registry.write_text(
        '{"profiles":{"work":{"config_dir":"existing-home"}},"active":"work"}',
        encoding="utf-8",
    )
    names = ClaudeProfileNames(accounts)
    registrar = ClaudeProfileRegistrar(accounts)
    directory = ProfileDirectory(names, registrar, CLAUDE_LOGIN)

    assert directory.launch_home(None) == existing_home
    assert accounts.resolve_config_dir("work") == existing_home
    personal = registrar.add_profile("personal", tmp_path / "personal-home")
    registrar.set_active("personal")
    assert names.names() == ["personal", "work"]
    assert directory.launch_home(None) == personal
    assert CLAUDE_LOGIN.environment(personal) == {CLAUDE_CONFIG_DIR: str(personal)}
    registrar.remove_profile("work")
    assert AccountFile(registry).resolve_config_dir() == personal


def test_every_standing_declaration_says_what_a_caller_does_about_it() -> None:
    """The property that holds of the window whatever is in it, including nothing.

    Asserting the *contents* of ``DECLARED`` cannot survive a release, because
    emptying that list is what a release does: this named two capabilities by
    their retired import paths and failed the moment they shipped, which made
    the release the one commit the suite could not accept. What is worth
    pinning is true of any window — a break somebody declared carries steps a
    caller can act on, and one scoped to a commit says which.

    Vacuous while the window is empty, and that is the honest reading: there
    are no pending breaks to check between a release and the next declaration.
    """
    for migration in DECLARED:
        assert migration.subjects
        assert migration.steps, f"{migration.subjects} declares no step to take"
        assert migration.reason
        assert all(step.instruction for step in migration.steps)


VENDORING_MANIFEST = """\
[project]
name = "app"
version = "0.1.0"
dependencies = ["lup"]

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
lup = { workspace = true }
"""
"""A project resolving lup from the copy under ``packages/lup``."""

GIT_MANIFEST = """\
[project]
name = "app"
version = "0.1.0"
dependencies = ["lup"]

[tool.uv.sources]
lup = { git = "https://github.com/joy-void-joy/lup", branch = "main", subdirectory = "packages/lup" }
"""
"""The same project after `dev library git`: lup is a dependency, not a tree."""


def vendoring_checkout(root: Path) -> str:
    """A project vendoring lup beside a package of its own, committed.

    Returns the commit, which is the base the gate judges the range from.
    """
    repository(root)
    (root / "pyproject.toml").write_text(VENDORING_MANIFEST, encoding="utf-8")
    library = root / "packages/lup/src/lup"
    library.mkdir(parents=True)
    (library / "client.py").write_text("class Client: ...\n", encoding="utf-8")
    (library / "session.py").write_text(
        "def open_session() -> None: ...\n", encoding="utf-8"
    )
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/core.py").write_text(
        "def run() -> None: ...\n\n\ndef stop() -> None: ...\n", encoding="utf-8"
    )
    committed(root, "vendored")
    return git.out("-C", str(root), "rev-parse", "HEAD")


def test_resolving_the_library_from_a_dependency_takes_nothing_from_anybody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dev library git` removes the vendored copy, and every name still imports.

    What an adopter met right after switching: the base's vendored `lup`
    read against a working tree holding none of it, and the gate failing on
    every name the library declares. The project's own package is judged
    across the same range all the same, so a name it really dropped is the
    one thing reported.
    """
    root = tmp_path / "project"
    base = vendoring_checkout(root)
    monkeypatch.chdir(root)
    (root / "pyproject.toml").write_text(GIT_MANIFEST, encoding="utf-8")
    git("rm", "-r", "--quiet", "packages/lup")
    (root / "src/app/core.py").write_text("def run() -> None: ...\n", encoding="utf-8")

    owed = undeclared_breaks(DevProject(package="app"), base, declared=[])

    assert [capability.identity for capability in owed] == ["stop"]


def test_a_library_this_checkout_vendors_is_held_to_what_it_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where the library's source is the checkout's own, a name it drops is a break.

    lup's own repository is this case, and the one the gate exists for.
    """
    root = tmp_path / "project"
    base = vendoring_checkout(root)
    monkeypatch.chdir(root)
    (root / "packages/lup/src/lup/session.py").write_text("\n", encoding="utf-8")

    owed = undeclared_breaks(DevProject(package="app"), base, declared=[])

    assert [capability.identity for capability in owed] == ["open_session"]
