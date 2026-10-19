"""Claude Code's hooks, its payloads in, lup's events, its outputs out; and its release channel.

| Claude Code hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `PreToolUse` | `CallStarted`; for `Edit` and `Write`, judged before it lands first |
| `PostToolUse`, `PostToolUseFailure` | `CallFinished` |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

A file tool's write that asks is held in `PreToolUse` for the operator's answer
in their inbox, then let through (`allow`) or denied (`deny`) with it: Claude
Code's own prompt isn't used, so a hold is answered the same way on every
runtime. The agent hears a
checkpoint's report as `additionalContext` beside the call's result, and a turn,
the session's or a subagent's, can't end while a `Stop` or `SubagentStop` hook
answers `decision: block`; `Stop`'s `stop_hook_active` says the session's turn's
end follows such a block. When judging itself fails at a turn's end, the turn
ends, and the operator is warned once in `systemMessage`, which also carries what
the session's turn's end tells without holding it.

In a launched room (`docs/launch.md`, *The one hook and the host service*), Claude
Code runs the room's hook on `SessionStart`, `PreToolUse` for every call, `Stop`
and `SubagentStop` (`hooks`), so the host service hears each conversation's start,
calls and turn's ends (`docs/host-tools.md`, *How an agent is told*). The judge
reads only `SessionStart` and the file tools' writes, judged before they land
(`heard`, `WRITING`): no checkpoint, as in lup's own repository, so the turn's ends
hold back nothing of the judge's. Every other hook the service answers itself,
without starting the judge, as no decision. Where the launch's judge can't answer
a hook, the host service answers it through `unanswered`: a file tool's write is
denied, naming why, since a write let through unjudged would land unseen; any
other hook warns the operator in `systemMessage`, and the call goes on. Where the
room's hook can't reach the service, it ends with status 1 and says why on
standard error: a non-blocking error, which Claude Code shows, and the call goes
on.

The service adds to each answer through `told`: a call to lup's tools
(`mcp__lup__<tool>`, `TOOL_PREFIX`) is rewritten to carry `caller`, lup's id for
the conversation calling, as `updatedInput` with no decision, so the call goes
through the session's own permission mode as it would have; and what the
conversation is told goes in as `additionalContext` beside a call or a session's
start, or as the reason a turn's end is held (`decision: "block"`). What a hook
tells whole is 10,000 bytes (`heard`'s `fits`): Claude Code caps a hook's
`additionalContext` at 10,000 characters, which a text's UTF-8 bytes never
undercount, and an item past it is announced instead. A turn's end following a
hold, the session's or a subagent's, carries `stop_hook_active`, so the next
end is let through.

An idle session is woken through its own messaging socket (`woken`), which the
launch puts in the room's socket directory: Claude Code "starts a new turn with
the message" when the receiving session is idle, and closes a connection that
hasn't sent a complete line within 30 seconds, so the host writes the whole line
at once (its `cross-session-messaging` docs, read 2026-10-14). The docs give
only the optional first line, `{"type":"auth","token":…}`, which Linux doesn't
require; the message's own frame is undocumented. The first lup measured it on
2.1.278 to 2.1.285: `{"type":"user","message":{"role":"user","content":…}}`, the
message as the session's own user turn, started an idle background session's
turn, through a socket moved by `--messaging-socket-path` too (its
`coordination/wake.py`, `195ff73f3`); and a frame naming another session in
`session_id` was dropped, only the one carrying the receiver's own id arriving
(`68eaa2e2e`). The 2.1.296 binary agrees (a byte search, `docs/field-notes.md`):
a `user` frame's `message.content` must be a non-empty string, a `session_id`
other than the session's own drops it, and a missing `priority` is `next`, which
interrupts nothing. Owed live on the version a launch runs
(`docs/field-notes.md`, *Piece 2, live*). Seen live on 2.1.296: it refuses to start with the socket's
directory at mode 0755 ("--messaging-socket-path directory /run/lup is not
private (mode 755); the socket directory must be mode 0700 so no other user or
group can reach or replace the socket"), so the host service keeps each launch's
socket directory at 0700.

What the host's part relies on, from Claude Code's hooks reference
(code.claude.com/docs/en/hooks, read 2026-10-14):
- "MCP tools follow the naming pattern `mcp__<server>__<tool>`", and "appear as
  regular tools in tool events";
- `PreToolUse`'s `updatedInput` "Modifies the tool's input parameters before
  execution. Replaces the entire input object, so include unchanged fields
  alongside modified ones"; the reference pairs it with `allow` or `ask`, and is
  silent on it alone. The first lup measured on Claude Code 2.1.283 that "a
  rewrite with no decision reached the server even for a tool with
  `additionalProperties: false`" (its `docs/platform-differentiation.md`); owed
  live on the version a launch runs (`docs/field-notes.md`, *Piece 2, live*);
- `PreToolUse`'s `additionalContext` is a "String added to Claude's context
  alongside the tool result", `SessionStart`'s one "added to Claude's context at
  the start of the conversation", and a hook's `additionalContext` is "capped at
  10,000 characters", past which Claude Code saves it to a file that "Claude can
  read ... but Claude Code doesn't ask it to";
- `Stop` and `SubagentStop`: `decision: "block"` "prevents Claude from
  stopping", its `reason` "Required when `decision` is `"block"`. Tells Claude
  why it should continue"; "SubagentStop hooks receive `stop_hook_active`" as
  `Stop` hooks do.

What its judging relies on, from Claude Code's hooks reference
(code.claude.com/docs/en/hooks):
- a hook ending with status 0 and printing nothing has "no decision to report";
  with any status but 0 or 2 it's "a non-blocking error": "You see a `<hook
  name> hook error` notice in the transcript with `Failed with non-blocking
  status code:` and the first line of your hook's stderr", and "The action goes
  ahead"; status 2 alone blocks the call, so the room's hook never ends with it;
- `systemMessage` is a "Warning message shown to the user";
- `tool_use_id` is in both `PreToolUse` and `PostToolUse`, so a call's start and
  finish match; a call that fails fires `PostToolUseFailure` instead, with the same
  id;
- `PreToolUse` "runs before a tool call executes", `PostToolUse` "after a tool call
  succeeds": a call never finishes before it starts, so the calls running stay
  right when calls run in parallel, whose hooks "run in parallel";
- a `command` hook's timeout defaults to 600 seconds, and "a timed-out command
  ... hook doesn't block the tool call", so a judgement must answer within it;
- a subagent's hooks carry `agent_id`, "Present only when the hook fires inside a
  subagent call", beside its session's `session_id` (seen in #32), and
  `SubagentStop` "Runs when a Claude Code subagent has finished responding";
- `Stop`'s `stop_hook_active` "is `true` when Claude Code is already continuing as
  a result of a stop hook"; `SubagentStop` takes "the same decision control format
  as Stop hooks".

Its release channel (`ClaudeChannel`) is the one its native installer reads
(`https://claude.ai/install.sh`, read on 2026-10-13):
- `<releases>/latest` is the newest version, as text;
- `<releases>/<version>/manifest.json` publishes each platform's binary with its
  SHA-256 (`platforms["linux-x64"].checksum`), and `manifest.zst.json` the same
  binary compressed with zstd, a third of its size, with that file's SHA-256;
- the installer downloads `<releases>/<version>/<platform>/claude.zst` when `zstd`
  is installed, checks it against `manifest.zst.json`, decompresses it and checks
  the binary against `manifest.json`; as this adapter does, with Python's zstd;
- `manifest.json` is also signed with Anthropic's release key
  (`manifest.json.sig`; code.claude.com/docs/en/setup, *Binary integrity and code
  signing*), which lup doesn't check.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup.adapters.claude.layout import ClaudeLayout
from lup.adapters.claude.settings import ClaudeSettings
from lup.sessions.terminal import Cli, Hook
from lup.types import JsonObject, Model, Settings
from lup_dev.adapters import Adapter
from lup_dev.host.courier import Heard, Spawned, Spawning, Telling
from lup_dev.host.records import (
    Called,
    Entry,
    Reader,
    Record,
    Records,
    Transcript,
    within,
)
from lup_dev.host.records import Said as Spoken
from lup_dev.host.rooms import SERVER, stamp
from lup_dev.launch.clis import (
    Channel,
    ChannelError,
    check,
    decompress,
    document,
    download,
    executable,
    text,
)
from lup_dev.policy.before import Decision, Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    first_warning,
)
from lup_dev.policy.report import judge_failed
from lup_dev.policy.runtime import Runtime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import timedelta

    import httpx

    from lup.sessions.declaration import Declaration
    from lup.sessions.terminal import Event

WRITING = ["Edit", "Write"]
"""The file tools whose writes are judged before they land: `PreToolUse.proposal`
reads each, and in a launched session the judge reads their calls alone."""

TOOL_PREFIX = f"mcp__{SERVER}__"
"""What Claude Code names each of lup's tools by in a hook: `mcp__lup__blocked`."""


