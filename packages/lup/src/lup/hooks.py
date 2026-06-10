"""Hook utilities for the Claude Agent SDK.

Provides composable hook primitives:

Output helpers:
- allow_hook_output() — PreToolUse allow decision
- deny_hook_output() — PreToolUse deny decision
- block_hook_output() — block decision (Stop or PreToolUse)

PreToolUse hooks:
- create_permission_hooks() — directory-based read/write access control
- create_tool_allowlist_hook() — restrict agent to specific tools
- create_tool_gate() — deny a tool (or Stop) until a condition unlocks it

PostToolUse hooks:
- create_nudge_hook() — inject system messages suggesting better alternatives
- create_capture_hook() — extract data from sub-agent tool responses

Composition:
- HooksConfig type alias for type-safe hook configuration
- merge_hooks() to compose multiple hook sources

Examples:
    Compose permission and nudge hooks::

        >>> from lup.hooks import merge_hooks, create_permission_hooks, create_nudge_hook
        >>> permission_hooks = create_permission_hooks(rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")])
        >>> nudge_hooks = create_nudge_hook({"fetch_url": my_nudge_check})
        >>> combined = merge_hooks(permission_hooks, nudge_hooks)

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
from typing import Literal, cast

from claude_agent_sdk import HookInput, HookMatcher, PostToolUseHookInput
from claude_agent_sdk.types import HookContext, HookEvent, SyncHookJSONOutput

from lup.paths import extract_glob_dir, path_is_under


type HooksConfig = dict[HookEvent, list[HookMatcher]]
"""Typed hook configuration for ClaudeAgentOptions.

Each key is a hook event type, and the value is a list of HookMatcher
instances that will be invoked for that event.
"""


def merge_hooks(base: HooksConfig, additional: HooksConfig) -> HooksConfig:
    """Merge two hook configurations.

    For each hook event type, combines the matchers from both configs.
    Base hooks run first, then additional hooks.

    Args:
        base: The base hook configuration.
        additional: Hook configuration to merge into base.

    Returns:
        New HooksConfig with combined matchers.
    """
    merged: HooksConfig = dict(base)

    for event in additional:
        if event in merged:
            merged[event] = merged[event] + additional[event]
        else:
            merged[event] = additional[event]

    return merged


def allow_hook_output() -> SyncHookJSONOutput:
    """Create an allow decision for PreToolUse hooks."""
    return SyncHookJSONOutput(
        hookSpecificOutput={
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    )


def deny_hook_output(reason: str) -> SyncHookJSONOutput:
    """Create a deny decision for PreToolUse hooks."""
    return SyncHookJSONOutput(
        hookSpecificOutput={
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    )


def block_hook_output(reason: str) -> SyncHookJSONOutput:
    """Create a block decision for Stop or PreToolUse hooks.

    Unlike deny (which is PreToolUse-specific via hookSpecificOutput),
    block uses the top-level ``decision`` field and works across hook types.
    """
    return SyncHookJSONOutput(decision="block", reason=reason)


def create_tool_gate(
    *,
    gated_tool: str | Sequence[str] | None = None,
    message: str | Callable[[], str],
    unlocked: Callable[[HookInput], bool] | None = None,
    on_unlock_tool: str | None = None,
    event: Literal["PreToolUse", "Stop"] = "PreToolUse",
    style: Literal["deny", "block"] = "deny",
    allow_when_unlocked: bool = False,
) -> HooksConfig:
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
            ``decision: block`` field (required for Stop).
        allow_when_unlocked: When True, return an explicit allow decision
            once unlocked instead of passing through to later hooks
            (PreToolUse only).

    Returns:
        HooksConfig to combine with other hooks via :func:`merge_hooks`.
    """
    if unlocked is None and on_unlock_tool is None:
        raise ValueError("create_tool_gate requires unlocked and/or on_unlock_tool")
    if event == "PreToolUse" and gated_tool is None:
        raise ValueError("create_tool_gate requires gated_tool for PreToolUse gates")

    unlock_seen = False

    async def gate_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        if input_data["hook_event_name"] != event:
            return SyncHookJSONOutput()
        if unlock_seen or (unlocked is not None and unlocked(input_data)):
            if allow_when_unlocked and event == "PreToolUse":
                return allow_hook_output()
            return SyncHookJSONOutput()
        text = message() if callable(message) else message
        match style:
            case "deny":
                return deny_hook_output(text)
            case "block":
                return block_hook_output(text)

    async def unlock_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        nonlocal unlock_seen
        if input_data["hook_event_name"] == "PostToolUse":
            unlock_seen = True
        return SyncHookJSONOutput()

    match event:
        case "Stop":
            gate_matchers = [HookMatcher(hooks=[gate_hook])]
        case "PreToolUse":
            names = (
                [gated_tool] if isinstance(gated_tool, str) else list(gated_tool or [])
            )
            gate_matchers = [
                HookMatcher(matcher=name, hooks=[gate_hook]) for name in names
            ]

    hooks = cast(HooksConfig, {event: gate_matchers})
    if on_unlock_tool is not None:
        unlock_config = cast(
            HooksConfig,
            {"PostToolUse": [HookMatcher(matcher=on_unlock_tool, hooks=[unlock_hook])]},
        )
        hooks = merge_hooks(hooks, unlock_config)
    return hooks


