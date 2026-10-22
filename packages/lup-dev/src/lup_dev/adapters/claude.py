"""Claude Code's hooks, its payloads in, lup's events, its outputs out; and its release channel.

| Claude Code hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `UserPromptSubmit` | `TurnStarted` |
| `PreToolUse` | `CallStarted`; for `Edit` and `Write`, judged before it lands first |
| `PostToolUse`, `PostToolUseFailure` | `CallFinished`: the checkpoint |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

A file tool's write that asks is held in `PreToolUse` for the operator's answer
in their inbox, then let through (`allow`), told beside the call that lup held
it and they approved it, with their comment, or denied (`deny`) with it: Claude
Code's own prompt isn't used, so a hold is answered the same way on every
runtime. The agent hears what deferred work came due as `additionalContext` of
`SessionStart`, a checkpoint's report as `additionalContext` beside the call's
result, and what a turn's end tells it, the session's or a subagent's, as
`additionalContext` of `Stop` or `SubagentStop`, which holds the turn: it goes
on, the text shown as hook feedback rather than a hook error.
`stop_hook_active` says a turn's end follows such a hold. An end that doesn't
hold tells nothing: `systemMessage` would reach the operator, not the agent.
When judging itself fails at a turn's end, the turn ends, and the operator is
warned once in `systemMessage`.

In a launched room (`docs/host.md`, *The one hook*), Claude Code runs the room's
hook on `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and
`PostToolUseFailure` for every call, `Stop` and `SubagentStop` (`hooks`), so the
host service hears each conversation's start, each turn's start and the prompt
it starts on, its calls' starts and finishes, and its turn's ends
(`docs/inbox.md`, *How an agent is told*). The judge reads every one of them
(`heard`) but the calls `judging` leaves out: those to lup's own tools, and to a
tool on the list of those that only read (`Reading`). So every
write is judged: a file tool's before it lands, and anything else, a command's,
a script's, a notebook's, at the checkpoint after its call, which holds what
asks there until the operator answers, put back on a decline
(`docs/judging-writes.md`, *After a call: the checkpoint*). A turn's end clears
the calls its conversation left that no finish reported, runs a last checkpoint,
and holds the session's turn while the files it touched have findings
(`docs/judging-writes.md`, *The turn's end*). Every other hook the service
answers itself, without starting the judge, as no decision. Where the launch's
judge can't answer a hook, the host service answers it through `unanswered`: a
file tool's write is denied, naming why, since a write let through unjudged
would land unseen; at a call's finish the agent is told beside its result, as
when judging fails; any other hook warns the operator in `systemMessage`, and
the call goes on. Where the room's hook can't reach the service, it ends with
status 1 and says why on standard error: a non-blocking error, which Claude Code
shows, and the call goes on.

The service adds to each answer through `told`: a call to lup's tools
(`mcp__lup__<tool>`, `TOOL_PREFIX`) is rewritten to carry `caller`, lup's id for
the conversation calling, as `updatedInput` with no decision, so the call goes
through the session's own permission mode as it would have; and what the
conversation is told goes in as `additionalContext`, beside a call or a session's
start, or holding a turn's end. What a hook
tells whole is 10,000 bytes (`heard`'s `fits`): Claude Code caps a hook's
`additionalContext` at 10,000 characters, which a text's UTF-8 bytes never
undercount, and an item past it is announced instead. A turn's end following a
hold, the session's or a subagent's, carries `stop_hook_active`, so the next
end is let through.

**The session's title in Claude Code,** the one `/rename` sets, is heard and
given at its start and at each prompt of its own conversation (`docs/launch.md`,
*Names*): the payload's `session_title` is read (`Heard.title`), so a title the
operator gave becomes the launch's name, and the service gives the launch's name
back as `sessionTitle` where the two differ, so a rename through lup reaches
Claude Code at the next prompt. From the hooks reference (read 2026-10-22):
`SessionStart`'s `sessionTitle` "Sets the session title, with the same effect as
`/rename`. Applies when `source` is `"startup"`, `"resume"`, or `"fork"`"
(`TitledStart`), and `UserPromptSubmit`'s "Sets the session title"; both hooks
receive `session_title`, "The session's custom title, present when one is set,
for example with `--name`, `/rename`, a hook's `sessionTitle` output". A
`UserPromptSubmit` hook defaults to a 30-second timeout, past which its output
is discarded; the room's waits as long as every other hook of the room does.
Measured on 2.1.303 (`docs/field-notes.md`, *A session's title*): `sessionTitle`
at either hook writes the two lines `/rename` writes, and the next prompt and a
resume carry the title back, a resume the one lup gave at the session's first
start included, so the service tells the titles it gave from the operator's
(`Names.title`).

An idle session is woken first through lup's tool server, as a channel's
message (`pushed`, `CHANNEL`), which the launch loads with
`--dangerously-load-development-channels server:lup`. Claude Code 2.1.304 queues
a channel's `notifications/claude/channel` as a prompt, `<channel source="lup"
wake="…">` around its `content`, with no line saying it came from another
session, at priority `next`: an idle session starts a turn on it, a busy one
takes it after its running call, and it fires `UserPromptSubmit` with the whole
tag as `prompt` either way, as it arrives, its `wake` attribute the push's
token. It registers
a server as a channel only where the server declares
`capabilities.experimental["claude/channel"]`, is named in the flag, connected
on the handshake revisions (lup's server refuses `server/discover`:
`lup.tools.serving`), on first-party authentication, with channels turned on
for the account and not blocked by its organization; one it doesn't drops what
the server pushes, saying nothing to the server (`docs/field-notes.md`,
*Channels*). Taken mid-turn, a channel's message comes with "IMPORTANT: This is
NOT from your user", so lup pushes only to a session it takes for idle, and
tells a busy one at its hooks.

Where a push isn't taken, the session is woken through its own messaging
socket (`woken`), which the launch puts in the room's socket directory: Claude
Code "starts a new turn with the message" when the receiving session is idle,
and closes a connection that hasn't sent a complete line within 30 seconds, so
the host writes the whole line at once (its `cross-session-messaging` docs, read 2026-10-14). The docs give
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
  `additionalProperties: false`" (`docs/platform-differentiation.md` in `lup-legacy`); owed
  live on the version a launch runs (`docs/field-notes.md`, *Piece 2, live*);
- `PreToolUse`'s `additionalContext` is a "String added to Claude's context
  alongside the tool result", `SessionStart`'s one "added to Claude's context at
  the start of the conversation", and a hook's `additionalContext` is "capped at
  10,000 characters", past which Claude Code saves it to a file that "Claude can
  read ... but Claude Code doesn't ask it to";
- `Stop` and `SubagentStop`: `hookSpecificOutput.additionalContext` is
  "Non-error feedback for Claude. The conversation continues so Claude can act on
  it, but unlike `decision: "block"` it is shown in the transcript as hook
  feedback rather than a hook error", with "the same loop protections as
  `decision: "block"`, namely the `stop_hook_active` input and the
  8-consecutive-continuation cap" (read 2026-10-19); "SubagentStop hooks receive
  `stop_hook_active`" as `Stop` hooks do. Measured on 2.1.303
  (`docs/field-notes.md`, *A turn's end told through `additionalContext`*): the
  model reads `Stop hook additional context: <text>` in a system reminder, where
  a block's reason comes as `Stop hook feedback:` and again as `Stop hook
  blocking error from command: "<command>": <reason>`; the turn goes on, and its
  next end carries `stop_hook_active: true`, a subagent's too.

What its judging relies on, from Claude Code's hooks reference
(code.claude.com/docs/en/hooks):
- a hook ending with status 0 and printing nothing has "no decision to report";
  with any status but 0 or 2 it's "a non-blocking error": "You see a `<hook
  name> hook error` notice in the transcript with `Failed with non-blocking
  status code:` and the first line of your hook's stderr", and "The action goes
  ahead"; status 2 alone blocks the call, so the room's hook never ends with it;
- `systemMessage` is a "Warning message shown to the user";
- `PreToolUse`'s `permissionDecisionReason` is "For `"deny"`, shown to Claude.
  For `"allow"` and `"defer"`, written to the debug log only", and its
  `additionalContext` is "String added to Claude's context alongside the tool
  result" (read 2026-10-22): what a write let through is told, its approval
  among it, goes in `additionalContext`;
- `tool_use_id` is in both `PreToolUse` and `PostToolUse`, so a call's start and
  finish match; a call that fails fires `PostToolUseFailure` instead, with the same
  id;
- `PreToolUse` "runs before a tool call executes", `PostToolUse` "after a tool call
  succeeds": a call never finishes before it starts, so the calls running stay
  right when calls run in parallel, whose hooks "run in parallel";
- `PostToolUse`'s and `PostToolUseFailure`'s `additionalContext` is added "next
  to the tool result"; `PostToolUseFailure` "Runs when a tool that started
  executing fails", but "Cancelling a running tool does not fire this hook", and
  `Stop` "Does not run if the stoppage occurred due to a user interrupt" (read
  2026-10-21): a call the operator interrupts stays counted as running until its
  conversation's next turn ends, holding back its session's checkpoints until
  then;
- a `command` hook's timeout defaults to 600 seconds, and "a timed-out command
  ... hook doesn't block the tool call", so a judgement must answer within it;
- a subagent's hooks carry `agent_id`, "Present only when the hook fires inside a
  subagent call", beside its session's `session_id` (seen in #32), and
  `SubagentStop` "Runs when a Claude Code subagent has finished responding";
- a hook's `cwd` is the "Current working directory when the hook is invoked",
  and "Subagent sessions never carry over working directory changes" (the tools
  reference, *Bash tool behavior*): a subagent's hooks report the directory its
  session works in, whatever worktree the subagent works on, as its records do
  (`docs/field-notes.md`, *Judging writes*), so a subagent works where its file
  tools write (`Holding.works`, `policy/worktrees.py`);
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
from typing import TYPE_CHECKING, Annotated, Literal, get_args, override

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup.adapters.claude.layout import ClaudeLayout
from lup.adapters.claude.settings import ClaudeSettings
from lup.sessions.terminal import Cli, Hook
from lup.tools.serving import Notice
from lup.types import JsonObject, Model, Settings
from lup_dev.adapters import Adapter, Pushing
from lup_dev.host.courier import Heard, Spawned, Telling
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
    TurnStarted,
    counted,
    first_warning,
)
from lup_dev.policy.report import judge_failed, sections
from lup_dev.policy.runtime import Runtime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import timedelta

    import httpx

    from lup.sessions.declaration import Declaration
    from lup.sessions.terminal import Event

type Writing = Literal["Edit", "Write"]
"""The file tools whose writes are judged before they land: `PreToolUse.proposal`
reads each."""

type Reading = Literal[
    "Read",  # reads a file, an image, a PDF or a notebook into the model's context
    "Glob",  # lists the paths matching a pattern
    "Grep",  # searches files' contents with ripgrep
    "LSP",  # asks a language server for definitions, references, symbols and types
    "WebFetch",  # fetches a page for a small model to answer about
    "WebSearch",  # searches the web
    "ToolSearch",  # loads the schemas of tools Claude Code deferred
    "ListMcpResourcesTool",  # lists the resources MCP servers expose
    "ReadMcpResourceTool",  # reads one resource of an MCP server
    "AskUserQuestion",  # asks the operator multiple-choice questions, and waits
    "TaskGet",  # reads one task of Claude Code's own task list
    "TaskList",  # reads Claude Code's own task list
    "CronList",  # lists the session's scheduled prompts
    "ListAgents",  # lists the agents `SendMessage` can reach
    "WaitForMcpServers",  # waits for MCP servers still connecting
]
"""The tools that only read or wait, which change no file: the judge reads
neither the start nor the finish of a call to one, so it costs no judgement, and
one that waits (`AskUserQuestion`) holds back no checkpoint. Every tool nobody
listed is judged, a new tool or another MCP server's among them, so a tool
missing here costs a judgement, never a write unjudged; a tool that changes only
Claude Code's own state (`TaskCreate`, `TodoWrite`) is judged too. Named as
Claude Code's tools reference names them (code.claude.com/docs/en/tools-reference,
read 2026-10-21), with what each does beside it. On Linux, `Glob` and `Grep`
are absent by default, and Claude searches with `find` and `grep` through
`Bash`, which is judged."""

type TitledStart = Literal["startup", "resume", "fork"]
"""The starts (`SessionStart`'s `source`) whose `sessionTitle` Claude Code applies
(its `hooks` docs, *SessionStart decision control*): a compaction or a `/clear`
takes none, so lup gives the title at the next prompt instead."""

TOOL_PREFIX = f"mcp__{SERVER}__"
"""What Claude Code names each of lup's tools by in a hook: `mcp__lup__blocked`."""


def judging(tool: str) -> bool:
    """Say whether the judge reads a call to `tool`, at its start and its finish alike: every call but one to lup's own tools, served on the host, and one to a tool that only reads.

    The same answer at both ends, since a call whose start counts it as running
    holds back its session's checkpoints until its finish is read.

    >>> judging("Bash"), judging("mcp__other__write"), judging("Read")
    (True, True, False)
    >>> judging("mcp__lup__ask")
    False
    """
    return not tool.startswith(TOOL_PREFIX) and tool not in get_args(Reading.__value__)


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


class SessionStartAnswer(Output):
    """What `SessionStart` adds to the conversation's context as it starts."""

    hook_event_name: Literal["SessionStart"] = "SessionStart"
    additional_context: str


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


type TurnEnd = Literal["Stop", "SubagentStop"]
"""The hooks at a conversation's turn's end, whose `additionalContext` holds it."""


class StopAnswer(Output):
    """What `Stop` or `SubagentStop` tells the conversation, which holds its turn's end: it goes on, told it as hook feedback, not a hook error."""

    hook_event_name: TurnEnd
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: (
        SessionStartAnswer | PreToolUseAnswer | PostToolUseAnswer | StopAnswer
    )


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
    """At a session's start or a prompt, the title Claude Code gives the
    session, as `/rename` does."""


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


def titled(said: Said, event: str, title: str | None) -> Said:
    """Return `said` giving the session `title` as its title for `event` (`sessionTitle`); as it is where `title` is none."""
    if title is None:
        return said
    given = said.hook_specific_output or Context(hook_event_name=event)
    named = given.model_copy(update={"session_title": title})
    return said.model_copy(update={"hook_specific_output": named})


def held(event: TurnEnd, told: str) -> Specific:
    """Return the answer holding a conversation's turn's end at `event`, telling it `told`."""
    answer = StopAnswer(hook_event_name=event, additional_context=told)
    return Specific(hook_specific_output=answer)


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
    source: str | None = None
    """How it started: `startup`, `resume`, `clear`, `compact` or `fork`."""
    session_title: str | None = None
    """The session's custom title, where one is set (`--name`, `/rename`, a
    hook's `sessionTitle`); not the title Claude Code generates."""

    def heard(self, fits: int) -> Heard:
        """Read the session's start and its title in Claude Code, a start `sessionTitle` applies at (`TitledStart`) taking a new one: the judge reads it."""
        return Heard(
            event="session-started",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=fits,
            title=self.session_title,
            takes_title=self.source in get_args(TitledStart.__value__)
            and not self.agent_id,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items as it starts, and title the session as its launch is named, where the service says to."""
        told = context(said, self.hook_event_name, telling.items)
        return titled(told, self.hook_event_name, telling.title)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Begin the session again in each worktree it holds, and tell its conversation what came due as it starts; the service adds its items and title after (`told`)."""
        reply = SessionStarted(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        ).apply(bench)
        if not reply.context:
            return None
        said = SessionStartAnswer(additional_context=reply.context)
        return Specific(hook_specific_output=said)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


class UserPromptSubmit(Payload):
    """`UserPromptSubmit`: a turn starts on a prompt, the operator's or a channel's, or a prompt arrives in a turn.

    Measured on 2.1.304 (`docs/field-notes.md`, *Channels*): a channel's message
    fires it with the whole `<channel …>` text as its `prompt`, when an idle
    session starts a turn on it, and about 30 ms after the push when a busy one
    is running a call, which takes the message after that call. So it can fire
    while a call of the session's own conversation still runs.
    """

    hook_event_name: Literal["UserPromptSubmit"]
    prompt: str
    session_title: str | None = None
    """The session's custom title, where one is set, as `SessionStart` carries it."""

    def heard(self, fits: int) -> Heard:
        """Read the turn's start, the prompt it starts on and the session's title in Claude Code, a prompt of the session's own conversation taking a new one: the judge reads it."""
        return Heard(
            event="turn-started",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=fits,
            prompt=self.prompt,
            title=self.session_title,
            takes_title=not self.agent_id,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items beside the prompt, and title the session as its launch is named, where the service says to."""
        told = context(said, self.hook_event_name, telling.items)
        return titled(told, self.hook_event_name, telling.title)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Stop counting the session's calls whose results their conversations' records hold: no hook reports the end of a call the operator interrupts, and Claude Code records its result at once.

        A call still running has no result recorded, so a prompt arriving
        mid-turn leaves it counted. A record that lags leaves a call counted
        until its conversation's turn ends, as before.
        """
        transcript = self.transcript_path
        left = [] if transcript is None else counted(bench, self.session_id)
        over = (
            []
            if transcript is None
            else [
                key
                for agent in dict.fromkeys(call.agent for call in left)
                for key in resulted(
                    recorded(transcript, agent),
                    [call.key for call in left if call.agent == agent],
                )
            ]
        )
        TurnStarted(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd, over=over
        ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Let the turn start, and warn the operator once, as a turn's end does: a call left counted is cleared at its conversation's turn's end."""
        warning = judge_failed(failure)
        if not first_warning(bench.services.layout, self.session_id, warning):
            return None
        return OperatorWarning(system_message=warning)

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
        """Read the call's start: the judge reads it unless it's to lup's tools or one that only reads (`judging`)."""
        return Heard(
            event="call-started",
            session=self.session_id,
            agent=self.agent_id or None,
            call=self.tool_use_id,
            tool=self.tool_name,
            served=self.tool_name.startswith(TOOL_PREFIX),
            judged=judging(self.tool_name),
            fits=fits,
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
                told = sections([decision.reason, decision.told])
                answer = PreToolUseAnswer(
                    permission_decision="allow", additional_context=told or None
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
        if self.tool_name not in get_args(Writing.__value__):
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
        """Read the call's finish: the judge reads it where it read the call's start (`judging`)."""
        return Heard(
            event="call-finished",
            session=self.session_id,
            agent=self.agent_id or None,
            call=self.tool_use_id,
            tool=self.tool_name,
            judged=judging(self.tool_name),
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
        """Tell the agent beside the call's result, as when judging fails: the checkpoint judged nothing."""
        told = PostToolUseAnswer(
            hook_event_name=self.hook_event_name,
            additional_context=f"{said}. Tell the operator.",
        )
        return Specific(hook_specific_output=told)


class Stop(Payload):
    """`Stop`: the session's own conversation ends its turn.

    What the turn's end tells the agent holds it, as `additionalContext`, which
    the hooks reference says means "The conversation continues so Claude can act
    on it"; an end that doesn't hold says nothing. Only a judge's failure goes
    to the operator, in `systemMessage`.
    """

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""
    last_assistant_message: str | None = None
    """"Text content of the last assistant message before stopping" (2.1.302's
    hook input schema)."""

    def heard(self, fits: int) -> Heard:
        """Read the turn's end: the judge reads it."""
        return Heard(
            event="turn-ended",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the turn's end on the conversation's items, after anything it tells already."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = TurnEnded(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            after_block=self.stop_hook_active,
        )
        reply = ended.apply(bench)
        return held(self.hook_event_name, reply.block) if reply.block else None

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
    """`SubagentStop`: a subagent's conversation ends its turn, or was stopped.

    The hooks reference: it takes "the same decision control format as Stop
    hooks, including `hookSpecificOutput.additionalContext` with `hookEventName`
    set to `"SubagentStop"`, for non-error feedback that keeps the subagent
    running".

    Read in the 2.1.308 binary (`docs/field-notes.md`, *A subagent's end*): the
    input carries `last_assistant_message`, as `Stop`'s does, when the
    subagent's turn ends; and a subagent whose run broke off, stopped by the
    operator or its parent or by an exception, runs `SubagentStop` once more as
    it's cleaned up ("SubagentStop on interrupted query"), within 5 seconds and
    with no message, so one without a message is taken as stopped: a turn
    ending with no text is rare (2 of 2,507 `Stop`s, *The end after a held
    end*), and taken so its end is held for nothing. One whose turn ends
    on an error from the model's API runs `StopFailure` alone, which lup
    doesn't hook: its parent isn't told.
    """

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool = False
    """Whether the subagent goes on because a `SubagentStop` hook blocked it already."""
    last_assistant_message: str | None = None
    """Its last message of the turn; absent where its run broke off."""

    def heard(self, fits: int) -> Heard:
        """Read a subagent's turn's end, or its stop where it carries no message: the judge reads it."""
        return Heard(
            event="conversation-ended",
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
            stopped=self.last_assistant_message is None,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the subagent's turn's end on its items, after anything it tells already."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd
        )
        reply = ended.apply(bench)
        return held(self.hook_event_name, reply.block) if reply.block else None

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


FORK = "fork"
"""The type of a subagent spawned with the conversation so far: its record's
`agentType` (measured on 2.1.303, `docs/field-notes.md`, *Subagents' records*).
A fork "sees the same system prompt, tools, model, and message history as the
main session" (the `sub-agents` docs, *Fork the current conversation*), so it
reads the session's guidance, which the system prompt carries."""


def spawned(raw: str) -> Spawned | None:
    """Return how the subagent a Claude Code hook fires for was spawned, from its record beside the session's transcript; none for the session's own conversation.

    A subagent whose record isn't there is said by its type alone; one with
    neither is Claude Code's own (`Spawned.internal`): its prompt suggestions
    and `/btw` are heard only at `SubagentStop`, with no type and no record,
    174 of them in one of lup's launches (`docs/field-notes.md`, *A subagent's
    end*). Only a fork reads the session's guidance: every other subagent's
    system prompt is "the agent's own prompt plus environment details that
    Claude Code appends, not the Claude Code system prompt" (the `sub-agents`
    docs, *What loads at startup*), which lup's guidance is appended to.

    Claude Code hands every subagent's last message to its parent itself
    (`Spawned.handed`): the result of a foreground `Agent` call, or a
    background one's task notification, its `<result>` whole, beside the
    parent's next call's result or starting its turn (`docs/field-notes.md`,
    *A subagent's end*).
    """
    payload = Subagented.model_validate_json(raw)
    if not payload.agent_id:
        return None
    kind = payload.agent_type or None
    folder = (
        None
        if payload.transcript_path is None
        else payload.transcript_path.with_suffix("") / "subagents"
    )
    record = None if folder is None else folder / f"agent-{payload.agent_id}.meta.json"
    if record is None or not record.is_file():
        return Spawned(
            kind=kind, guided=kind == FORK, internal=kind is None, handed=True
        )
    kept = SubagentRecord.model_validate_json(record.read_text())
    kind = kept.agent_type or kind
    return Spawned(
        name=kept.name,
        parent=kept.parent_agent_id,
        kind=kind,
        guided=kind == FORK,
        handed=True,
    )


type Received = Annotated[
    SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | Stop | SubagentStop,
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


class ChannelMessage(Model):
    """What a channel's notification carries (`channels-reference`, *Notification format*): its text, and the attributes its tag shows."""

    content: str
    meta: dict[str, str]
    """Each an attribute of the `<channel>` tag; a key that isn't letters,
    digits and underscores is dropped."""


CHANNEL = "claude/channel"
"""The experimental capability a server declares to be a channel."""


def pushed(text: str, token: str) -> Notice:
    """Return the notice that starts a turn of an idle Claude Code session with `text`, a channel's message whose tag carries `token`.

    >>> pushed("Hi.", "t1").params
    {'content': 'Hi.', 'meta': {'wake': 't1'}}
    """
    message = ChannelMessage(content=text, meta={"wake": token})
    return Notice(method=f"notifications/{CHANNEL}", params=message.model_dump())


def hooks(command: list[str], timeout: timedelta) -> list[Hook]:
    """Return the hooks a launched Claude Code session runs `command` at: the events the host service hears.

    `SessionStart`; `UserPromptSubmit`, each turn's start, a channel's message
    among them, which clears the calls the session's records show over (one
    interrupted); `PreToolUse` on every call, the file tools' writes judged
    before they land, every call told what waits for its conversation, and a
    call to lup's tools stamped with its caller; `PostToolUse` and
    `PostToolUseFailure` on every call, the checkpoint after it; `Stop` and
    `SubagentStop`, each conversation's turn's end, which clears the calls it
    left that no finish reported and judges what the turn left. Each waits up to `timeout`, which a hold's wait for the operator
    needs, at a call's start, its finish or a turn's end.
    """
    events: list[Event] = [
        "session-started",
        "turn-started",
        "call-started",
        "call-finished",
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


class ToolResult(Model, extra="ignore"):
    """A call's result, by the id of the call it answers."""

    type: Literal["tool_result"]
    tool_use_id: str


class OtherBlock(Model, extra="ignore"):
    """Any other part of a message: thinking, an image."""

    type: str


type Block = Annotated[
    TextBlock | ToolUse | ToolResult | OtherBlock, Field(union_mode="left_to_right")
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


def recorded(transcript: Path, agent: str) -> Path:
    """Return where Claude Code records conversation `agent` of the session whose transcript is `transcript`: the transcript for the session's own, `<session>/subagents/agent-<id>.jsonl` beside it for a subagent's (`docs/field-notes.md`, *Subagents' records*)."""
    if not agent:
        return transcript
    return transcript.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"


def resulted(record: Path, calls: list[str]) -> list[str]:
    """Return those of `calls` whose result `record` holds; none where there's no record.

    Claude Code records a result for every call, an interrupted one's or one the
    operator refused at its prompt among them ("The user doesn't want to proceed
    with this tool use"), though no hook reports its end (`docs/field-notes.md`,
    *Judging writes*).
    """
    if not calls or not record.is_file():
        return []
    found = [
        block.tool_use_id
        for line in parsed(record)
        if isinstance(line, UserLine) and not isinstance(line.message.content, str)
        for block in line.message.content
        if isinstance(block, ToolResult)
    ]
    return [call for call in calls if call in found]


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
        spawned=spawned,
        woken=woken,
        pushing=Pushing(capabilities={CHANNEL: {}}, notice=pushed),
        hooks=hooks,
        channel=ClaudeChannel(),
        agent=agent,
        records=ClaudeRecords(directory=ClaudeLayout.of(ClaudeSettings()).directory),
        reader=ClaudeTranscripts(),
    )
