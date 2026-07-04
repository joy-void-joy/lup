"""Behavior tests for the marker scanner (`lup.review.markers`).

Pins the load-bearing rule that distinguishes a real note from code: in
Python a `# lup:` counts only inside a comment or docstring, never inside
an ordinary string literal. The scanner's own "no notes" echo strings are the
canonical false positive that line-scanning used to report. The same scan,
parameterized over the marker regex, backs the `TEMPLATE:` customization
todos that `dev todos` gathers for `/lup:init`.
"""

from pathlib import Path

from lup.review.markers import (
    TEMPLATE_MARKER_RE,
    ScanMode,
    find_feedback,
    find_markers,
    scan_mode_for,
)


def texts(source: str, mode: str) -> list[str]:
    return [c.text for c in find_feedback(source, mode)]


def todo_texts(source: str, mode: str) -> list[str]:
    return [c.text for c in find_markers(source, mode, marker=TEMPLATE_MARKER_RE)]


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


def test_python_skips_double_backtick_quoted_syntax_reference() -> None:
    # reStructuredText quotes inline code with double backticks, whose even
    # run length defeats single-backtick parity alone.
    source = '"""Docs that mention the ``# lup:`` marker syntax rst-style."""\n'
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


def test_note_mentioning_the_ignore_hatch_in_prose_is_still_a_note() -> None:
    # The ignore check is anchored to the marker that opens the line, not a
    # substring search — so a note whose prose talks about `# lup: ignore`
    # is feedback, not an ignore directive, and must surface.
    source = "# lup: real note\n# lup: we should remove every # lup: ignore\n"
    assert texts(source, ScanMode.MARKDOWN) == [
        "real note",
        "we should remove every # lup: ignore",
    ]


def test_inline_ignore_directive_is_still_skipped() -> None:
    source = "x = 1  # lup: ignore\ny = 2  # lup: real note\n"
    assert texts(source, ScanMode.PYTHON) == ["real note"]


def test_scan_mode_for_routes_by_suffix() -> None:
    assert scan_mode_for(Path("a.py")) == ScanMode.PYTHON
    assert scan_mode_for(Path("a.pyi")) == ScanMode.PYTHON
    assert scan_mode_for(Path("README.md")) == ScanMode.MARKDOWN
    assert scan_mode_for(Path("notes.txt")) == ScanMode.TEXT


def test_template_comment_marker_is_a_todo() -> None:
    source = "# TEMPLATE: replace these fields for your domain\nx = 1\n"
    assert todo_texts(source, ScanMode.PYTHON) == [
        "replace these fields for your domain"
    ]


def test_template_docstring_marker_needs_no_comment_prefix() -> None:
    source = '"""Setup flow.\n\nTEMPLATE: Replace with your API scopes.\n"""\n'
    assert todo_texts(source, ScanMode.PYTHON) == ["Replace with your API scopes."]


def test_template_marker_inside_ordinary_string_is_code() -> None:
    source = 'MESSAGE = "TEMPLATE: not a decision point"\n'
    assert todo_texts(source, ScanMode.PYTHON) == []


def test_lowercase_template_prose_is_not_a_todo() -> None:
    source = "# the template: a scaffold downstream projects customize\n"
    assert todo_texts(source, ScanMode.PYTHON) == []


def test_template_mention_mid_comment_is_not_a_todo() -> None:
    # A marker opens its comment; prose mentioning the convention mid-way
    # through one is not a decision point.
    source = "# gathered via the TEMPLATE: convention\n"
    assert todo_texts(source, ScanMode.PYTHON) == []


def test_file_level_ignore_is_not_itself_a_note() -> None:
    # A file-level `# lup: ignore` opts the file out of anti-pattern checks;
    # it is an ignore directive, so neither the feedback listing nor the
    # customization todos report the line itself.
    source = "# lup: ignore\n# TEMPLATE: still a decision point\n"
    assert todo_texts(source, ScanMode.PYTHON) == ["still a decision point"]
    assert find_feedback(source, ScanMode.PYTHON) == []


def test_feedback_note_surfaces_despite_file_level_ignore() -> None:
    # The file-level opt-out silences anti-pattern checks, never feedback:
    # a real note in an opted-out file (e.g. lup.review.markers itself) must reach
    # `dev comments`, or review feedback silently disappears.
    source = "# lup: ignore\nx = 1  # lup: real note\n"
    assert texts(source, ScanMode.PYTHON) == ["real note"]


def test_template_continuation_merges_and_stops_at_decoration() -> None:
    source = (
        "# =========================================\n"
        "# TEMPLATE: pick your integrations —\n"
        "# one entry per service\n"
        "# =========================================\n"
        "X = 1\n"
    )
    assert todo_texts(source, ScanMode.PYTHON) == [
        "pick your integrations — one entry per service"
    ]


def test_decoration_line_ends_a_feedback_note_too() -> None:
    source = "# lup: note inside a banner\n# ----\nx = 1\n"
    assert texts(source, ScanMode.PYTHON) == ["note inside a banner"]