def create_permission_hooks(
    rw_dirs: list[Path],
    ro_dirs: list[Path],
) -> HooksConfig:
    """Create permission hooks with directory-based access control.

    Controls Read/Write/Edit/Glob/Grep access based on directory permissions:
    - Write/Edit: Only allowed in rw_dirs
    - Read/Glob/Grep: Allowed in rw_dirs + ro_dirs
    - Other tools: Allowed (filtered by allowed_tools in options)

    Args:
        rw_dirs: Directories where Write/Edit/Read are allowed.
        ro_dirs: Additional directories where only Read is allowed.

    Returns:
        Hooks configuration dict for ClaudeAgentOptions.
    """
    all_readable = rw_dirs + ro_dirs

    async def permission_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        """Control tool access based on directory permissions."""
        if input_data["hook_event_name"] != "PreToolUse":
            return SyncHookJSONOutput()

        tool_name = input_data["tool_name"]
        tool_input = input_data["tool_input"]

        match tool_name:
            case "Write" | "Edit":
                file_path = tool_input.get("file_path", "")
                if not file_path:
                    return SyncHookJSONOutput()
                if path_is_under(file_path, rw_dirs):
                    return allow_hook_output()
                return deny_hook_output(
                    f"{tool_name} denied. Allowed: {[str(d) for d in rw_dirs]}"
                )

            case "Read":
                file_path = tool_input.get("file_path", "")
                if not file_path:
                    return SyncHookJSONOutput()
                if path_is_under(file_path, all_readable):
                    return allow_hook_output()
                return deny_hook_output(
                    f"Read denied. Allowed: {[str(d) for d in all_readable]}"
                )

            case "Glob" | "Grep":
                file_path = tool_input.get("path", "")
                if not file_path and tool_name == "Glob":
                    file_path = extract_glob_dir(tool_input.get("pattern", ""))
                if not file_path:
                    return deny_hook_output(
                        f"Path required for {tool_name}. "
                        f"Specify path in: {[str(d) for d in all_readable]}"
                    )
                if path_is_under(file_path, all_readable):
                    return allow_hook_output()
                return deny_hook_output(
                    f"{tool_name} denied. Allowed: {[str(d) for d in all_readable]}"
                )

            case _:
                return allow_hook_output()

    return cast(
        HooksConfig,
        {
            "PreToolUse": [HookMatcher(hooks=[permission_hook])],
        },
    )


