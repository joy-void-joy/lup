"""Codex's hooks: its payloads in, lup's events, its outputs out.

| Codex hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `PreToolUse` | `CallStarted` |
| `PostToolUse` | `CallFinished` |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

Codex has no file tools that say what they'll write before they write it: its
`apply_patch` is judged at the checkpoint, like a command. Its `PreToolUse` can't
ask, so an ask is held at the checkpoint, the agent waiting inside the hook until
the operator answers from a terminal (`lup-dev holds`). The agent hears a
checkpoint's report as `additionalContext` beside the call's result, and the result
reaches it untouched.

A Codex session holds only the worktree it started in, a declared gap until rooms
(`docs/judging-writes.md`, *Every worktree of the repository*): its hooks' `cwd` is
the "Working directory for the session", and `Bash` and `apply_patch` carry only
`tool_input.command` (its hooks docs), which lup doesn't parse. Under its
`workspace-write` sandbox a write elsewhere lies outside the writable roots, so
Codex's own approval decides it.

What this relies on, from Codex's hooks documentation and its source at
`rust-v0.156.1` (`codex-rs/hooks/schema/generated/`):
- the inputs: `PreToolUse` and `PostToolUse` carry `tool_use_id`, `PostToolUse` its
  `tool_response`, `SubagentStop` its `agent_id`; a subagent's calls carry their
  `agent_id`;
- `PreToolUse`'s `permissionDecision: "ask"` is "parsed but not supported yet", and
  a plain `allow` fails open: this adapter never answers `PreToolUse`;
- `PermissionRequest` fires for `apply_patch` only when the patch needs approval
  (outside the writable roots, or after a sandbox denial), and carries only the
  patch text: inside the worktree, Codex doesn't ask, and the checkpoint judges.
  This adapter leaves `PermissionRequest` to Codex's own approval;
- `PostToolUse` takes `hookSpecificOutput.additionalContext`, which "is added as
  extra developer context" (its docs). Past the handler's `additionalContextLimit`
  (2,500 tokens by default) Codex keeps the whole text in a file and shows a
  preview pointing at it (`hooks/src/output_spill.rs`), so nothing is lost, and the
  hook configuration raises the limit so a report arrives whole;
- `write_stdin` can deliver a command's `PostToolUse` with no `PreToolUse` of its
  own, under the original command's `tool_use_id`;
- a hook's `timeout` defaults to 600 seconds and has no maximum, so the hook
  configuration gives `PostToolUse` and `Stop` a day and more, for holds.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import Field, TypeAdapter
from pydantic.alias_generators import to_camel

from lup.types import Model, Settings
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
)
from lup_dev.policy.runtime import Runtime


class Variables(Settings):
    """The variables Codex sets in the commands its agent runs."""

    codex_thread_id: str | None = None
    """`CODEX_THREAD_ID`, set in every command Codex's agent runs.

    Codex's `core/src/unified_exec/process_manager.rs` inserts it into each
    command's environment after the shell environment policy, so a profile can't
    strip it. Hooks themselves run with Codex's own environment, without it.
    """


class Codex(Runtime):
    """Codex, as the judge sees it."""

    @override
    def name(self) -> str:
        return "codex"

    @override
    def asks_before(self) -> bool:
        return False

    @override
    def inside(self) -> bool:
        return bool(Variables().codex_thread_id)


class Output(Model, alias_generator=to_camel, populate_by_name=True):
    """What a hook prints for Codex, its fields in camel case."""


class PostToolUseAnswer(Output):
    """What `PostToolUse` adds beside the call's result."""

    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: PostToolUseAnswer


class Blocked(Output):
    """`Stop` or `SubagentStop` keeping the conversation going, and why."""

    decision: Literal["block"] = "block"
    reason: str


def failure_note(failure: Exception) -> str:
    """Say that judging failed, for the agent to pass on."""
    return f"lup's judge failed, so this wasn't judged: {failure!r}. Tell the operator."


class Payload(Model, ABC):
    """What every Codex hook receives on stdin, and how each answers."""

    session_id: str
    cwd: Path
    agent_id: str | None = None
    """The subagent the hook fires for; absent for the session's own conversation."""

    @abstractmethod
    def answer(self, bench: Bench) -> Output | None:
        """Act on the hook, and return what to print; none to print nothing."""

    @abstractmethod
    def failed(self, failure: Exception) -> Output | None:
        """Return what to print when judging itself failed."""


class SessionStart(Payload):
    """`SessionStart`: a session starts, resumes, or is cleared or compacted."""

    hook_event_name: Literal["SessionStart"]

    @override
    def answer(self, bench: Bench) -> Output | None:
        SessionStarted(
            session=self.session_id, agent=self.agent_id or "", cwd=self.cwd
        ).apply(bench)
        return None

    @override
    def failed(self, failure: Exception) -> Output | None:
        return None


class PreToolUse(Payload):
    """`PreToolUse`: a tool call about to run."""

    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_use_id: str

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Count the call as running; a call running a subagent isn't counted."""
        CallStarted(
            session=self.session_id,
            agent=self.agent_id or "",
            cwd=self.cwd,
            call=self.tool_use_id,
            tool=self.tool_name,
            spawns=self.tool_name == "spawn_agent",
        ).apply(bench)
        return None

    @override
    def failed(self, failure: Exception) -> Output | None:
        return None


class PostToolUse(Payload):
    """`PostToolUse`: a tool call finished."""

    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_use_id: str

    @override
    def answer(self, bench: Bench) -> Output | None:
        finished = CallFinished(
            session=self.session_id,
            agent=self.agent_id or "",
            cwd=self.cwd,
            call=self.tool_use_id,
        )
        reply = finished.apply(bench)
        if not reply.context:
            return None
        said = PostToolUseAnswer(additional_context=reply.context)
        return Specific(hook_specific_output=said)

    @override
    def failed(self, failure: Exception) -> Output | None:
        said = PostToolUseAnswer(additional_context=failure_note(failure))
        return Specific(hook_specific_output=said)


class Stop(Payload):
    """`Stop`: the session's own conversation ends its turn."""

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = TurnEnded(session=self.session_id, agent="", cwd=self.cwd)
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

    @override
    def failed(self, failure: Exception) -> Output | None:
        """Say so once; a judge that keeps failing mustn't keep the turn from ending."""
        return None if self.stop_hook_active else Blocked(reason=failure_note(failure))


class SubagentStop(Payload):
    """`SubagentStop`: a subagent's conversation ends."""

    hook_event_name: Literal["SubagentStop"]

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id, agent=self.agent_id or "", cwd=self.cwd
        )
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

    @override
    def failed(self, failure: Exception) -> Output | None:
        return None


type Received = Annotated[
    SessionStart | PreToolUse | PostToolUse | Stop | SubagentStop,
    Field(discriminator="hook_event_name"),
]
"""Any hook payload this adapter answers, told apart by its event's name."""


def hook(raw: str, bench: Bench) -> str:
    """Answer one Codex hook: its payload in, what it prints out.

    A hook must answer whatever failed, so judging's failure is answered in the
    hook's own terms.
    """
    received: Payload = TypeAdapter[Received](Received).validate_json(raw)
    try:
        output = received.answer(bench)
    except Exception as failure:
        output = received.failed(failure)
    if output is None:
        return ""
    return output.model_dump_json(by_alias=True, exclude_none=True)
