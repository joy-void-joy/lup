"""Behavior tests for the Python source-reading commands."""

from pathlib import Path

from typer.testing import CliRunner

from lup.devtools.py.app import app
from lup.devtools.py.text import source_text_matches


runner = CliRunner()


def test_source_is_complete_by_default() -> None:
    result = runner.invoke(app, ["source", "lup.devtools.py.app"])
    assert result.exit_code == 0
    assert '@app.command("search")' in result.output


def test_source_text_search_keeps_complete_matching_lines(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "policy.py"
    complete_line = "assignment = " + "literal-value-" * 40
    source.write_text(f"before = 1\n{complete_line}\nafter = 2\n")
    matches = source_text_matches("literal-value", [source_root])

    assert len(matches) == 1
    assert matches[0].line_number == 2
    assert matches[0].text == complete_line


def test_text_command_reports_path_and_line(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("first = 1\nassignment = 'constant'\n")
    result = runner.invoke(app, ["text", "assignment", str(source)])

    assert result.exit_code == 0
    assert f"{source}:2:" in result.output
    assert "assignment = 'constant'" in result.output


def test_text_command_refuses_a_missing_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["text", "assignment", str(tmp_path / "missing")])
    assert result.exit_code == 1
    assert "Python source path does not exist" in result.output


def test_text_command_refuses_a_non_python_file(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("assignment")
    result = runner.invoke(app, ["text", "assignment", str(source)])
    assert result.exit_code == 1
    assert "Source file is not Python" in result.output
