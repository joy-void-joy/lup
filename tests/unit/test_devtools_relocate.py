"""Behavior tests for `lup-devtools dev relocate`.

The rewrite exists for the ordinary relocation — a flat module moving under a
subpackage — which changes the module path's depth. Pinned here is that a
depth change is applied rather than declined, that everything outside the
spliced span survives byte for byte, and that the two things which look like
module paths but are not — an imported symbol after `from`, and a mention in
prose — are left alone.
"""

from pathlib import Path

from typer.testing import CliRunner

from lup.devtools.dev.relocate import (
    Relocation,
    name_parts,
    relocate,
    surviving_mentions,
)
from lup_template.devtools.main import app


def moved(old: str, new: str) -> Relocation:
    """One relocation, spelled the way the CLI's flag grammar spells it."""
    return Relocation(old=name_parts(old) or [], new=name_parts(new) or [])


DEEPER = [moved("lup.paths", "lup.workspace.paths")]
"""The move the command exists for: two names becoming three."""


def test_relocate_applies_a_move_that_deepens_the_path(tmp_path: Path) -> None:
    """A flat module moving under a subpackage is rewritten, not skipped."""
    source = tmp_path / "site.py"
    source.write_text("from lup.paths import sessions_dir\n", encoding="utf-8")

    edits = relocate([tmp_path], DEEPER)

    assert [edit.imports for edit in edits] == [1]
    assert source.read_text(encoding="utf-8") == (
        "from lup.workspace.paths import sessions_dir\n"
    )


def test_relocate_applies_a_move_that_shortens_the_path(tmp_path: Path) -> None:
    """The reverse move splices just as well: three names becoming two."""
    source = tmp_path / "site.py"
    source.write_text("import lup.workspace.paths as paths\n", encoding="utf-8")

    relocate([tmp_path], [moved("lup.workspace.paths", "lup.paths")])

    assert source.read_text(encoding="utf-8") == "import lup.paths as paths\n"


def test_relocate_leaves_everything_outside_the_span_alone(tmp_path: Path) -> None:
    """Spacing, continuations, comments, and unrelated code survive intact."""
    source = tmp_path / "site.py"
    source.write_text(
        "from lup.paths import (  # the trailing comment\n"
        "    sessions_dir,\n"
        "    traces_path,\n"
        ")\n"
        "from lup.pathsy import untouched\n"
        "\n"
        "VALUE = {'lup.paths': 1}\n",
        encoding="utf-8",
    )

    relocate([tmp_path], DEEPER)

    assert source.read_text(encoding="utf-8") == (
        "from lup.workspace.paths import (  # the trailing comment\n"
        "    sessions_dir,\n"
        "    traces_path,\n"
        ")\n"
        "from lup.pathsy import untouched\n"
        "\n"
        "VALUE = {'lup.paths': 1}\n"
    )


def test_relocate_rewrites_two_imports_sharing_one_line(tmp_path: Path) -> None:
    """Rightmost first, so the second splice does not shift the first."""
    source = tmp_path / "site.py"
    source.write_text("import lup.paths, lup.paths.inner\n", encoding="utf-8")

    relocate([tmp_path], DEEPER)

    assert source.read_text(encoding="utf-8") == (
        "import lup.workspace.paths, lup.workspace.paths.inner\n"
    )


def test_relocate_carries_submodules_of_a_moved_package(tmp_path: Path) -> None:
    """Relocating a package moves what sits beneath it without declaring each."""
    source = tmp_path / "site.py"
    source.write_text("from lup.paths.inner import deep\n", encoding="utf-8")

    relocate([tmp_path], DEEPER)

    assert source.read_text(encoding="utf-8") == (
        "from lup.workspace.paths.inner import deep\n"
    )


