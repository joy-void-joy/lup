"""Behavior tests for create_tool_gate and its four presets.

The gate pattern: deny tool B (or Stop) with an agent-readable message
until condition A holds. Each preset must deny while locked and let the
call through once unlocked.
"""

from typing import cast

import pytest

from claude_agent_sdk.types import (
    HookContext,
    HookEvent,
    HookInput,
    PostToolUseHookInput,
    PreToolUseHookInput,
    PreToolUseHookSpecificOutput,
    StopHookInput,
    SyncHookJSONOutput,
)

from lup.hooks import HooksConfig, create_tool_gate
from lup.realtime import (
    Scheduler,
    create_meta_before_sleep_guard,
    create_pending_event_guard,
    create_stop_guard,
)
from lup.reflect import ReflectionGate, create_reflection_gate


def pre_tool_use(
    tool_name: str, tool_input: dict[str, object] | None = None
) -> PreToolUseHookInput:
    return PreToolUseHookInput(
        hook_event_name="PreToolUse",
        session_id="s",
        transcript_path="",
        cwd="",
        tool_name=tool_name,
        tool_input=tool_input or {},
        tool_use_id="t-1",
    )


def post_tool_use(tool_name: str) -> PostToolUseHookInput:
    return PostToolUseHookInput(
        hook_event_name="PostToolUse",
        session_id="s",
        transcript_path="",
        cwd="",
        tool_name=tool_name,
        tool_input={},
        tool_response=None,
        tool_use_id="t-1",
    )


def stop_input(stop_hook_active: bool) -> StopHookInput:
    return StopHookInput(
        hook_event_name="Stop",
        session_id="s",
        transcript_path="",
        cwd="",
        stop_hook_active=stop_hook_active,
    )


async def run_hook(
    config: HooksConfig, event: HookEvent, input_data: HookInput, index: int = 0
) -> SyncHookJSONOutput:
    """Invoke the hook callback registered for *event* directly."""
    matcher = config[event][index]
    result = await matcher.hooks[0](input_data, None, HookContext(signal=None))
    return cast(SyncHookJSONOutput, result)


def permission_decision(output: SyncHookJSONOutput) -> str | None:
    specific = output.get("hookSpecificOutput")
    if specific is None:
        return None
    return cast(PreToolUseHookSpecificOutput, specific).get("permissionDecision")


def denial_reason(output: SyncHookJSONOutput) -> str:
    specific = output.get("hookSpecificOutput")
    if specific is not None:
        return cast(PreToolUseHookSpecificOutput, specific).get(
            "permissionDecisionReason", ""
        )
    return output.get("reason", "")


async def noop_action(_content: str) -> None:
    return None


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------


async def test_gate_denies_before_unlock_and_passes_after() -> None:
    flag = {"open": False}
    config = create_tool_gate(
        gated_tool="Target",
        message="locked out",
        unlocked=lambda _input: flag["open"],
    )

    denied = await run_hook(config, "PreToolUse", pre_tool_use("Target"))
    assert permission_decision(denied) == "deny"
    assert denial_reason(denied) == "locked out"

    flag["open"] = True
    passed = await run_hook(config, "PreToolUse", pre_tool_use("Target"))
    assert passed == {}


async def test_gate_allow_when_unlocked_returns_explicit_allow() -> None:
    config = create_tool_gate(
        gated_tool="Target",
        message="m",
        unlocked=lambda _input: True,
        allow_when_unlocked=True,
    )
    out = await run_hook(config, "PreToolUse", pre_tool_use("Target"))
    assert permission_decision(out) == "allow"


async def test_gate_block_style_uses_decision_field() -> None:
    config = create_tool_gate(
        gated_tool="Target",
        message="halt",
        unlocked=lambda _input: False,
        style="block",
    )
    out = await run_hook(config, "PreToolUse", pre_tool_use("Target"))
    assert out.get("decision") == "block"
    assert out.get("reason") == "halt"


async def test_gate_dynamic_message_evaluated_at_denial_time() -> None:
    count = {"n": 1}
    config = create_tool_gate(
        gated_tool="T",
        message=lambda: f"{count['n']} pending",
        unlocked=lambda _input: False,
    )
    count["n"] = 7
    out = await run_hook(config, "PreToolUse", pre_tool_use("T"))
    assert denial_reason(out) == "7 pending"