class Variables(Settings):
    """The variables Claude Code sets in the commands it runs."""

    claude_code_child_session: str | None = None
    """`CLAUDE_CODE_CHILD_SESSION`, `1` in what Claude Code's tools and hooks run.

    Its environment-variable reference: "Set to `1` in subprocesses Claude Code
    spawns via the Bash, PowerShell, and Monitor tools, hook commands, and status
    line commands". Unlike `CLAUDECODE`, IDE extensions don't set it in their
    terminals, where the operator may answer a hold.
    """


class Claude(Runtime):
    """Claude Code, as the judge sees it."""

    @override
    def name(self) -> str:
        return "claude"

    @override
    def inside(self) -> bool:
        return bool(Variables().claude_code_child_session)


class Output(Model, alias_generator=to_camel, populate_by_name=True):
    """What a hook prints for Claude Code, its fields in camel case."""


class PreToolUseAnswer(Output):
    """`PreToolUse`'s decision on the call."""

    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "ask", "deny"] | None = None
    permission_decision_reason: str | None = None
    additional_context: str | None = None


class PostToolUseAnswer(Output):
    """What `PostToolUse` adds beside the call's result."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: PreToolUseAnswer | PostToolUseAnswer


class Blocked(Output):
    """`Stop` or `SubagentStop` refusing to let the conversation end, and why."""

    decision: Literal["block"] = "block"
    reason: str


class OperatorWarning(Output):
    """A warning shown to the operator, not the agent, which lets the turn end.

    The hooks reference: `systemMessage` is a "Warning message shown to the user",
    and `Stop`'s own section neither discards nor redirects it. Anything `Stop`
    tells the agent, `reason` or `additionalContext`, keeps the turn going.
    """

    system_message: str


class Context(Output, extra="allow"):
    """`hookSpecificOutput`, as any hook's answer holds it: what `told` reads and adds to.

    What it doesn't name is kept as it was given.
    """

    hook_event_name: str
    permission_decision: str | None = None
    permission_decision_reason: str | None = None
    additional_context: str | None = None
    updated_input: JsonObject | None = None
    session_title: str | None = None
    """At a session's start, the name Claude Code gives the session, as `/rename`
    does (its `hooks` docs: "Sets the session title, with the same effect as
    `/rename`")."""


class Said(Output, extra="allow"):
    """Any answer a Claude Code hook prints, the judge's or none: what `told` reads and adds to.

    What it doesn't name is kept as it was given.
    """

    decision: str | None = None
    reason: str | None = None
    system_message: str | None = None
    hook_specific_output: Context | None = None


def joined(given: str | None, items: list[str]) -> str:
    """Return what `given` says, then each item, a blank line between each."""
    return "\n\n".join([*([given] if given else []), *items])


def context(said: Said, event: str, items: list[str]) -> Said:
    """Return `said` with `items` told as `additionalContext` for `event`, after any context it gives."""
    if not items:
        return said
    given = said.hook_specific_output or Context(hook_event_name=event)
    added = given.model_copy(
        update={"additional_context": joined(given.additional_context, items)}
    )
    return said.model_copy(update={"hook_specific_output": added})


def held(said: Said, items: list[str]) -> Said:
    """Return `said` holding a turn's end on `items`, after any reason it holds it for."""
    if not items:
        return said
    return said.model_copy(
        update={"decision": "block", "reason": joined(said.reason, items)}
    )


def failure_note(failure: Exception) -> str:
    """Say that judging failed, for the agent to pass on."""
    return f"lup's judge failed, so this wasn't judged: {failure!r}. Tell the operator."


class Payload(Model, ABC):
    """What every Claude Code hook receives on stdin, and how each answers."""

    session_id: str
    cwd: Path
    agent_id: str = ""
    """The subagent the hook fires for; absent for the session's own conversation."""
    transcript_path: Path | None = None
    """The session's transcript: its subagents' records are beside it."""

    @abstractmethod
    def answer(self, bench: Bench) -> Output | None:
        """Act on the hook, and return what to print; none to print nothing."""

    @abstractmethod
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Return what to print when judging itself failed."""

    @abstractmethod
    def unanswered(self, said: str) -> Output:
        """Return what to print where lup's judge couldn't answer the hook at all, `said` saying why."""


class SessionStart(Payload):
    """`SessionStart`: a session starts, resumes, or is cleared or compacted."""

    hook_event_name: Literal["SessionStart"]
    session_title: str | None = None
    """The session's custom title, where one is set (`--name`, `/rename`, a
    hook's `sessionTitle`); not the title Claude Code generates."""

    def heard(self, fits: int) -> Heard:
        """Read the session's start, and the name the operator gave it in Claude Code: the judge reads it."""
        return Heard(
            event="session-started",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=fits,
            title=self.session_title,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items as it starts, and name the session as its launch is named."""
        told = context(said, self.hook_event_name, telling.items)
        if telling.title is None:
            return told
        given = told.hook_specific_output or Context(
            hook_event_name=self.hook_event_name
        )
        titled = given.model_copy(update={"session_title": telling.title})
        return told.model_copy(update={"hook_specific_output": titled})

    @override
    def answer(self, bench: Bench) -> Output | None:
        SessionStarted(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


class Edit(Model):
    """The `Edit` tool's input."""

    file_path: Path
    old_string: str
    new_string: str
    replace_all: bool = False


class Write(Model):
    """The `Write` tool's input."""

    file_path: Path
    content: str


class PreToolUse(Payload):
    """`PreToolUse`: a tool call about to run."""

    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: JsonObject
    tool_use_id: str

    def proposal(self) -> Replacement | Overwrite | None:
        """Read a file tool's call as what it proposes to write; none for others."""
        match self.tool_name:
            case "Edit":
                edit = Edit.model_validate(self.tool_input)
                return Replacement(
                    call=self.tool_use_id,
                    tool=self.tool_name,
                    path=self.cwd / edit.file_path,
                    old=edit.old_string,
                    new=edit.new_string,
                    everywhere=edit.replace_all,
                )
            case "Write":
                write = Write.model_validate(self.tool_input)
                return Overwrite(
                    call=self.tool_use_id,
                    tool=self.tool_name,
                    path=self.cwd / write.file_path,
                    text=write.content,
                )
            case _:
                return None

    def heard(self, fits: int) -> Heard:
        """Read the call's start: the judge reads a file tool's write alone."""
        return Heard(
            event="call-started",
            session=self.session_id,
            agent=self.agent_id or None,
            call=self.tool_use_id,
            tool=self.tool_name,
            served=self.tool_name.startswith(TOOL_PREFIX),
            judged=self.tool_name in WRITING,
            fits=fits,
            spawning=(
                Spawning(
                    name=AgentCall.model_validate(self.tool_input).name,
                    naming="`name` on `Agent`, which it takes though its schema doesn't list it",
                )
                if self.tool_name in SPAWNING and not self.agent_id
                else None
            ),
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items beside the call, and stamp a call to lup's tools with its caller.

        The stamp is `updatedInput` with no decision added, so the call goes
        through the session's own permission mode as it would have. A call the
        judge refused never runs, so it isn't stamped.
        """
        told = context(said, self.hook_event_name, telling.items)
        given = told.hook_specific_output or Context(
            hook_event_name=self.hook_event_name
        )
        if (
            not self.tool_name.startswith(TOOL_PREFIX)
            or given.permission_decision == "deny"
        ):
            return told
        stamped = given.model_copy(
            update={
                "updated_input": stamp(
                    self.tool_input, telling.caller, self.tool_use_id
                )
            }
        )
        return told.model_copy(update={"hook_specific_output": stamped})

    def started(self) -> CallStarted:
        """Return the event of this call starting.

        A call running a subagent (`Agent`) isn't counted: its own calls are.
        """
        return CallStarted(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            call=self.tool_use_id,
            tool=self.tool_name,
            spawns=self.tool_name in ["Agent", "Task"],
        )

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Judge a file tool's write before it lands, and count the call as running; a write held and declined never runs, so it isn't counted."""
        proposed = self.proposal()
        decision = (
            Decision(outcome=None)
            if proposed is None
            else before(
                bench, proposed, self.session_id, self.cwd, self.agent_id or None
            )
        )
        match decision.outcome:
            case None:
                self.started().apply(bench)
                return None
            case "deny":
                answer = PreToolUseAnswer(
                    permission_decision="deny",
                    permission_decision_reason=decision.reason,
                )
                return Specific(hook_specific_output=answer)
            case "allow":
                self.started().apply(bench)
                answer = PreToolUseAnswer(
                    permission_decision="allow",
                    permission_decision_reason=decision.reason or None,
                    additional_context=decision.told or None,
                )
                return Specific(hook_specific_output=answer)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Refuse a file tool's write; let other calls go on, told why.

        A crashing hook is a non-blocking error to Claude Code, which would let a
        write meant for review through unseen.
        """
        told = failure_note(failure)
        if self.proposal() is None:
            return Specific(
                hook_specific_output=PreToolUseAnswer(additional_context=told)
            )
        refused = PreToolUseAnswer(
            permission_decision="deny", permission_decision_reason=told
        )
        return Specific(hook_specific_output=refused)

    @override
    def unanswered(self, said: str) -> Output:
        """Refuse a file tool's write, telling the agent why; warn the operator of any other call, which goes on.

        Let through, a write would land unjudged and unseen.
        """
        if self.tool_name not in WRITING:
            return OperatorWarning(system_message=said)
        refused = PreToolUseAnswer(
            permission_decision="deny",
            permission_decision_reason=f"{said}. Tell the operator.",
        )
        return Specific(hook_specific_output=refused)


class PostToolUse(Payload):
    """`PostToolUse` or `PostToolUseFailure`: a tool call finished, or failed."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    tool_name: str
    tool_use_id: str

    def heard(self, fits: int) -> Heard:
        """Read the call's finish: the judge reads it, where it's hooked."""
        return Heard(
            event="call-finished",
            session=self.session_id,
            agent=self.agent_id or None,
            call=self.tool_use_id,
            tool=self.tool_name,
            judged=True,
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items beside the call's result."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        finished = CallFinished(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            call=self.tool_use_id,
        )
        reply = finished.apply(bench)
        if not reply.context:
            return None
        said = PostToolUseAnswer(
            hook_event_name=self.hook_event_name, additional_context=reply.context
        )
        return Specific(hook_specific_output=said)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        said = PostToolUseAnswer(
            hook_event_name=self.hook_event_name,
            additional_context=failure_note(failure),
        )
        return Specific(hook_specific_output=said)

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


class Stop(Payload):
    """`Stop`: the session's own conversation ends its turn.

    What the turn's end tells without holding it goes to the operator, in
    `systemMessage`: the hooks reference says `Stop`'s `additionalContext`, like
    `reason`, means "The conversation continues so Claude can act on it".
    """

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""
    last_assistant_message: str | None = None
    """"Text content of the last assistant message before stopping" (2.1.302's
    hook input schema)."""

    def heard(self, fits: int) -> Heard:
        """Read the turn's end: in a room, with no checkpoint, the judge doesn't read it."""
        return Heard(
            event="turn-ended",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=False,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the turn's end on the conversation's items."""
        return held(said, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = TurnEnded(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            after_block=self.stop_hook_active,
        )
        reply = ended.apply(bench)
        if reply.block:
            return Blocked(reason=reply.block)
        if reply.note:
            return OperatorWarning(system_message=reply.note)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Let the turn end, and warn the operator once: the agent can't fix it."""
        warning = judge_failed(failure)
        if not first_warning(bench.services.layout, self.session_id, warning):
            return None
        return OperatorWarning(system_message=warning)

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


class SubagentStop(Payload):
    """`SubagentStop`: a subagent's conversation ends its turn.

    The hooks reference: it takes "the same decision control format as Stop
    hooks", and a block "keeps the subagent running and delivers `reason` to the
    subagent as its next instruction".
    """

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool = False
    """Whether the subagent goes on because a `SubagentStop` hook blocked it already."""

    def heard(self, fits: int) -> Heard:
        """Read a subagent's turn's end: in a room, with no checkpoint, the judge doesn't read it."""
        return Heard(
            event="conversation-ended",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=False,
            after_block=self.stop_hook_active,
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the subagent's turn's end on its items."""
        return held(said, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        )
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Let the subagent's turn end, and warn the operator once, as `Stop` does."""
        warning = judge_failed(failure)
        if not first_warning(bench.services.layout, self.session_id, warning):
            return None
        return OperatorWarning(system_message=warning)

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


SPAWNING = ["Agent", "Task"]
"""The tool spawning a subagent, by its name and its earlier name."""


class AgentCall(Model, extra="ignore"):
    """The part of a call to `Agent` lup reads: the name the caller gives the subagent (the `sub-agents` docs: "Claude can give a subagent a name by passing a `name` parameter").

    Only the session's own conversation has it: a subagent's `Agent` takes no
    `name` (measured on 2.1.302, `docs/field-notes.md`, *Subagents' records*).
    """

    name: str | None = None


class SubagentRecord(Model, extra="ignore", alias_generator=to_camel):
    """What Claude Code records of a subagent beside the session's transcript, `<session>/subagents/agent-<id>.meta.json`.

    Undocumented, read as measured on 2.1.301 and 2.1.302
    (`docs/field-notes.md`, *Subagents' records*): the subagent's type, the
    name its parent gave it, and the subagent that spawned it, where one did.
    """

    agent_type: str | None = None
    name: str | None = None
    parent_agent_id: str | None = None


class Subagented(Model, extra="ignore"):
    """Any hook's payload, as far as finding a subagent's record reads it."""

    session_id: str
    agent_id: str = ""
    agent_type: str = ""
    transcript_path: Path | None = None


def spawned(raw: str) -> Spawned | None:
    """Return how the subagent a Claude Code hook fires for was spawned, from its record beside the session's transcript; none for the session's own conversation.

    A subagent whose record isn't there is said by its type alone.
    """
    payload = Subagented.model_validate_json(raw)
    if not payload.agent_id:
        return None
    kind = payload.agent_type or None
    if payload.transcript_path is None:
        return Spawned(kind=kind)
    folder = payload.transcript_path.with_suffix("") / "subagents"
    record = folder / f"agent-{payload.agent_id}.meta.json"
    if not record.is_file():
        return Spawned(kind=kind)
    kept = SubagentRecord.model_validate_json(record.read_text())
    return Spawned(
        name=kept.name, parent=kept.parent_agent_id, kind=kept.agent_type or kind
    )


type Received = Annotated[
    SessionStart | PreToolUse | PostToolUse | Stop | SubagentStop,
    Field(discriminator="hook_event_name"),
]
"""Any hook payload this adapter answers, told apart by its event's name."""


def hook(raw: str, bench: Bench) -> str:
    """Answer one Claude Code hook: its payload in, what it prints out.

    A hook must answer whatever failed, so judging's failure is answered in the
    hook's own terms.
    """
    received: Payload = TypeAdapter[Received](Received).validate_json(raw)
    try:
        output = received.answer(bench)
    except Exception as failure:
        output = received.failed(bench, failure)
    if output is None:
        return ""
    return output.model_dump_json(by_alias=True, exclude_none=True)


def unanswered(raw: str, failure: str) -> str:
    """Answer a hook lup's judge couldn't, saying `failure` in Claude Code's terms.

    Each hook answers as its payload says (`Payload.unanswered`); a payload that
    doesn't read as a hook warns the operator in `systemMessage`.
    """
    said = f"lup's judge couldn't answer this hook, so it wasn't judged: {failure}"
    try:
        received: Payload = TypeAdapter[Received](Received).validate_json(raw)
    except ValidationError:
        output: Output = OperatorWarning(system_message=said)
    else:
        output = received.unanswered(said)
    return output.model_dump_json(by_alias=True, exclude_none=True)


def heard(raw: str, fits: int = 10_000) -> Heard:
    """Read one Claude Code hook as the host service does: who's speaking, about which call, and whether the judge reads it.

    Each hook's answer tells `fits` bytes whole: Claude Code's cap on a hook's
    `additionalContext`, in characters, which UTF-8 bytes never undercount. Raise
    `ValidationError` where the payload isn't one of the hooks this adapter reads.
    """
    return TypeAdapter[Received](Received).validate_json(raw).heard(fits)


def ends(printed: str) -> bool:
    """Say whether what a turn's end hook prints lets the turn end: it holds the turn with `decision: "block"`.

    >>> ends(""), ends('{"decision":"block","reason":"wait"}')
    (True, False)
    """
    said = Said.model_validate_json(printed) if printed.strip() else Said()
    return said.decision != "block"


def told(raw: str, answer: str, telling: Telling) -> str | None:
    """Return what a Claude Code hook prints: `answer`, the judge's or none, with `telling` added; none where nothing is.

    Raise `ValidationError` where the payload isn't one of the hooks this adapter
    reads, or the answer isn't a hook's.
    """
    received = TypeAdapter[Received](Received).validate_json(raw)
    said = Said.model_validate_json(answer) if answer.strip() else Said()
    added = received.told(said, telling)
    if added == said:
        return None
    return added.model_dump_json(by_alias=True, exclude_none=True)


class UserTurn(Model):
    """The message a frame carries, as the session's own user turn."""

    role: Literal["user"] = "user"
    content: str


class Frame(Model):
    """One message to a session's messaging socket, a line of JSON: a user turn, for the session it names."""

    type: Literal["user"] = "user"
    message: UserTurn
    session_id: str
    """The session it's for: one whose id differs drops it."""


def woken(session: str, text: str) -> str:
    """Return the line that starts a turn of the idle Claude Code session `session` with `text`, on its messaging socket.

    >>> woken("s1", "hi")
    '{"type":"user","message":{"role":"user","content":"hi"},"session_id":"s1"}'
    """
    return Frame(message=UserTurn(content=text), session_id=session).model_dump_json()


def hooks(command: list[str], timeout: timedelta) -> list[Hook]:
    """Return the hooks a launched Claude Code session runs `command` at: the events the host service hears.

    `SessionStart`; `PreToolUse` on every call, the file tools' writes judged
    before they land, every call told what waits for its conversation, and a
    call to lup's tools stamped with its caller; `Stop` and `SubagentStop`, each
    conversation's turn's end. Each waits up to `timeout`, which a hold's wait
    for the operator needs.
    """
    events: list[Event] = [
        "session-started",
        "call-started",
        "turn-ended",
        "conversation-ended",
    ]
    return [Hook(event=event, command=command, timeout=timeout) for event in events]


def agent() -> Declaration:
    """Return the declaration a launched Claude Code session runs: no model, so Claude Code reads the operator's own."""
    return lup.Claude()


class Build(Model):
    """One platform's file in a release's manifest."""

    checksum: str
    """Its SHA-256, as hex."""


class Manifest(Model):
    """A release's manifest: its version, and each platform's file with its checksum."""

    version: str
    platforms: dict[str, Build]


class ClaudeChannel(Channel):
    """Claude Code's release channel, read as its native installer reads it."""

    releases: str = "https://downloads.claude.ai/claude-code-releases"
    """The channel's root: the newest version, and each version's manifests and files."""
    platform: str = "linux-x64"
    """The manifests' name for Linux on x86-64 against glibc, which the room's Arch Linux has."""
    binary: str = "claude"
    """The binary's name, in the channel and in its version's directory."""

    @override
    def latest(self, client: httpx.Client) -> str:
        return text(client, f"{self.releases}/latest").strip()

    @override
    def download(self, client: httpx.Client, version: str, into: Path) -> None:
        release = f"{self.releases}/{version}"
        binary = self.build(client, f"{release}/manifest.json", version)
        packed = self.build(client, f"{release}/manifest.zst.json", version)
        archive = into / f"{self.binary}.zst"
        url = f"{release}/{self.platform}/{archive.name}"
        check(url, download(client, url, archive), packed.checksum)
        program = into / self.binary
        check(f"{url}, decompressed,", decompress(archive, program), binary.checksum)
        archive.unlink()
        executable(program)

    @override
    def cli(self, directory: Path) -> Cli:
        return Cli(program=directory / self.binary)

    def build(self, client: httpx.Client, url: str, version: str) -> Build:
        """Return the platform's file, as the manifest at `url` for `version` lists it."""
        manifest = document(client, url, Manifest)
        if manifest.version != version:
            message = f"{url} describes {manifest.version}, not {version}"
            raise ChannelError(message)
        found = manifest.platforms.get(self.platform)
        if found is None:
            message = f"{url} lists no build for {self.platform}"
            raise ChannelError(message)
        return found


class Located(Model, extra="ignore"):
    """One line of a Claude Code session's record, for the directory it ran in, where it says."""

    cwd: Path | None = None


class ClaudeRecords(Model, Records):
    """Claude Code's records: a folder per directory sessions ran in, under `projects/`, and each session's file history.

    A folder's directory is read off its records' own lines, the first naming one,
    never from the folder's name.
    """

    directory: Path
    """The operator's Claude Code directory, `~/.claude` or `CLAUDE_CONFIG_DIR`."""

    @override
    def conversation(self, session: str, agent: str | None) -> Path | None:
        projects = self.directory / "projects"
        name = (
            f"{session}.jsonl"
            if agent is None
            else f"{session}/subagents/agent-{agent}.jsonl"
        )
        found = sorted(projects.glob(f"*/{name}")) if projects.is_dir() else []
        return next(iter(found), None)

    @override
    def kept(self, under: list[Path]) -> list[Record]:
        projects = self.directory / "projects"
        folders = sorted(projects.iterdir()) if projects.is_dir() else []
        ours = [
            folder
            for folder in folders
            if folder.is_dir() and (ran := ran_in(folder)) and within(ran, under)
        ]
        histories = [
            self.directory / "file-history" / session.stem
            for folder in ours
            for session in sorted(folder.glob("*.jsonl"))
        ]
        return [
            *(
                Record(source=folder, place=PurePosixPath("projects", folder.name))
                for folder in ours
            ),
            *(
                Record(source=each, place=PurePosixPath("file-history", each.name))
                for each in histories
                if each.is_dir()
            ),
        ]


def ran_in(folder: Path) -> Path | None:
    """Return the directory the sessions recorded in `folder` ran in, read off their first line naming one; none where none does."""
    for record in sorted(folder.glob("*.jsonl")):
        with record.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    located = Located.model_validate_json(line)
                except ValidationError:
                    continue
                if located.cwd is not None:
                    return located.cwd
    return None


class Origin(Model, extra="ignore"):
    """Where a message came from, as Claude Code records it: `human` for the operator's own words."""

    kind: str


class TextBlock(Model, extra="ignore"):
    """Text in a message."""

    type: Literal["text"]
    text: str


class ToolUse(Model, extra="ignore"):
    """A call to a tool, by its name, and its id, which the call's hooks carry as `tool_use_id`."""

    type: Literal["tool_use"]
    name: str
    id: str | None = None


class OtherBlock(Model, extra="ignore"):
    """Any other part of a message: a tool's result, thinking, an image."""

    type: str


type Block = Annotated[
    TextBlock | ToolUse | OtherBlock, Field(union_mode="left_to_right")
]


class UserMessage(Model, extra="ignore"):
    """A user line's message: text, or its parts."""

    content: str | list[Block]


class UserLine(Model, extra="ignore", alias_generator=to_camel):
    """A `user` line: the operator's words, a tool's result, or text Claude Code wrote in their place (a command's output, a notice)."""

    type: Literal["user"]
    message: UserMessage
    timestamp: datetime | None = None
    origin: Origin | None = None
    is_meta: bool = False
    is_compact_summary: bool = False
    is_sidechain: bool = False
    cwd: Path | None = None

    def operators(self) -> str | None:
        """Return the operator's words in it; none where it holds none of theirs.

        Measured on 2.1.302 (`docs/field-notes.md`, *A session's record*): the
        operator's are `origin.kind == "human"`. A line with no `origin` is
        theirs, as an earlier release wrote them, where it's text that isn't a
        tag Claude Code wrote (`<command-name>`, `<task-notification>`); one in
        parts with no `origin` is Claude Code's own (`[Request interrupted by
        user]`), and one in parts with a tool's result never is.
        """
        if self.is_meta or self.is_compact_summary or self.is_sidechain:
            return None
        if self.origin is not None and self.origin.kind != "human":
            return None
        match self.message.content:
            case str() as text:
                written = self.origin is None and text.startswith("<")
                return None if written else text
            case blocks:
                if self.origin is None:
                    return None
                texts = [block.text for block in blocks if isinstance(block, TextBlock)]
                return "\n".join(texts) if texts else None


class AssistantMessage(Model, extra="ignore"):
    """An assistant line's message: its parts."""

    content: list[Block] = []


class AssistantLine(Model, extra="ignore", alias_generator=to_camel):
    """An `assistant` line: the agent's text, and the tools it called."""

    type: Literal["assistant"]
    message: AssistantMessage
    timestamp: datetime | None = None
    is_sidechain: bool = False


class Queued(Model, extra="ignore", alias_generator=to_camel):
    """A message that arrived while the agent worked, given to it at its next step."""

    type: Literal["queued_command"]
    prompt: str
    command_mode: str | None = None
    origin: Origin | None = None


class OtherAttachment(Model, extra="ignore"):
    """Anything else Claude Code attaches: a hook's context, a reminder."""

    type: str


class AttachmentLine(Model, extra="ignore"):
    """An `attachment` line."""

    type: Literal["attachment"]
    attachment: Annotated[Queued | OtherAttachment, Field(union_mode="left_to_right")]
    timestamp: datetime | None = None


class CustomTitle(Model, extra="ignore", alias_generator=to_camel):
    """The name the operator gave the session (`/rename`), or lup did (`sessionTitle`)."""

    type: Literal["custom-title"]
    custom_title: str


class AgentName(Model, extra="ignore", alias_generator=to_camel):
    """The session's agent name."""

    type: Literal["agent-name"]
    agent_name: str


class AiTitle(Model, extra="ignore", alias_generator=to_camel):
    """The title Claude Code made for the session."""

    type: Literal["ai-title"]
    ai_title: str


type Line = Annotated[
    UserLine | AssistantLine | AttachmentLine | CustomTitle | AgentName | AiTitle,
    Field(discriminator="type"),
]
"""A line of a session's record lup reads; the others it passes over."""


class ClaudeTranscripts(Model, Reader):
    """Claude Code's records, read: a session's file per session under `projects/<folder>/`, its subagents' in a folder beside it."""

    @override
    def sessions(self, copies: Path) -> list[Path]:
        projects = copies / "projects"
        return sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []

    @override
    def read(self, record: Path) -> Transcript:
        lines = list(parsed(record))
        ran = [each.cwd for each in lines if isinstance(each, UserLine) and each.cwd]
        # A subagent's own record, `<session>/subagents/agent-<id>.jsonl`, is all
        # sidechain; a session's own is its main line.
        sidechain = record.parent.name == "subagents"
        return Transcript(
            runtime=Claude().name(),
            session=record.stem,
            title=named(lines),
            directory=next(iter(ran), None),
            entries=[
                entry for each in lines for entry in entries(each, sidechain=sidechain)
            ],
        )


def parsed(record: Path) -> Iterator[Line]:
    """Yield each line of `record` lup reads, passing over the others and any that isn't JSON."""
    reading = TypeAdapter[Line](Line)
    with record.open(encoding="utf-8", errors="replace") as written:
        for raw in written:
            try:
                yield reading.validate_json(raw)
            except ValidationError:
                continue


def named(lines: list[Line]) -> str | None:
    """Return a session's name: the last one the operator or lup gave it, else its last agent name, else Claude Code's last title; none where it has none."""
    custom = [each.custom_title for each in lines if isinstance(each, CustomTitle)]
    agents = [each.agent_name for each in lines if isinstance(each, AgentName)]
    titles = [each.ai_title for each in lines if isinstance(each, AiTitle)]
    return next((names[-1] for names in [custom, agents, titles] if names), None)


def entries(line: Line, *, sidechain: bool = False) -> list[Entry]:
    """Return the steps one line of a record holds: the operator's words, the agent's text, the tools it called; the agent's on the record's own line, its main one or, in a subagent's record, its `sidechain`."""
    match line:
        case UserLine(timestamp=at) as user:
            words = user.operators()
            return [] if words is None else [Spoken(by="operator", text=words, at=at)]
        case AssistantLine(timestamp=at, message=message) as agent if (
            agent.is_sidechain == sidechain
        ):
            return [
                step
                for block in message.content
                for step in [said_by_agent(block, at)]
                if step is not None
            ]
        case AttachmentLine(
            attachment=Queued(
                command_mode="prompt", origin=Origin(kind="human")
            ) as queued,
            timestamp=at,
        ):
            return [Spoken(by="operator", text=queued.prompt, at=at)]
        case _:
            return []


def said_by_agent(block: Block, at: datetime | None) -> Entry | None:
    """Return the step a part of the agent's message is: its text, or a tool it called; none for any other part."""
    match block:
        case TextBlock(text=text):
            return Spoken(by="agent", text=text, at=at)
        case ToolUse(name=name, id=id_):
            return Called(tool=name, id=id_, at=at)
        case _:
            return None


def adapter() -> Adapter:
    """Return what lup needs of Claude Code: its hooks answered, and its launch."""
    return Adapter(
        runtime=Claude(),
        hook=hook,
        unanswered=unanswered,
        heard=heard,
        told=told,
        ends=ends,
        spawned=spawned,
        woken=woken,
        hooks=hooks,
        channel=ClaudeChannel(),
        agent=agent,
        records=ClaudeRecords(directory=ClaudeLayout.of(ClaudeSettings()).directory),
        reader=ClaudeTranscripts(),
    )
