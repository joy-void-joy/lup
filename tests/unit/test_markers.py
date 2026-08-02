"""Behavior tests for the marker scanner (`lup.codescan.markers`).

Pins the load-bearing rule that distinguishes a real note from code: in
Python a `# lup:` counts only inside a comment or docstring, never inside
an ordinary string literal. The scanner's own "no notes" echo strings are the
canonical false positive that line-scanning used to report. The same scan,
parameterized over the marker regex, backs the `TEMPLATE:` customization
todos that `dev todos` gathers for `/lup:init`.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lup.codescan.common import IGNORE_RE, file_level_ignore, ignore_rule_ids
from lup.codescan.markers import (
    TEMPLATE_MARKER_RE,
    MarkerComment,
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


def test_typed_ignore_directive_is_not_feedback() -> None:
    # A typed `# lup: ignore[id]` is an escape hatch, not a review note, so it
    # is skipped by the feedback scan just like the bare form.
    source = "x = 1  # lup: ignore[dict-get]\ny = 2  # lup: real note\n"
    assert texts(source, ScanMode.PYTHON) == ["real note"]


def test_ignore_rule_ids_parses_bare_and_typed() -> None:
    bare = IGNORE_RE.search("# lup: ignore")
    assert bare is not None and ignore_rule_ids(bare) is None
    typed = IGNORE_RE.search("x = 1  # lup: ignore[dict-get, tuple-shape]")
    assert typed is not None
    assert ignore_rule_ids(typed) == {"dict-get", "tuple-shape"}


def test_file_level_ignore_reads_bare_typed_and_absent() -> None:
    bare = file_level_ignore("# lup: ignore\nx = 1\n")
    assert bare is not None and bare.rule_ids is None
    typed = file_level_ignore("# lup: ignore[dict-get]\nx = 1\n")
    assert typed is not None and typed.rule_ids == {"dict-get"}
    assert file_level_ignore("x = 1\n") is None


def test_file_level_ignore_carries_a_reason_after_the_ids() -> None:
    for line in (
        "# lup: ignore[dict-get] — the receiver is an HTTP client\n",
        "# lup: ignore[dict-get]: the receiver is an HTTP client\n",
        "# lup: ignore[dict-get] - the receiver is an HTTP client\n",
    ):
        stated = file_level_ignore(line + "x = 1\n")
        assert stated is not None and stated.rule_ids == {"dict-get"}
    bare = file_level_ignore("# lup: ignore — every rule, and here is why\nx = 1\n")
    assert bare is not None and bare.rule_ids is None


def test_file_level_ignore_still_refuses_a_trailing_inline_directive() -> None:
    assert file_level_ignore("x = 1  # lup: ignore[dict-get]\n") is None


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
    # a real note in an opted-out file (e.g. lup.codescan.markers itself) must reach
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


def test_defer_note_parses_kind_condition_and_text() -> None:
    source = "# lup: defer[until v2 ships]: rework the cache layer\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "defer"
    assert note.condition == "until v2 ships"
    assert note.text == "rework the cache layer"


def test_ordinary_note_has_note_kind_and_no_condition() -> None:
    source = "# lup: plain feedback\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "note"
    assert note.condition is None


def test_defer_head_requires_brackets() -> None:
    # Prose that merely starts with "defer" is ordinary feedback; the bracket
    # syntax (mirroring `# lup: ignore[rule-id]`) is the discriminator.
    source = "# lup: defer this until later\n# lup: deferred work is tracked inline\n"
    notes = find_feedback(source, ScanMode.MARKDOWN)
    assert [note.kind for note in notes] == ["note", "note"]


def test_defer_condition_may_contain_bracketed_rule_ids() -> None:
    # The condition syntax mirrors `ignore[rule-id]`, so conditions naming
    # such directives are expected input and must survive the round trip.
    source = "# lup: defer[when ignore[dict-get] sites migrate]: refine the rule\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "defer"
    assert note.condition == "when ignore[dict-get] sites migrate"
    assert note.text == "refine the rule"
    assert note.marker_text() == (
        "defer[when ignore[dict-get] sites migrate]: refine the rule"
    )


def test_defer_head_ends_at_the_first_bracket_colon_delimiter() -> None:
    source = "# lup: defer[until v2]: see ignore[dict-get]: both sites\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "defer"
    assert note.condition == "until v2"
    assert note.text == "see ignore[dict-get]: both sites"


def test_defer_with_empty_condition_stays_an_ordinary_note() -> None:
    source = "# lup: defer[]: no wake condition given\n# lup: defer[ ]: blank\n"
    notes = find_feedback(source, ScanMode.MARKDOWN)
    assert [note.kind for note in notes] == ["note", "note"]


def test_defer_head_without_a_colon_stays_an_ordinary_note() -> None:
    # The documented grammar is `defer[<condition>]: <text>`; a head that
    # never closes with `]:` degrades to an ordinary red note rather than
    # a silently mangled condition.
    source = "# lup: defer[until v2] rework the cache\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "note"
    assert note.condition is None


def test_defer_continuation_lines_merge_into_the_message() -> None:
    source = (
        "# lup: defer[until the sweep lands]: fold both scanners\n"
        "# into one shared pass\n"
        "x = 1\n"
    )
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "defer"
    assert note.condition == "until the sweep lands"
    assert note.text == "fold both scanners into one shared pass"


def test_typed_ignore_is_still_skipped_not_classified_as_defer() -> None:
    source = "x = 1  # lup: ignore[dict-get]\ny = 2  # lup: defer[never]: parked\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    assert note.kind == "defer"
    assert note.start_line == 2


def test_gitignore_style_hash_comment_carries_a_defer_note() -> None:
    assert scan_mode_for(Path(".gitignore")) == ScanMode.TEXT
    source = (
        "notes/*\n"
        "!notes/.gitkeep\n"
        "# lup: defer[until branches merge]: purge notes history\n"
        "worktrees/\n"
    )
    (note,) = find_feedback(source, ScanMode.TEXT)
    assert note.kind == "defer"
    assert note.condition == "until branches merge"
    assert note.text == "purge notes history"
    assert (note.start_line, note.end_line) == (3, 3)


def test_marker_text_reconstitutes_the_defer_head() -> None:
    source = "# lup: defer[until launch]: tighten the budget\n# lup: plain note\n"
    deferred, plain = find_feedback(source, ScanMode.MARKDOWN)
    assert deferred.marker_text() == "defer[until launch]: tighten the budget"
    assert plain.marker_text() == "plain note"


def test_template_todos_are_never_classified_as_deferred() -> None:
    source = "# TEMPLATE: defer[x]: choose your integrations\n"
    (todo,) = find_markers(source, ScanMode.PYTHON, marker=TEMPLATE_MARKER_RE)
    assert todo.kind == "note"
    assert todo.condition is None


def test_defer_classification_survives_model_roundtrip() -> None:
    source = "# lup: defer[until reviewed]: keep this parked\n"
    (note,) = find_feedback(source, ScanMode.PYTHON)
    restored = MarkerComment.model_validate_json(note.model_dump_json())
    assert restored == note


def test_marker_comment_rejects_incoherent_kind_condition_pairs() -> None:
    def build(kind: str, condition: str | None) -> MarkerComment:
        return MarkerComment.model_validate(
            {
                "start_line": 1,
                "end_line": 1,
                "read_start": 1,
                "read_end": 1,
                "text": "body",
                "kind": kind,
                "condition": condition,
            }
        )

    with pytest.raises(ValidationError):
        build("defer", None)
    with pytest.raises(ValidationError):
        build("defer", "")
    with pytest.raises(ValidationError):
        build("note", "until then")
    assert build("defer", "until then").condition == "until then"
