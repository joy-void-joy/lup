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
    assert decide(spawn("leak-probe")) == {}


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
