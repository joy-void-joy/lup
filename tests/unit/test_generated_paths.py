"""The generated-path map is the compiled trees, not a table beside them.

What makes this page worth generating is the failure it removes: a hand-written
map loses whichever artifacts were added most recently and reads exactly as it
did when it was complete. So these check the walk against the trees this
repository actually compiles, rather than against a fixture that would have to
be kept current by the same hand that let the page rot.
"""

from pathlib import Path

from lup.devtools.harness.generated_paths import (
    GENERATED_PATHS,
    generated_paths_document,
)
from lup_template.devtools.harness.composition import TARGETS


def rendered() -> str:
    """The page as it stands on disk, which generation keeps current."""
    return GENERATED_PATHS.read_text(encoding="utf-8")


def test_every_compiled_artifact_reaches_the_page() -> None:
    """An artifact reaches the map by being compiled, which is the whole point."""
    page = rendered()

    for build in TARGETS.builders.values():
        for artifact in build(Path.cwd()).recipe.desired.artifacts:
            assert f"`{artifact.path.as_posix()}`" in page


def test_every_row_names_the_source_its_artifact_carries() -> None:
    """The page cannot name a source the artifact does not."""
    page = rendered()

    for build in TARGETS.builders.values():
        for artifact in build(Path.cwd()).recipe.desired.artifacts:
            assert artifact.banner is not None
            assert artifact.banner.attribution() in page


def test_the_families_a_hand_written_table_folded_are_each_present() -> None:
    """Every one of these was one row for a whole directory, or missing."""
    page = rendered()

    assert "`.claude/plugins/lup/commands/commit.md`" in page
    assert "lup.devtools.harness.content.skills.commit" in page
    assert "`.codex/plugins/lup/skills/commit/SKILL.md`" in page
    assert "`.claude/plugins/lup/hooks/runtime/kernel/edit.py`" in page
    assert "lup.policy.kernel.edit" in page


def test_the_page_declares_the_module_that_renders_it() -> None:
    """It is generated like every other page, and says so in its own banner."""
    document = generated_paths_document(TARGETS, Path.cwd())

    assert document.declared_source() == "lup.devtools.harness.generated_paths"
    assert rendered().startswith(f"<!-- Generated from {document.declared_source()} ")
