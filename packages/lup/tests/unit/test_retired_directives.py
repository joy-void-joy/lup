"""Taking a retired rule out of the directives that named it."""

from pathlib import Path

from lup.codescan.common import PythonSource
from lup.codescan.project import retired_suppressions


def source(text: str, name: str = "sample") -> PythonSource:
    return PythonSource(path=Path(f"{name}.py"), module=name, text=text)


def test_a_directive_naming_only_the_retired_rule_goes() -> None:
    revised = retired_suppressions(
        source("# lup: ignore[gone] — a reason\ndef run() -> None: ...\n"), "gone"
    )

    assert revised.text == "def run() -> None: ...\n"
    assert revised.removed == [1]


def test_an_inline_directive_goes_and_leaves_its_code() -> None:
    revised = retired_suppressions(
        source("def run() -> None:  # lup: ignore[gone] — a reason\n    ...\n"), "gone"
    )

    assert revised.text == "def run() -> None:\n    ...\n"
    assert revised.removed == [1]


def test_a_multi_line_reason_goes_with_its_directive() -> None:
    """The comment lines under a standalone directive finish its reason."""
    revised = retired_suppressions(
        source(
            "# lup: ignore[gone] — driver: it reads the hook file on disk, and\n"
            "# HookScript is the declaration rather than the thing that reads\n"
            "def run() -> None: ...\n"
        ),
        "gone",
    )

    assert revised.text == "def run() -> None: ...\n"
    assert revised.removed == [1, 2]


def test_prose_above_a_directive_is_not_its_reason_and_stays() -> None:
    revised = retired_suppressions(
        source(
            "# what this function is for\n"
            "# lup: ignore[gone] — a reason\n"
            "def run() -> None: ...\n"
        ),
        "gone",
    )

    assert revised.text == "# what this function is for\ndef run() -> None: ...\n"
    assert revised.removed == [2]


def test_a_compound_directive_keeps_the_rules_it_still_names() -> None:
    revised = retired_suppressions(
        source("# lup: ignore[gone, kept] — a reason\ndef run() -> None: ...\n"), "gone"
    )

    assert revised.text == "# lup: ignore[kept] — a reason\ndef run() -> None: ...\n"
    assert revised.removed == []


def test_a_directive_naming_another_rule_is_untouched() -> None:
    text = "# lup: ignore[kept] — a reason\ndef run() -> None: ...\n"

    assert retired_suppressions(source(text), "gone").text == text


def test_a_bare_directive_is_left_for_the_untyped_audit() -> None:
    text = "# lup: ignore\ndef run() -> None: ...\n"

    assert retired_suppressions(source(text), "gone").text == text


def test_the_id_inside_a_string_is_not_a_directive() -> None:
    text = 'MESSAGE = "# lup: ignore[gone]"\n'

    assert retired_suppressions(source(text), "gone").text == text


def test_two_stacked_directives_keep_the_one_not_retired() -> None:
    """A directive below another ends the block above it, reason and all."""
    revised = retired_suppressions(
        source(
            "# lup: ignore[gone] — first\n"
            "# lup: ignore[kept] — second\n"
            "def run() -> None: ...\n"
        ),
        "gone",
    )

    assert revised.text == "# lup: ignore[kept] — second\ndef run() -> None: ...\n"
    assert revised.removed == [1]
