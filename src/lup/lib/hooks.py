"""Hook utilities for the Claude Agent SDK.

Provides composable hook primitives:
- HooksConfig type alias for type-safe hook configuration
- merge_hooks() to compose multiple hook sources
- create_permission_hooks() for directory-based access control
- create_tool_allowlist_hook() for tool restriction

Usage:
    from lup.lib import merge_hooks, create_permission_hooks, HooksConfig

    permission_hooks = create_permission_hooks(rw_dirs, ro_dirs)
    custom_hooks = create_my_custom_hooks()
    combined = merge_hooks(permission_hooks, custom_hooks)

    options = ClaudeAgentOptions(hooks=combined, ...)
"""

from pathlib import Path
from typing import Literal, cast

from claude_agent_sdk import HookInput, HookMatcher
from claude_agent_sdk.types import HookContext, SyncHookJSONOutput

from lup.lib.notes import path_is_under


# Hook event types supported by the Claude Agent SDK
HookEventType = Literal[
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
    "PreCompact",
]


type HooksConfig = dict[HookEventType, list[HookMatcher]]
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
    """Create a PreToolUse hook that restricts the agent to only allowed tools.

    Use this instead of allowed_tools in ClaudeAgentOptions, which is
    ignored when permission_mode="bypassPermissions".
    """
    allowed = frozenset(allowed_tools)

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
        return deny_hook_output(f"Tool '{tool_name}' not in allowed list.")

    return cast(
        HooksConfig,
        {
            "PreToolUse": [HookMatcher(hooks=[allowlist_hook])],
        },
    )
