"""SDK-agnostic hook utilities.

Provides composable hook primitives that work with any backend adapter.
Each adapter converts ``LupHooksConfig`` into its native hook format.

Output helpers:
- allow_hook() — PreToolUse allow decision
- deny_hook() — PreToolUse deny decision
- block_hook() — block decision (Stop or PreToolUse)

PreToolUse hooks:
- create_permission_hooks() — directory-based read/write access control
- create_tool_allowlist_hook() — restrict agent to specific tools
- create_reflection_gate() — deny a tool until reflection has occurred

PostToolUse hooks:
- create_nudge_hook() — inject system messages suggesting better alternatives
- create_capture_hook() — extract data from sub-agent tool responses

Composition:
- merge_hooks() to compose multiple hook sources

Examples:
    Compose permission and nudge hooks::

        >>> from lup.hooks import create_permission_hooks, create_nudge_hook
        >>> from lup.types import merge_hooks
        >>> perms = create_permission_hooks(
        ...     rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")]
        ... )
        >>> nudges = create_nudge_hook({"fetch_url": lambda inp: "Use WebFetch"})
        >>> combined = merge_hooks(perms, nudges)

    Restrict an agent to specific tools::

        >>> hooks = create_tool_allowlist_hook(["Read", "Grep", "WebSearch"])

    Capture data from a sub-agent's tool calls::

        >>> hooks, captured = create_capture_hook("WebSearch", extract_urls)
        >>> # After running the agent, `captured` contains extracted items
        >>> len(captured)
        5
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lup.reflect import ReflectionGate

from lup.paths import extract_glob_dir, path_is_under
from lup.types import (
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    allow_hook,
    block_hook,
    deny_hook,
)


type NudgeCheck = Callable[[LupHookInput], str | None]
"""Given a hook input, return a nudge message or None to skip."""


def create_permission_hooks(
    rw_dirs: list[Path],
    ro_dirs: list[Path],
) -> LupHooksConfig:
    """Create permission hooks with directory-based access control.

    Controls Read/Write/Edit/Glob/Grep access based on directory permissions:
    - Write/Edit: Only allowed in rw_dirs
    - Read/Glob/Grep: Allowed in rw_dirs + ro_dirs
    - Other tools: Allowed (filtered by allowed_tools in options)

    Args:
        rw_dirs: Directories where Write/Edit/Read are allowed.
        ro_dirs: Additional directories where only Read is allowed.

    Returns:
        SDK-agnostic hooks configuration.
    """
    all_readable = rw_dirs + ro_dirs

    async def permission_hook(input_data: LupHookInput) -> LupHookOutput:
        if input_data.get("hook_event_name") != "PreToolUse":
            return LupHookOutput()

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        match tool_name:
            case "Write" | "Edit":
                file_path = str(tool_input.get("file_path", ""))
                if not file_path:
                    return LupHookOutput()
                if path_is_under(file_path, rw_dirs):
                    return allow_hook()
                return deny_hook(
                    f"{tool_name} denied. Allowed: {[str(d) for d in rw_dirs]}"
                )

            case "Read":
                file_path = str(tool_input.get("file_path", ""))
                if not file_path:
                    return LupHookOutput()
                if path_is_under(file_path, all_readable):
                    return allow_hook()
                return deny_hook(
                    f"Read denied. Allowed: {[str(d) for d in all_readable]}"
                )

            case "Glob" | "Grep":
                file_path = str(tool_input.get("path", ""))
                if not file_path and tool_name == "Glob":
                    file_path = extract_glob_dir(str(tool_input.get("pattern", "")))
                if not file_path:
                    return deny_hook(
                        f"Path required for {tool_name}. "
                        f"Specify path in: {[str(d) for d in all_readable]}"
                    )
                if path_is_under(file_path, all_readable):
                    return allow_hook()
                return deny_hook(
                    f"{tool_name} denied. Allowed: {[str(d) for d in all_readable]}"
                )

            case _:
                return allow_hook()

    return {
        "PreToolUse": [LupHookMatcher(hook=permission_hook, tag="permission")],
    }


def create_tool_allowlist_hook(
    allowed_tools: list[str],
) -> LupHooksConfig:
    """Create a PreToolUse hook that restricts the agent to only allowed tools."""
    allowed = frozenset(allowed_tools)

    async def allowlist_hook(input_data: LupHookInput) -> LupHookOutput:
        if input_data.get("hook_event_name") != "PreToolUse":
            return LupHookOutput()

        tool_name = input_data.get("tool_name", "")
        if tool_name in allowed:
            return allow_hook()
        return deny_hook(f"Tool '{tool_name}' not in allowed list.")

    return {
        "PreToolUse": [LupHookMatcher(hook=allowlist_hook, tag="allowlist")],
    }


def create_nudge_hook(
    nudges: dict[str, NudgeCheck],
) -> LupHooksConfig:
    """Create a PostToolUse hook that nudges the agent toward better alternatives.

    Instead of hard-blocking a tool via PreToolUse denial, this injects a
    system message after the tool runs, suggesting a better approach. The
    agent remains free to ignore the nudge.

    Args:
        nudges: Mapping of tool_name to a check function. The check receives
            the hook input and returns a nudge message string, or None to skip.

    Returns:
        SDK-agnostic hooks configuration with a PostToolUse nudge hook.
    """

    async def nudge_hook(input_data: LupHookInput) -> LupHookOutput:
        if input_data.get("hook_event_name") != "PostToolUse":
            return LupHookOutput()

        tool_name = input_data.get("tool_name", "")
        check = nudges.get(tool_name)
        if check is None:
            return LupHookOutput()

        message = check(input_data)
        if message is None:
            return LupHookOutput()

        return LupHookOutput(system_message=message)

    return {
        "PostToolUse": [LupHookMatcher(hook=nudge_hook, tag="nudge")],
    }


def create_capture_hook[T](
    tool_name: str,
    extract: Callable[[LupHookInput], list[T]],
) -> tuple[LupHooksConfig, list[T]]:
    """Create a PostToolUse hook that captures data from tool responses.

    Extracts data from a sub-agent's tool responses into a shared list.

    Args:
        tool_name: The tool name to capture from (e.g., "WebSearch").
        extract: Function that examines the hook input and returns items to capture.

    Returns:
        (hooks_config, captured): The hook config and the shared accumulator list.
    """
    captured: list[T] = []

    async def capture_hook(input_data: LupHookInput) -> LupHookOutput:
        if input_data.get("hook_event_name") != "PostToolUse":
            return LupHookOutput()
        if input_data.get("tool_name") != tool_name:
            return LupHookOutput()

        items = extract(input_data)
        captured.extend(items)
        return LupHookOutput()

    return (
        {"PostToolUse": [LupHookMatcher(hook=capture_hook, tag="capture")]},
        captured,
    )


def create_reflection_gate(
    *,
    gate: "ReflectionGate",
    gated_tool: str,
    reflection_tool_name: str = "reflection",
    denial_message: str | None = None,
) -> LupHooksConfig:
    """Create a PreToolUse hook that denies *gated_tool* until reflection.

    The hook checks ``gate.reflected``. If ``False``, denies *gated_tool*
    with a message telling the agent to call *reflection_tool_name* first.

    Args:
        gate: The ReflectionGate instance tracking status.
        gated_tool: Tool name to block (e.g., ``"StructuredOutput"``).
        reflection_tool_name: Name shown in the denial message.
        denial_message: Custom denial text. Uses a sensible default if None.

    Returns:
        SDK-agnostic hooks configuration.
    """
    default_message = (
        f"You must call {reflection_tool_name}() with your assessment "
        f"BEFORE calling {gated_tool}. Reflect on your work first, "
        f"then try again."
    )
    message = denial_message or default_message

    async def reflection_gate_hook(input_data: LupHookInput) -> LupHookOutput:
        _ = input_data
        if gate.reflected:
            return allow_hook()
        return deny_hook(message)

    return {
        "PreToolUse": [
            LupHookMatcher(
                matcher=gated_tool, hook=reflection_gate_hook, tag="reflection_gate"
            )
        ],
    }


def create_completion_guard(
    output_exists: Callable[[], bool],
    *,
    output_tool_name: str = "mcp__notes__submit_output",
    max_blocks: int = 3,
) -> LupHooksConfig:
    """Create a Stop hook that blocks finishing until output is submitted.

    Output submission happens through a tool (see :mod:`lup.output`), so a
    backend's native finalization no longer guarantees a result exists. On
    backends with a stop event, this hook pushes the agent back with a
    corrective message when it tries to finish without submitting.

    After ``max_blocks`` consecutive blocks the stop is allowed through —
    a confused agent must not loop forever. The orchestration layer then
    sees the missing output file and surfaces the failure.

    Args:
        output_exists: Returns True once the final output has been submitted.
        output_tool_name: Tool named in the corrective message.
        max_blocks: Consecutive blocks before giving up.

    Returns:
        SDK-agnostic hooks configuration with a Stop hook.
    """
    blocks = 0

    async def completion_guard_hook(input_data: LupHookInput) -> LupHookOutput:
        nonlocal blocks
        if input_data.get("hook_event_name") != "Stop":
            return LupHookOutput()
        if output_exists():
            return LupHookOutput()
        if blocks >= max_blocks:
            return LupHookOutput()
        blocks += 1
        return block_hook(
            f"No final output has been submitted. Call {output_tool_name} "
            f"with your structured output before finishing. "
            f"(attempt {blocks}/{max_blocks})"
        )

    return {
        "Stop": [LupHookMatcher(hook=completion_guard_hook, tag="completion_guard")],
    }
