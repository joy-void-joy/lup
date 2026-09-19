"""A spawn carries a name, judged end to end through the installed dispatchers.

The Claude half is run as the runtime runs it, over the payload shape the
probe recorded: an `Agent` call whose input holds `description`, `prompt` and
`subagent_type`, and, when given, `name`. The kernel is asked directly for
what a project that requires no name does, since no installed tree declines
it.
"""

import json
from pathlib import Path

import sh

from lup.policy.kernel.spawns import decide_spawn
from lup.types import JsonObject
from lup_template.harness.catalog import portable_harness

DISPATCHER = Path(".claude/plugins/lup/hooks/scripts/policy.py")


def decide(payload: JsonObject) -> JsonObject:
    """Run the generated Claude dispatcher over one hook payload."""
    return json.loads(
        str(sh.Command("python3")("-I", "-S", str(DISPATCHER), _in=json.dumps(payload)))
    )


def spawn(
    name: str | None, prompt: str = "Reply with the single word ok."
) -> JsonObject:
    """One native spawn, in the shape the runtime was measured to deliver."""
    named: JsonObject = {} if name is None else {"name": name}
    return {
        "tool_name": "Agent",
        "tool_input": {
            "description": "Run monitor leak probe",
            "prompt": prompt,
            "subagent_type": "general-purpose",
            **named,
        },
        "cwd": str(Path.cwd()),
    }


def test_a_spawn_without_a_name_is_refused_with_the_shape_of_one() -> None:
    """The refusal says what a name is for and what one looks like."""
    declared = portable_harness().declared_hooks.spawn_names
    assert declared is not None

    decision = decide(spawn(None))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "deny"
    reason = str(specific["permissionDecisionReason"])
    assert declared.reason in reason
    assert declared.recovery in reason


def test_a_blank_name_is_no_name() -> None:
    decision = decide(spawn("   "))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "deny"


def test_a_named_spawn_is_left_to_the_runtime() -> None:
    """Deferred, not allowed: the kernel grants nothing it was not asked to."""
    assert decide(spawn("leak_probe")) == {}


def test_a_hyphen_is_refused_here_rather_than_silently_where_it_lands() -> None:
    """Measured on Codex 0.155.1: a hyphenated name produced no PostToolUse at all.

    The model retried with underscores unprompted, having learned the shape
    by guessing. Refusing it here leaves a record and says what to pass.
    """
    declared = portable_harness().declared_hooks.spawn_names
    assert declared is not None

    decision = decide(spawn("leak-probe"))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "deny"
    reason = str(specific["permissionDecisionReason"])
    assert "leak-probe" in reason
    assert declared.misspelled in reason
    assert declared.recovery in reason


def test_a_name_longer_than_the_limit_is_refused() -> None:
    """The shorter of the two runtimes' limits, counted rather than trusted."""
    declared = portable_harness().declared_hooks.spawn_names
    assert declared is not None

    decision = decide(spawn("a" * (declared.limit + 1)))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "deny"
    assert decide(spawn("a" * declared.limit)) == {}


def test_a_name_may_not_open_with_its_punctuation() -> None:
    """Both runtimes want a letter or a digit first, so the check does too."""
    decision = decide(spawn("_leak_probe"))

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "deny"


def test_a_project_running_one_runtime_may_widen_what_a_name_carries() -> None:
    """The safe set is the declaration's, since it follows from where it runs."""
    declared = portable_harness().declared_hooks.spawn_names
    assert declared is not None
    widened = declared.model_copy(update={"punctuation": "-_"}).erased()

    assert decide_spawn("leak-probe", [], widened).effect == "defer"
    assert decide_spawn("leak.probe", [], widened).effect == "deny"


def test_a_misspelled_name_escalates_the_way_a_missing_one_does() -> None:
    """One refusal shape for both, so a caller who can answer for it is asked."""
    declared = portable_harness().declared_hooks.spawn_names
    assert declared is not None

    escalated = decide_spawn(
        "leak-probe",
        ["# lup: escalate: the name is the runtime's to reject"],
        declared.erased(),
    )

    assert escalated.effect == "ask"
    assert "the name is the runtime's to reject" in escalated.reason


def test_an_escalated_spawn_becomes_the_question_the_caller_asked_for() -> None:
    """The marker rides in the prompt, the one input a caller writes prose into."""
    decision = decide(
        spawn(None, prompt="# lup: escalate: measuring the hook\nReply ok.")
    )

    specific = decision["hookSpecificOutput"]
    assert isinstance(specific, dict)
    assert specific["permissionDecision"] == "ask"
    assert "measuring the hook" in str(specific["permissionDecisionReason"])


def test_a_project_requiring_no_name_leaves_every_spawn_alone() -> None:
    assert decide_spawn("", [], None).effect == "defer"
    assert decide_spawn("leak-probe", [], None).effect == "defer"
