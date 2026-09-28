"""Codex's half of the caller hook: which conversation made a tool call.

Shipped verbatim into the plugin's ``hooks/runtime/``, where the caller hook's
generated entry runs it and the compiled permission dispatcher imports it. It
holds only what Codex spells for itself: the ``PreToolUse`` event, the
payload's keys, and the output envelope. What a caller is and how it rides in
a call are the store's.

One tool server serves every conversation of a session, so a coordination
call arriving there says nothing about who made it. The payload does:
measured on 0.155.1 in user-run sessions, with the payloads kept as fixtures,
a subagent's tool events carry its ``agent_id`` — its own thread's id — and
``agent_type`` beside the session's ``session_id``, and the parent's carry
neither. The 0.158.0 source builds both from the thread spawn that started
the subagent (``core/src/hook_runtime.rs``), and nothing else about it.

How Codex applies the rewrite is read out of that source rather than measured,
because a contained session reaches no Codex login and the live probe is the
operator's to run. ``hooks/src/engine/output_parser.rs`` refuses an
``updatedInput`` without ``permissionDecision: "allow"`` and a bare ``"allow"``
without an ``updatedInput``, so the two travel together;
``hooks/src/events/pre_tool_use.rs`` takes the latest rewrite of the matching
hooks; and ``core/src/tools/handlers/mcp.rs`` rebuilds an MCP call's arguments
whole from it. The ``allow`` settles nothing else: the coordination servers
are declared with their tools approved already.

What the spawn called the subagent is in no payload here — ``task_name`` is on
the spawning call, and its recorded response is a path-like handle
(``/root/<task_name>``) rather than the ``agent_id`` a subagent's events carry
— so the name stays blank and the row is reached by its id.

Every failure is silence: a call left unstamped acts as the session, which is
what every call did before there was anything to stamp.
"""

import json
import sys
from typing import Literal, TypedDict

from coordination.store import Caller, called_by, text
from kernel.policy_protocol import WireValue


class Payload(TypedDict, total=False):
    """What a tool event hands a hook, as far as the caller is read from it."""

    hook_event_name: str
    tool_input: dict[str, WireValue]
    agent_id: str
    agent_type: str
    cwd: str


class Rewritten(TypedDict):
    hookEventName: str
    permissionDecision: Literal["allow"]
    updatedInput: dict[str, WireValue | Caller]


class Rewrite(TypedDict):
    """The answer: the same call with its caller written in."""

    hookSpecificOutput: Rewritten


def caller_of(payload: Payload) -> Caller:
    """The conversation one tool event came from, blank for the session's own."""
    return Caller(
        agent_id=text(payload.get("agent_id")),
        agent_type=text(payload.get("agent_type")),
        cwd=text(payload.get("cwd")),
    )


def decided(payload: Payload) -> Rewrite | None:
    """The rewritten call, or nothing for an event this hook has no answer to."""
    if payload.get("hook_event_name") != "PreToolUse":
        return None
    return Rewrite(
        hookSpecificOutput=Rewritten(
            hookEventName="PreToolUse",
            permissionDecision="allow",
            updatedInput=called_by(payload.get("tool_input", {}), caller_of(payload)),
        )
    )


def main() -> None:
    """Answer the event on stdin, or say nothing and let the call through as it was."""
    try:
        payload: Payload = json.load(sys.stdin)
        answer = decided(payload)
    except Exception:
        return
    if answer is not None:
        print(json.dumps(answer))