def test_relocate_counts_rows_the_way_the_tokenizer_does(tmp_path: Path) -> None:
    """A form feed is whitespace to Python and a line break to `splitlines`.

    Rows read one way and spliced another put every edit below the form feed
    one row early, over whatever line happened to be there.
    """
    source = tmp_path / "site.py"
    source.write_text("\x0c\nfrom lup.paths import sessions_dir\n", encoding="utf-8")

    relocate([tmp_path], DEEPER)

    assert source.read_text(encoding="utf-8") == (
        "\x0c\nfrom lup.workspace.paths import sessions_dir\n"
    )


def test_relocate_follows_the_most_specific_move(tmp_path: Path) -> None:
    """A module declared on its own goes where it was declared to go.

    Its package moving elsewhere in the same run does not take it along: the
    module's own file is carried to the name its move spells, and an import
    following the package's move instead would name a module that is not there.
    """
    source = tmp_path / "site.py"
    source.write_text(
        "from lup.devtools.harness import contained\nimport lup.devtools.dev\n",
        encoding="utf-8",
    )

    relocate(
        [tmp_path],
        [
            moved("lup.devtools", "lup.tools"),
            moved("lup.devtools.harness", "lup.harness"),
        ],
    )

    assert source.read_text(encoding="utf-8") == (
        "from lup.harness import contained\nimport lup.tools.dev\n"
    )


def test_relocate_leaves_an_imported_symbol_alone(tmp_path: Path) -> None:
    """Names after `import` in a `from` statement are symbols, not modules."""
    source = tmp_path / "site.py"
    source.write_text("from lup import paths\n", encoding="utf-8")

    assert relocate([tmp_path], DEEPER) == []
    assert source.read_text(encoding="utf-8") == "from lup import paths\n"


def test_relocate_reports_untouched_files_as_unchanged(tmp_path: Path) -> None:
    """A file naming no mover is not rewritten and not reported."""
    source = tmp_path / "site.py"
    source.write_text("from lup.telemetry.trace import TraceLogger\n", encoding="utf-8")

    assert relocate([tmp_path], DEEPER) == []


def test_surviving_mentions_reports_prose_the_rewrite_cannot_reach(
    tmp_path: Path,
) -> None:
    """A docstring naming the old home is reported for a human to judge."""
    source = tmp_path / "site.py"
    source.write_text('"""Reads through lup.paths."""\n', encoding="utf-8")

    mentions = surviving_mentions([tmp_path], DEEPER)

    assert [mention.split(": ", 1)[1] for mention in mentions] == [
        '"""Reads through lup.paths."""'
    ]


def test_surviving_mentions_name_a_moved_module_imported_from_its_package(
    tmp_path: Path,
) -> None:
    """`from package import submodule` is never rewritten, so it is never silent.

    The dotted path is not written whole there, so the text search that finds
    prose passed over it and the relocation reported nothing left to fix,
    over a site that no longer resolved.
    """
    source = tmp_path / "site.py"
    source.write_text(
        "from lup import (\n    paths,\n    trace,\n)\nfrom lup import pathsy\n",
        encoding="utf-8",
    )

    mentions = surviving_mentions([tmp_path], DEEPER)

    assert [mention.split(": ", 1)[0] for mention in mentions] == [f"{source}:2"]


def test_relocate_refuses_a_destination_another_module_holds(tmp_path: Path) -> None:
    """Nothing moves and nothing is repointed when the new name is taken.

    The command used to carry nothing, since overwriting a module is not a
    relocation, and then repoint every importer at the module standing
    there -- a tree reported as relocated whose imports resolved against the
    wrong file.
    """
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "old_home.py").write_text("value = 1\n", encoding="utf-8")
    (package / "new_home.py").write_text("standing = True\n", encoding="utf-8")
    importer = tmp_path / "site.py"
    importer.write_text("from pkg.old_home import value\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["dev", "relocate", "--root", str(tmp_path), "pkg.old_home=pkg.new_home"],
    )

    assert result.exit_code == 2, result.output
    assert "already exists" in result.output
    assert importer.read_text(encoding="utf-8") == "from pkg.old_home import value\n"
    assert (package / "old_home.py").read_text(encoding="utf-8") == "value = 1\n"
    assert (package / "new_home.py").read_text(encoding="utf-8") == "standing = True\n"
