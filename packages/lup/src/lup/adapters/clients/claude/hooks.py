"""``LupHooksConfig`` → Claude SDK hook wiring.

The backend-neutral hook factories in :mod:`lup.hooks` produce
``LupHookMatcher``\\ s; this module adapts them to the SDK's in-process
hook callables, normalizing each native payload into the
:class:`~lup.hooks.LupHookInput` the factories read and converting each
:class:`~lup.hooks.LupHookOutput` back into the SDK's output shape.
"""

import json
from collections.abc import Awaitable, Callable

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.hooks import (
    LupHookEvent,
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
)
from lup.workspace.paths import extract_glob_dir
from lup.types import JsonObject

type ClaudeHooksConfig = dict[claude_types.HookEvent, list[claude_types.HookMatcher]]


def claude_hook_tool_path(tool_name: str, tool_input: JsonObject) -> str:
    """Resolve the directory a path-bearing Claude tool acts on.

    Write/Edit/Read carry ``file_path``; Grep carries ``path``; Glob carries
    ``path`` or, failing that, the directory prefix of its ``pattern``. Every
    other tool resolves to ``""``. This is the single place a native tool
    payload becomes the normalized ``LupHookInput.tool_path`` the backend-neutral
    hook factories read.
    """
    match tool_name:
        case "Write" | "Edit" | "Read":
            return str(
                tool_input.get("file_path", "")  # lup: ignore[dict-get] — payload
            )
        case "Grep":
            return str(
                tool_input.get("path", "")  # lup: ignore[dict-get] — per-tool payload
            )
        case "Glob":
            path = str(
                tool_input.get("path", "")  # lup: ignore[dict-get] — per-tool payload
            )
            pattern = str(
                tool_input.get("pattern", "")  # lup: ignore[dict-get] — payload
            )
            return path or extract_glob_dir(pattern)
        case _:
            return ""


def build_claude_hook_handler(
    lup_matcher: LupHookMatcher,
    *,
    event: LupHookEvent,
) -> Callable[
    [claude.HookInput, str | None, claude_types.HookContext],
    Awaitable[claude_types.SyncHookJSONOutput],
]:
    """Build a Claude SDK hook handler from a LupHookMatcher.

    ``event`` is the hook event this handler is registered under — it seeds
    the normalized :class:`LupHookInput` and drives the output conversion
    (permission decisions exist only on PreToolUse).
    """
    hook_fn = lup_matcher.hook

    async def claude_hook(
        input_data: claude.HookInput,
        _tool_use_id: str | None,
        _context: claude_types.HookContext,
    ) -> claude_types.SyncHookJSONOutput:
        if "tool_name" in input_data and "tool_input" in input_data:
            tool_name, tool_input = input_data["tool_name"], input_data["tool_input"]
        else:
            tool_name, tool_input = "", {}
        tool_result = ""
        if "tool_response" in input_data:
            response = input_data["tool_response"]
            tool_result = (
                response
                if isinstance(response, str)
                else json.dumps(response, default=str)
            )
        stop_hook_active = (
            input_data["stop_hook_active"]
            if "stop_hook_active" in input_data
            else False
        )
        lup_input = LupHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_path=claude_hook_tool_path(tool_name, tool_input),
            tool_result=tool_result,
            stop_hook_active=stop_hook_active,
        )
        lup_output = await hook_fn(lup_input)
        return lup_hook_output_to_claude(lup_output, event=event)

    return claude_hook


def lup_hooks_to_claude(hooks: LupHooksConfig) -> ClaudeHooksConfig:
    """Convert SDK-agnostic LupHooksConfig to Claude SDK hook format."""

    def to_claude_matcher(
        lup_matcher: LupHookMatcher, event: LupHookEvent
    ) -> claude_types.HookMatcher:
        handler = build_claude_hook_handler(lup_matcher, event=event)
        if lup_matcher.matcher:
            return claude_types.HookMatcher(
                matcher=lup_matcher.matcher, hooks=[handler]
            )
        return claude_types.HookMatcher(hooks=[handler])

    return {
        event_name: [to_claude_matcher(m, event_name) for m in matchers]
        for event_name, matchers in hooks.by_event().items()
    }


def lup_hook_output_to_claude(
    output: LupHookOutput,
    *,
    event: LupHookEvent = "PreToolUse",
) -> claude_types.SyncHookJSONOutput:
    """Convert a LupHookOutput to Claude SDK SyncHookJSONOutput.

    Permission decisions (``allow``/``deny``) exist only on PreToolUse;
    on every other event a denial converts to the generic ``block``
    decision, and an allow is a no-op output.
    """
    decision = output.decision
    reason = output.reason
    system_message = output.system_message

    match event, decision:
        case ("PreToolUse", "allow"):
            return claude_types.SyncHookJSONOutput(
                hookSpecificOutput=claude_types.PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="allow",
                )
            )
        case ("PreToolUse", "deny"):
            return claude_types.SyncHookJSONOutput(
                hookSpecificOutput=claude_types.PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="deny",
                    permissionDecisionReason=reason,
                )
            )
        case (_, "deny" | "block"):
            return claude_types.SyncHookJSONOutput(decision="block", reason=reason)
        case _:
            if system_message:
                return claude_types.SyncHookJSONOutput(systemMessage=system_message)
            return claude_types.SyncHookJSONOutput()
