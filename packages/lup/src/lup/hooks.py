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
- create_tool_gate() — deny a tool (or Stop) until a condition unlocks it

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

    Gate a tool until another tool has run::

        >>> hooks = create_tool_gate(
        ...     gated_tool="StructuredOutput",
        ...     message="Call review() before finalizing output.",
        ...     on_unlock_tool="mcp__notes__review",
        ... )

    Capture data from a sub-agent's tool calls::

        >>> hooks, captured = create_capture_hook("WebSearch", extract_urls)
        >>> # After running the agent, `captured` contains extracted items
        >>> len(captured)
        5
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from lup.paths import extract_glob_dir, path_is_under
from lup.types import (
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    allow_hook,
    block_hook,
    deny_hook,
    merge_hooks,
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


def create_tool_gate(
    *,
    gated_tool: str | Sequence[str] | None = None,
    message: str | Callable[[], str],
    unlocked: Callable[[LupHookInput], bool] | None = None,
    on_unlock_tool: str | None = None,
    event: Literal["PreToolUse", "Stop"] = "PreToolUse",
    style: Literal["deny", "block"] = "deny",
    allow_when_unlocked: bool = False,
    tag: str = "tool_gate",
) -> LupHooksConfig:
    """Create a hook that denies a tool (or Stop) until a condition unlocks it.

    **What:** Registers a hook on *event* that answers with an
    agent-readable denial *message* while the gate is locked, and passes
    through (or explicitly allows) once it is unlocked. The gate is
    unlocked when ``unlocked(input)`` returns True, or — with
    *on_unlock_tool* — once that tool has run (tracked via an internal
    PostToolUse hook).

    **When:** Reach for this whenever the agent must do A before it may
    do B: reflect before finalizing output, read pending events before
    sleeping, call sleep instead of ending the turn. Presets built on
    this primitive: :func:`lup.reflect.create_reflection_gate`,
    :func:`lup.realtime.create_stop_guard`,
    :func:`lup.realtime.create_pending_event_guard`, and
    :func:`lup.realtime.create_meta_before_sleep_guard`.

    **Why:** The denial message is the one channel that reliably
    redirects the agent mid-turn — it states what to do instead, making
    the workflow constraint structural rather than a prompt rule the
    agent can skip.

    Args:
        gated_tool: Tool name(s) to gate. Required for
            ``event="PreToolUse"``; ignored for ``event="Stop"``.
        message: Denial text shown to the agent, or a zero-argument
            callable evaluated at denial time (for dynamic state such as
            unread-event counts).
        unlocked: Predicate over the raw hook input. Return True to let
            the call through. Receiving the input lets gates honor
            per-call escape hatches (a ``force`` flag in ``tool_input``)
            or event fields (``stop_hook_active``).
        on_unlock_tool: Tool name whose use unlocks the gate. Adds a
            PostToolUse hook that records the call; combined with
            *unlocked* via OR. The internal flag never resets — for
            per-cycle gates, track the state yourself and pass *unlocked*.
        event: Hook event to gate: ``"PreToolUse"`` (default) or ``"Stop"``.
        style: Locked response shape. ``"deny"`` uses the PreToolUse
            permission decision; ``"block"`` uses the cross-event
            block decision (required for Stop).
        allow_when_unlocked: When True, return an explicit allow decision
            once unlocked instead of passing through to later hooks
            (PreToolUse only).
        tag: Matcher tag for adapter dispatch. Subprocess backends
            (Codex) cannot run the in-process ``unlocked`` closure; they
            regenerate known gates as external hook scripts by tag, so
            presets with a file-representable condition pass their own
            (e.g. ``"reflection_gate"``).

    Returns:
        SDK-agnostic hooks configuration; combine via ``merge_hooks``.
    """
    if unlocked is None and on_unlock_tool is None:
        raise ValueError("create_tool_gate requires unlocked and/or on_unlock_tool")
    if event == "PreToolUse" and gated_tool is None:
        raise ValueError("create_tool_gate requires gated_tool for PreToolUse gates")

    unlock_seen = False

    async def gate_hook(input_data: LupHookInput) -> LupHookOutput:
        if input_data.get("hook_event_name") != event:
            return LupHookOutput()
        if unlock_seen or (unlocked is not None and unlocked(input_data)):
            if allow_when_unlocked and event == "PreToolUse":
                return allow_hook()
            return LupHookOutput()
        text = message() if callable(message) else message
        match style:
            case "deny":
                return deny_hook(text)
            case "block":
                return block_hook(text)

    async def unlock_hook(input_data: LupHookInput) -> LupHookOutput:
        nonlocal unlock_seen
        if input_data.get("hook_event_name") == "PostToolUse":
            unlock_seen = True
        return LupHookOutput()

    gate_matchers: list[LupHookMatcher]
    match event:
        case "Stop":
            gate_matchers = [LupHookMatcher(hook=gate_hook, tag=tag)]
        case "PreToolUse":
            names = (
                [gated_tool] if isinstance(gated_tool, str) else list(gated_tool or [])
            )
            gate_matchers = [
                LupHookMatcher(matcher=name, hook=gate_hook, tag=tag)
                for name in names
            ]

    hooks: LupHooksConfig = {event: gate_matchers}
    if on_unlock_tool is not None:
        unlock_config: LupHooksConfig = {
            "PostToolUse": [
                LupHookMatcher(
                    matcher=on_unlock_tool, hook=unlock_hook, tag=f"{tag}_unlock"
                )
            ]
        }
        hooks = merge_hooks(hooks, unlock_config)
    return hooks


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
