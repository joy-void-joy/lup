"""Answering the directives a retired rule leaves behind.

Retiring a rule strands every `# lup: ignore` that named it: the directive now
guards nothing, and a stale typed directive is blocking, so the ids have to go
wherever they were written. What has to be pinned is that the rewrite takes the
directive and nothing else — a reason wrapping past one line goes with it, a
directive naming other rules keeps them, and the comment a directive happens to
sit under is not part of it.
"""

from lup.devtools.dev.antipatterns import retired_directives

RULE = "model-free-function"


def test_a_sole_id_directive_and_its_wrapped_reason_are_removed() -> None:
    text = (
        f"# lup: ignore[{RULE}] — driver: it prints to the terminal, which is\n"
        "# the command's surface and not something a verdict does to itself\n"
        "def report(verdict: Verdict) -> None:\n"
        "    return None\n"
    )
    assert retired_directives(text, RULE) == (
        "def report(verdict: Verdict) -> None:\n    return None\n"
    )


def test_an_unrelated_comment_above_the_directive_is_kept() -> None:
    text = (
        "# Compiler, prompt renderers, and reconciler in one place.\n"
        f"# lup: ignore[{RULE}] — composition root building a recipe\n"
        "def recipe(root: Path) -> Recipe:\n"
        "    return Recipe()\n"
    )
    assert retired_directives(text, RULE) == (
        "# Compiler, prompt renderers, and reconciler in one place.\n"
        "def recipe(root: Path) -> Recipe:\n"
        "    return Recipe()\n"
    )


def test_a_directive_naming_other_rules_keeps_them() -> None:
    text = (
        f"# lup: ignore[dict-get, {RULE}, set-shape] — reason\ndef act() -> None: ...\n"
    )
    assert retired_directives(text, RULE) == (
        "# lup: ignore[dict-get, set-shape] — reason\ndef act() -> None: ...\n"
    )


def test_an_inline_directive_is_trimmed_off_its_code() -> None:
    text = f"def act(part: Part) -> None:  # lup: ignore[{RULE}] — reason\n    return None\n"
    assert retired_directives(text, RULE) == (
        "def act(part: Part) -> None:\n    return None\n"
    )


def test_a_directive_for_another_rule_is_untouched() -> None:
    text = "# lup: ignore[dict-get] — reason\ndef act() -> None: ...\n"
    assert retired_directives(text, RULE) == text


def test_a_bare_directive_is_untouched() -> None:
    """It silences every rule, so retiring one leaves it saying what it said."""
    text = "# lup: ignore — reason\ndef act() -> None: ...\n"
    assert retired_directives(text, RULE) == text


def test_the_rule_id_inside_a_string_is_not_a_directive() -> None:
    text = f'MESSAGE = "# lup: ignore[{RULE}]"\n'
    assert retired_directives(text, RULE) == text


def test_unparseable_source_is_returned_untouched() -> None:
    text = f"def broken(  # lup: ignore[{RULE}] — reason\n"
    assert retired_directives(text, RULE) == text