def create_tool_allowlist_hook(
    allowed_tools: list[str],
) -> HooksConfig:
    """Create a PreToolUse hook that restricts the agent to an allowed tool set.

    **What:** Denies every tool call whose name is not in *allowed_tools*,
    answering with the full list of tools that ARE available so the agent
    can re-plan instead of retrying blindly. Allowed tools get an explicit
    allow decision.

    **When:** Use whenever ``permission_mode="bypassPermissions"`` is set —
    the SDK's ``allowed_tools`` option is ignored in that mode, so a
    PreToolUse hook is the only enforcement point.

    **Why:** Makes tool availability a structural guarantee instead of a
    prompt rule: excluded tools cannot run, and the denial message turns a
    dead end into a redirect.
    """
    allowed = frozenset(allowed_tools)
    available = ", ".join(sorted(allowed))

    async def allowlist_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return SyncHookJSONOutput()

        tool_name = input_data["tool_name"]
        if tool_name in allowed:
            return allow_hook_output()
        return deny_hook_output(
            f"Tool '{tool_name}' is not available in this session. "
            f"Available tools: {available}"
        )

    return cast(
        HooksConfig,
        {
            "PreToolUse": [HookMatcher(hooks=[allowlist_hook])],
        },
    )


type NudgeCheck = Callable[[PostToolUseHookInput], str | None]
"""Given a PostToolUse hook input, return a nudge message or None to skip."""


def create_nudge_hook(
    nudges: dict[str, NudgeCheck],
) -> HooksConfig:
    """Create a PostToolUse hook that nudges the agent toward better alternatives.

    Instead of hard-blocking a tool via PreToolUse denial, this injects a
    system message after the tool runs, suggesting a better approach. The
    agent remains free to ignore the nudge.

    Use this when an alternative tool or API exists but hard-blocking would
    be too restrictive (the original tool still works, just suboptimally).

    Args:
        nudges: Mapping of tool_name to a check function. The check receives
            the full PostToolUseHookInput and returns a nudge message string,
            or None to skip the nudge for this invocation.

    Returns:
        Hooks configuration with a PostToolUse nudge hook.
    """

    async def nudge_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        if input_data["hook_event_name"] != "PostToolUse":
            return SyncHookJSONOutput()

        tool_name = input_data["tool_name"]
        check = nudges.get(tool_name)
        if check is None:
            return SyncHookJSONOutput()

        message = check(cast(PostToolUseHookInput, input_data))
        if message is None:
            return SyncHookJSONOutput()

        return SyncHookJSONOutput(systemMessage=message)

    return cast(
        HooksConfig,
        {"PostToolUse": [HookMatcher(hooks=[nudge_hook])]},
    )


def create_capture_hook[T](
    tool_name: str,
    extract: Callable[[PostToolUseHookInput], list[T]],
) -> tuple[HooksConfig, list[T]]:
    """Create a PostToolUse hook that captures data from tool responses.

    Extracts data from a sub-agent's tool responses into a shared list,
    enabling side-channel data capture without requiring structured output
    parsing. This is useful when running a sub-agent (e.g., a search agent)
    and you want to collect data from its tool calls without requiring it
    to produce a specific output format.

    Args:
        tool_name: The tool name to capture from (e.g., "WebSearch").
        extract: Function that examines the PostToolUseHookInput and returns
            items to capture. Called only when tool_name matches.

    Returns:
        (hooks_config, captured): The hook config to pass to merge_hooks,
        and the shared list that accumulates items as the agent runs.
    """
    captured: list[T] = []

    async def capture_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        if input_data["hook_event_name"] != "PostToolUse":
            return SyncHookJSONOutput()
        if input_data["tool_name"] != tool_name:
            return SyncHookJSONOutput()

        items = extract(cast(PostToolUseHookInput, input_data))
        captured.extend(items)
        return SyncHookJSONOutput()

    return (
        cast(HooksConfig, {"PostToolUse": [HookMatcher(hooks=[capture_hook])]}),
        captured,
    )
