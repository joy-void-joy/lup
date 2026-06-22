"""Behavior tests for the feedback-marker scanner (`lup.markers`).

Pins the load-bearing rule that distinguishes a real note from code: in
Python a `# lup:` counts only inside a comment or docstring, never inside
an ordinary string literal. The scanner's own "no notes" echo strings are the
canonical false positive that line-scanning used to report.
"""

from pathlib import Path

from lup.markers import ScanMode, find_feedback, scan_mode_for


def texts(source: str, mode: str) -> list[str]:
    return [c.text for c in find_feedback(source, mode)]


def test_python_ignores_marker_inside_ordinary_string() -> None:
    source = 'def f() -> None:\n    print("No # lup: comments to commit.")\n'
    assert find_feedback(source, ScanMode.PYTHON) == []


def test_python_reports_real_comment() -> None:
    source = 'x = 1  # lup: real note\nprint("# lup: not a note")\n'
    assert texts(source, ScanMode.PYTHON) == ["real note"]


def test_python_reports_marker_inside_docstring() -> None:
    source = (
        '"""Module summary.\n\nKey idea — explained #lup: clarify this please\n"""\n'
    )
    assert texts(source, ScanMode.PYTHON) == ["clarify this please"]


def test_python_skips_backtick_quoted_syntax_reference() -> None:
    source = '"""Docs that mention the `# lup:` marker syntax inline."""\n'
    assert find_feedback(source, ScanMode.PYTHON) == []


def test_syntax_error_does_not_swallow_a_real_note() -> None:
    source = "def broken(:\n# lup: still surfaced despite syntax error\n"
    assert texts(source, ScanMode.PYTHON) == ["still surfaced despite syntax error"]


def test_text_mode_line_scans_what_python_would_treat_as_a_string() -> None:
    # Text has no lexer, so a line-level marker is taken verbatim — even one
    # that Python mode would dismiss as living inside a string literal.
    source = 'print("# lup: surfaced in text mode")\n'
    assert texts(source, ScanMode.TEXT) == ['surfaced in text mode")']
    assert find_feedback(source, ScanMode.PYTHON) == []


def test_markdown_skips_fenced_code() -> None:
    source = "intro\n\n```\n# lup: inside a fence, not a note\n```\n"
    assert find_feedback(source, ScanMode.MARKDOWN) == []


def test_scan_mode_for_routes_by_suffix() -> None:
    assert scan_mode_for(Path("a.py")) == ScanMode.PYTHON
    assert scan_mode_for(Path("a.pyi")) == ScanMode.PYTHON
    assert scan_mode_for(Path("README.md")) == ScanMode.MARKDOWN
    assert scan_mode_for(Path("notes.txt")) == ScanMode.TEXT
