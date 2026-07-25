"""Behavior tests for the rule that keeps platforms out of portable prose.

The vocabulary is derived from the runtimes rather than written down, so these
tests check the derivation itself as much as the declarations it judges.
"""

from lup.adapters.claude.harness import ClaudeSpellings
from lup.adapters.codex.harness import CodexSpellings
from lup.codescan.portable import native_vocabulary, prose_breaches
from lup.harness.contracts import NativeSpellings
from lup_template.devtools.harness.catalog import portable_harness

RUNTIMES: list[NativeSpellings] = [ClaudeSpellings(), CodexSpellings()]

MARK = "<supplied by the caller>"

REMAINING_PROSE_BREACHES = [
    "harness.guidance",
    "skill.init",
    "skill.install",
    "skill.meta",
]
"""Declarations whose prose still names a platform. This only ever shrinks.

The gate that refuses a breach outright cannot land until this is empty, so
the inventory is the worklist: each conversion removes its own entry, and
nothing new can be added without the removal being noticed."""


def instruction_text(runtime: NativeSpellings) -> str:
    """Everything this runtime says when it frames a caller's own words."""
    return " ".join(
        [
            runtime.ask_user(MARK),
            runtime.delegate("plugin:agent", MARK),
            runtime.request_approval(MARK, MARK),
            runtime.relocate_session(MARK),
            runtime.resolver_entry(),
            runtime.runtime_docs(),
        ]
    )


def test_declared_identifiers_occur_in_what_the_runtime_spells() -> None:
    """A declared identifier that no instruction contains describes nothing."""
    for runtime in RUNTIMES:
        spelled = instruction_text(runtime)
        for identifier in runtime.native_identifiers:
            assert identifier in spelled, (
                f"{runtime.runtime_name} declares {identifier!r} but never spells it"
            )


def test_vocabulary_follows_the_locations_a_runtime_can_spell() -> None:
    """Derivation, not a table: every location reachable is forbidden in prose."""
    vocabulary = native_vocabulary(ClaudeSpellings(), ["lup"])

    assert ".claude/CLAUDE.md" in vocabulary
    assert ".claude/plugins/lup/commands/" in vocabulary
    assert ".claude/.lup-ownership.json" in vocabulary
    assert "Claude Code" in vocabulary
    assert "AskUserQuestion" in vocabulary


def test_portable_prose_names_no_platform_beyond_the_known_inventory() -> None:
    breaches = prose_breaches(portable_harness(), RUNTIMES)
    remaining = sorted(dict.fromkeys(breach.declaration_id for breach in breaches))

    assert remaining == sorted(REMAINING_PROSE_BREACHES), (
        "portable prose inventory changed; converted declarations must leave "
        f"the list. Current: {remaining}"
    )