async def test_on_unlock_tool_opens_the_gate() -> None:
    config = create_tool_gate(
        gated_tool="B", message="call A first", on_unlock_tool="A"
    )

    denied = await run_hook(config, "PreToolUse", pre_tool_use("B"))
    assert permission_decision(denied) == "deny"

    await run_hook(config, "PostToolUse", post_tool_use("A"))

    passed = await run_hook(config, "PreToolUse", pre_tool_use("B"))
    assert passed == {}


async def test_gate_matches_each_guarded_tool() -> None:
    config = create_tool_gate(
        gated_tool=["t1", "t2"], message="m", unlocked=lambda _input: False
    )
    assert [m.matcher for m in config["PreToolUse"]] == ["t1", "t2"]


def test_gate_requires_a_condition_and_a_target() -> None:
    with pytest.raises(ValueError):
        create_tool_gate(gated_tool="X", message="m")
    with pytest.raises(ValueError):
        create_tool_gate(message="m", unlocked=lambda _input: True)


async def test_gate_passes_through_mismatched_events() -> None:
    config = create_tool_gate(
        gated_tool="X", message="m", unlocked=lambda _input: False
    )
    out = await run_hook(config, "PreToolUse", stop_input(False))
    assert out == {}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


async def test_reflection_gate_preset() -> None:
    gate = ReflectionGate()
    config = create_reflection_gate(
        gate=gate, gated_tool="StructuredOutput", reflection_tool_name="review"
    )

    denied = await run_hook(config, "PreToolUse", pre_tool_use("StructuredOutput"))
    assert permission_decision(denied) == "deny"
    assert "review" in denial_reason(denied)

    gate.mark_reflected()
    allowed = await run_hook(config, "PreToolUse", pre_tool_use("StructuredOutput"))
    assert permission_decision(allowed) == "allow"

    gate.reset()
    denied_again = await run_hook(
        config, "PreToolUse", pre_tool_use("StructuredOutput")
    )
    assert permission_decision(denied_again) == "deny"


async def test_stop_guard_preset() -> None:
    config = create_stop_guard()

    blocked = await run_hook(config, "Stop", stop_input(False))
    assert blocked.get("decision") == "block"
    assert "sleep" in blocked.get("reason", "")

    passed = await run_hook(config, "Stop", stop_input(True))
    assert passed == {}


async def test_pending_event_guard_preset() -> None:
    unread = {"n": 2}
    scheduler = Scheduler(on_action=noop_action)
    config = create_pending_event_guard(
        check_unread=lambda: unread["n"],
        scheduler=scheduler,
        guarded_tools=["mcp__s__sleep", "mcp__s__schedule_action"],
    )
    assert [m.matcher for m in config["PreToolUse"]] == [
        "mcp__s__sleep",
        "mcp__s__schedule_action",
    ]

    blocked = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert blocked.get("decision") == "block"
    assert "2 unread" in blocked.get("reason", "")

    forced = await run_hook(
        config, "PreToolUse", pre_tool_use("mcp__s__sleep", {"force": True})
    )
    assert forced == {}

    own_debounce = await run_hook(
        config, "PreToolUse", pre_tool_use("mcp__s__sleep", {"debounce_initial": 5})
    )
    assert own_debounce == {}

    scheduler.wake("event")
    wake_pending = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert wake_pending == {}
    scheduler.consume_wake()

    unread["n"] = 0
    nothing_unread = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert nothing_unread == {}


async def test_meta_before_sleep_guard_preset() -> None:
    scheduler = Scheduler(on_action=noop_action)
    config = create_meta_before_sleep_guard(
        scheduler=scheduler, sleep_tool_name="mcp__s__sleep"
    )

    denied = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert permission_decision(denied) == "deny"
    assert "meta" in denial_reason(denied)

    scheduler.meta_gate.mark_reflected()
    allowed = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert permission_decision(allowed) == "allow"

    scheduler.on_agent_action()
    denied_again = await run_hook(config, "PreToolUse", pre_tool_use("mcp__s__sleep"))
    assert permission_decision(denied_again) == "deny"


# ---------------------------------------------------------------------------
# Scheduler sleep result
# ---------------------------------------------------------------------------


async def test_sleep_result_carries_reason_and_time() -> None:
    scheduler = Scheduler(on_action=noop_action)
    result = await scheduler.sleep(0)
    assert result.get("reason") == "timer"
    assert result.get("time")
