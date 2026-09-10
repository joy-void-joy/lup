"""What a dotted path that did not resolve says next.

A dotted path names a module and a name in one string, and a reader is
usually sure only of the name. Failing on the pair alone charges one
invocation per module guessed at, which is what these pin against: the
refusal stands, and the modules actually defining the name stand beside it.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lup.devtools.py import common
from lup.devtools.py.app import app
from lup.devtools.py.search import name_candidates

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project holding one symbol, in a module nobody would guess."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    package = tmp_path / "shelf"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "words.py").write_text(
        "def rewrites_only_recoverable_files() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_name_is_found_where_it_is_defined(project: Path) -> None:
    """The search answers with the module actually holding the name."""
    found = name_candidates("rewrites_only_recoverable_files", project)
    assert [match["import_path"] for match in found] == [
        "shelf.words.rewrites_only_recoverable_files"
    ]


def test_an_exact_match_drops_its_substring_neighbours(project: Path) -> None:
    """A partial name still answers; an exact one answers alone."""
    (project / "shelf" / "more.py").write_text(
        "def rewrites_only_recoverable_files_twice() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    partial = name_candidates("rewrites_only", project)
    exact = name_candidates("rewrites_only_recoverable_files", project)
    assert len(partial) == 2
    assert [match["import_path"] for match in exact] == [
        "shelf.words.rewrites_only_recoverable_files"
    ]


def test_no_project_leaves_nothing_to_suggest() -> None:
    """A caller outside any project gets the refusal it already had."""
    assert name_candidates("anything", None) == []


def test_source_names_the_module_a_guess_missed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`py source` reports candidates rather than only refusing."""
    monkeypatch.setattr(common, "find_nearest_pyproject", lambda: project)
    result = runner.invoke(
        app, ["source", "shelf.evidence:rewrites_only_recoverable_files"]
    )
    assert result.exit_code == 1
    assert "Could not resolve" in result.output
    assert "shelf.words.rewrites_only_recoverable_files" in result.output


def test_source_still_refuses_a_name_nothing_defines(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to suggest leaves the refusal exactly as it was."""
    monkeypatch.setattr(common, "find_nearest_pyproject", lambda: project)
    result = runner.invoke(app, ["source", "shelf.evidence:not_a_symbol_anywhere"])
    assert result.exit_code == 1
    assert "is defined at" not in result.output


def test_source_of_a_resolvable_object_is_untouched() -> None:
    """The successful path prints the source it always printed."""
    result = runner.invoke(app, ["source", "lup.devtools.py.search:name_candidates"])
    assert result.exit_code == 0
    assert "def name_candidates" in result.output
