"""Claude Code's hooks, its payloads in, lup's events, its outputs out; and its release channel.

| Claude Code hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `UserPromptSubmit` | `TurnStarted` |
| `PreToolUse` | `CallStarted`; for `Edit` and `Write`, judged before it lands first; for `Agent` asking `isolation: "worktree"`, lup's own isolation |
| `WorktreeCreate` | `WorktreeAsked`: lup makes the worktree |
| `PostToolUse`, `PostToolUseFailure` | `CallFinished`: the checkpoint |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |
| `StopFailure` | a subagent's: `ConversationEnded`; the session's: none |

A file tool's write that asks is held in `PreToolUse` for the operator's answer
in their inbox, then let through (`allow`), told beside the call that lup held
it and they approved it, with their comment, or denied (`deny`) with it: Claude
Code's own prompt isn't used, so a hold is answered the same way on every
runtime. The agent hears what deferred work came due as `additionalContext` of
`SessionStart`, a checkpoint's report as `additionalContext` beside the call's
result, and what a turn's end tells them, the session's or a subagent's, as
`additionalContext` of `Stop` or `SubagentStop`, which holds the turn: it goes
on, the text shown as hook feedback rather than a hook error.
`stop_hook_active` says a turn's end follows such a hold. An end that doesn't
hold tells nothing: `systemMessage` would reach the operator, not the agent.
When judging itself fails at a turn's end, the turn ends, and the operator is
warned once in `systemMessage`.

A worktree Claude Code would make, for a session entering one
(`EnterWorktree`), lup makes instead (`WorktreeCreate`; `docs/judging-writes.md`,
*A worktree the runtime asks for*): Claude Code's own starts from the
repository's `HEAD`, a bare repository's default branch however far the work is
from it, and a worker switching to their branch there had the judge read the
switch as their writes. A subagent asked to work apart (`isolation: "worktree"`)
lup isolates itself, where Claude Code's isolation would guard their shell,
refusing git aimed at another worktree and every compound command (`PreToolUse.spawn`;
*A subagent lup isolates*): the `Agent` call goes on without `isolation`, lup
makes the subagent's worktree and tells them so in their prompt, their shell's
commands start there (`PreToolUse.commanded`), and a write of their file tools
in the worktree Claude Code names as their working directory, another
conversation's, is refused (`apart`, `policy/checkpoint.py`). A subagent's hooks
carry nothing linking them to their spawn but their record, written before their first
call (`spawned_by`), and a spawn's result, which names them (`PostToolUse`).

In a launched room (`docs/host.md`, *The one hook*), Claude Code runs the room's
hook on `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and
`PostToolUseFailure` for every call, `WorktreeCreate`, `Stop`, `SubagentStop`
and `StopFailure` (`hooks`), so the host service hears each conversation's
start, each turn's start and the prompt it starts on, their calls' starts and
finishes, each worktree they ask for, and their turn's ends, one failing on an
error from the model's API among them
(`docs/inbox.md`, *How an agent is told*). The judge reads every one of them
(`heard`) but the calls `judging` leaves out: those to lup's own tools, and to a
tool on the list of those that only read (`Reading`). So every
write is judged: a file tool's before it lands, and anything else, a command's,
a script's, a notebook's, at the checkpoint after its call, which holds what
asks there until the operator answers, put back on a decline
(`docs/judging-writes.md`, *After a call: the checkpoint*). A turn's end clears
the calls its conversation left that no finish reported, runs a last checkpoint,
and holds the session's turn while the files it touched have findings
(`docs/judging-writes.md`, *The turn's end*). A turn that failed holds nothing,
since Claude Code reads none of `StopFailure`'s answer, and the judge reads a
subagent's alone (`StopFailure`). Every other hook the service
answers itself, without starting the judge, as no decision. Where the launch's
judge can't answer a hook, the host service answers it through `unanswered`: a
file tool's write is denied, naming why, since a write let through unjudged
would land unseen; at a call's finish the agent is told beside its result, as
when judging fails; any other hook warns the operator in `systemMessage`, and
the call goes on. Where the room's hook can't reach the service, it ends with
status 1 and says why on standard error: a non-blocking error, which Claude Code
shows, and the call goes on. Where it reached the service and the connection
was lost before an answer, as when the service restarts while a hold waits, it
ends with status 2 at a call's start, its finish and a turn's end, and 1 at a
session's start and a turn's start, saying why (`lost`, `launch/session.py`).
The hooks reference's table of status 2 (read 2026-10-22): `PreToolUse` "Blocks
the tool call"; `PostToolUse` and `PostToolUseFailure` "Shows stderr to Claude";
`Stop` "Prevents Claude from stopping, continues the conversation", and
`SubagentStop` "Prevents the subagent from stopping", each on the standard
error, unless it "says a file is missing", which lup's line never does; and
`UserPromptSubmit` "Blocks the prompt, so it never reaches Claude", which a
turn's start mustn't do to the operator's prompt; `StopFailure`'s "Output and
exit code are ignored", so its status 2 is no one's. So the service answers every
hook with something, `{}` where it decides nothing: Claude Code reads output
starting with `{` as JSON and checks it against its schema, every field of
which is optional (2.1.308, `cte`), "Success. The fields apply", none here.

The service adds to each answer through `told`: a call to lup's tools
(`mcp__lup__<tool>`, `TOOL_PREFIX`) is rewritten to carry `caller`, lup's id for
the conversation calling, as `updatedInput` with no decision, so the call goes
through the session's own permission mode as it would have; and what the
conversation is told goes in as `additionalContext`, beside a call or a session's
start, or holding a turn's end. What a hook
tells whole is 10,000 bytes (`Claude.fits`): Claude Code caps a hook's
`additionalContext` at 10,000 characters, which a text's UTF-8 bytes never
undercount; an item past it is announced instead, and the judge's report is
fitted to it (`policy/report.py`, `fitted`). A turn's end following a
hold, the session's or a subagent's, carries `stop_hook_active`, so the next
end is let through.

**The session's title in Claude Code,** the one `/rename` sets, is heard and
given at their start and at each prompt of their own conversation (`docs/launch.md`,
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
takes it after their running call, and it fires `UserPromptSubmit` with the whole
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
tells a busy one at their hooks.

Where a push isn't taken, the session is woken through their own messaging
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
  ahead"; status 2 alone blocks the call, so the room's hook ends with it only
  where its connection to the host service was lost before an answer;
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
  subagent call", beside their session's `session_id` (seen in #32), and
  `SubagentStop` "Runs when a Claude Code subagent has finished responding";
- a hook's `cwd` is the "Current working directory when the hook is invoked",
  and "Subagent sessions never carry over working directory changes" (the tools
  reference, *Bash tool behavior*): a subagent's hooks report the directory their
  session works in, whatever worktree the subagent works on, as their records do
  (`docs/field-notes.md`, *Judging writes*), so a subagent works where their file
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

import io
import os
import shlex
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, get_args, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup import events
from lup.adapters.claude.layout import ClaudeLayout
from lup.adapters.claude.settings import ClaudeSettings
from lup.adapters.claude.terminal import own_settings
from lup.adapters.claude.windows import catalogued, reach
from lup.rooms.homes import inside, lines, opened, plain
from lup.sessions.terminal import Cli, Hook, TerminalError
from lup.tools.serving import Notice
from lup.types import JsonObject, Model, MutableModel, Settings
from lup_dev.adapters import Adapter, Pushing
from lup_dev.host import written
from lup_dev.host.courier import Failure, Heard, Spawned, Telling
from lup_dev.host.homes import Found, home_of, served, translated
from lup_dev.host.records import (
    Call,
    Called,
    Entry,
    Home,
    Queued,
    Queues,
    Queuing,
    Reader,
    Record,
    Records,
    Status,
    Task,
    Transcript,
    Usage,
    first,
    gist,
    head,
    homes,
    reached,
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
from lup_dev.layout import HomesLayout, HostLayout, Layout
from lup_dev.policy.before import Decision, Overwrite, Replacement, before
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    WorktreeAsked,
    WorktreeRefusedError,
    apart,
    counted,
    first_warning,
)
from lup_dev.policy.report import judge_failed, sections
from lup_dev.policy.runtime import Runtime
from lup_dev.policy.worktrees import Apart, Making
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from datetime import timedelta

    import httpx

    from lup.events import SessionEvent
    from lup.sessions.declaration import Declaration
    from lup_dev.host.protocol import Register

type Writing = Literal["Edit", "Write"]
"""The file tools whose writes are judged before they land: `PreToolUse.proposal`
reads each."""

type Spawning = Literal["Agent", "Task"]
"""The tool that spawns a subagent, by both its names: `Agent`, as Claude Code's
hooks name it, and `Task`, as 2.1.310's own list of its tools does (its
`init` message)."""

type Commanding = Literal["Bash", "Monitor"]
"""The tools that run a shell command, which starts in the session's working
directory whoever calls it: one of a conversation working apart is rewritten to
start in their worktree. Measured on 2.1.310 (`docs/field-notes.md`, *lup's own
isolation*): each takes the command as `command`."""

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

type FreshStart = Literal["startup", "clear"]
"""The starts (`SessionStart`'s `source`) whose conversation begins empty: a
session started, or cleared with `/clear`, which gives them an id of their own; a
resume, a compaction or a fork carries a conversation on (`Heard.fresh`)."""

type ForgettingStart = Literal["compact", "clear"]
"""The starts (`SessionStart`'s `source`) after which the conversation holds
none of what it was told: a compaction summarizes it, and `/clear` empties it,
so the judge tells again the findings that still stand
(`SessionStarted.forgotten`)."""

type TitledStart = Literal["startup", "resume", "fork"]
"""The starts (`SessionStart`'s `source`) whose `sessionTitle` Claude Code applies
(its `hooks` docs, *SessionStart decision control*): a compaction or a `/clear`
takes none, so lup gives the title at the next prompt instead."""

# lup: defer(issue=52, why="Claude Code's spelling of a tool's name in a hook, a module constant until a `Spellings` each adapter implements gives it its home")
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

    @override
    def fits(self) -> int:
        """Return 10,000: Claude Code's cap on a hook's `additionalContext`, in characters, which a text's UTF-8 bytes never undercount (see the module's docstring)."""
        return 10_000

    @override
    def settings(self) -> PurePosixPath:
        """Return `.claude`: the project's settings, hooks, commands and subagents (code.claude.com/docs/en/settings)."""
        return PurePosixPath(".claude")


class Output(Model, alias_generator=to_camel, populate_by_name=True):
    """What a hook prints for Claude Code, its fields in camel case."""

    def printed(self) -> str:
        """Return it as the hook prints it: JSON, which Claude Code reads every hook's answer as but `WorktreeCreate`'s."""
        return self.model_dump_json(by_alias=True, exclude_none=True)


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
    updated_input: JsonObject | None = None
    """The call's input in place of its own, whole: with no decision, the call
    goes through the session's own permission mode."""


class PostToolUseAnswer(Output):
    """What `PostToolUse` adds beside the call's result."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    additional_context: str


type TurnEnd = Literal["Stop", "SubagentStop"]
"""The hooks at a conversation's turn's end, whose `additionalContext` holds it."""


class StopAnswer(Output):
    """What `Stop` or `SubagentStop` tells the conversation, which holds their turn's end: they go on, told it as hook feedback, not a hook error."""

    hook_event_name: TurnEnd
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: (
        SessionStartAnswer | PreToolUseAnswer | PostToolUseAnswer | StopAnswer
    )


class Placed(Output):
    """What `WorktreeCreate` prints, for the room's hook to read: the worktree lup makes, a field a line (`Making.lines`), or why it makes none, which never starts with `/`."""

    made: Making | None = None
    refused: str = "lup made no worktree"

    @override
    def printed(self) -> str:
        return f"{self.refused}\n" if self.made is None else self.made.lines()


class Isolating(Output):
    """What `PreToolUse` prints for a call spawning a conversation lup isolates in a worktree it makes: the worktree, a field a line (`Making.lines`), which the room's hook makes before printing the rest, the call's answer (`launch/worktree.sh`)."""

    made: Making
    answer: Specific

    @override
    def printed(self) -> str:
        return f"{self.made.lines()}{self.answer.printed()}"


def making(answer: str) -> str:
    r"""Return what of a hook's `answer` names a worktree for the room's hook to make (`Making.lines`), its first four lines, or nothing where it names none: JSON starts with `{`, and a refusal with neither.

    >>> making("/r.git/tree/w\n/r.git/tree/dev\nw\nc0\n{}")
    '/r.git/tree/w\n/r.git/tree/dev\nw\nc0\n'
    >>> making("{}")
    ''
    """
    if not answer.startswith("/"):
        return ""
    lines = io.StringIO(answer)
    return "".join(lines.readline() for _ in Making.model_fields)


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
    """Return the answer holding a conversation's turn's end at `event`, telling them `told`."""
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
    """The session's transcript: their subagents' records are beside it."""

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
    """How the session started: `startup`, `resume`, `clear`, `compact` or `fork`."""
    session_title: str | None = None
    """The session's custom title, where one is set (`--name`, `/rename`, a
    hook's `sessionTitle`); not the title Claude Code generates."""

    def heard(self, fits: int) -> Heard:
        """Read the session's start and their title in Claude Code, a start `sessionTitle` applies at (`TitledStart`) taking a new one, and whether their conversation begins empty (`FreshStart`): the judge reads it."""
        return Heard(
            event=events.SessionStarted(),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=fits,
            title=self.session_title,
            fresh=self.source in get_args(FreshStart.__value__) and not self.agent_id,
            takes_title=self.source in get_args(TitledStart.__value__)
            and not self.agent_id,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation their items as they start, and title the session as their launch is named, where the service says to."""
        told = context(said, self.hook_event_name, telling.items)
        return titled(told, self.hook_event_name, telling.title)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Begin the session again in each worktree they hold, and tell their conversation what came due as they start; the service adds their items and title after (`told`)."""
        reply = SessionStarted(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            spawned_by=spawned_by(self, bench.launch),
            forgotten=self.source in get_args(ForgettingStart.__value__),
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
            event=events.TurnStarted(),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=fits,
            prompt=self.prompt,
            title=self.session_title,
            takes_title=not self.agent_id,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation their items beside the prompt, and title the session as their launch is named, where the service says to."""
        told = context(said, self.hook_event_name, telling.items)
        return titled(told, self.hook_event_name, telling.title)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Stop counting the session's calls whose results their conversations' records hold: no hook reports the end of a call the operator interrupts, and Claude Code records its result at once.

        A call still running has no result recorded, so a prompt arriving
        mid-turn leaves it counted. A record that lags leaves a call counted
        until its conversation's turn ends, as before. The records are read in
        the home the launch registered, where the payload names them under the
        own runtime directory of the launch whose room ran the hook, and
        nowhere else.
        """
        transcript = (
            None
            if self.transcript_path is None
            else translated(bench.launch, self.transcript_path)
        )
        left = [] if transcript is None else counted(bench, self.session_id)
        over = (
            []
            if transcript is None
            else [
                key
                for agent in dict.fromkeys(call.agent for call in left)
                for key in resulted(
                    recorded(transcript.record, agent),
                    [call.key for call in left if call.agent == agent],
                    transcript.root,
                )
            ]
        )
        TurnStarted(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            spawned_by=spawned_by(self, bench.launch),
            over=over,
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


class Written(Model, extra="ignore"):
    """A file tool's input, as far as where it writes: `Edit`'s and `Write`'s `file_path`, `NotebookEdit`'s `notebook_path`."""

    file_path: Path | None = None
    notebook_path: Path | None = None


class Spawn(Model, extra="allow"):
    """The `Agent` tool's input, as far as lup reads it, every other field kept as given."""

    description: str = ""
    """What the subagent is for, in a few words."""
    prompt: str = ""
    isolation: str | None = None
    """`worktree` to have them work apart, in a worktree of their own."""


class Command(Model, extra="allow"):
    """`Bash`'s or `Monitor`'s input, as far as lup reads it, every other field kept as given."""

    command: str


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
            event=events.CallStarted(call=self.tool_use_id, tool=self.tool_name),
            session=self.session_id,
            agent=self.agent_id or None,
            served=self.tool_name.startswith(TOOL_PREFIX),
            judged=judging(self.tool_name),
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation their items beside the call, and stamp a call to lup's tools with its caller.

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

    def writes(self) -> Path | None:
        """Return where a file tool's call writes; none for other calls."""
        if self.tool_name not in ["Edit", "Write", "NotebookEdit"]:
            return None
        written = Written.model_validate(self.tool_input)
        path = written.file_path or written.notebook_path
        return None if path is None else self.cwd / path

    def started(self, launch: Register | None) -> CallStarted:
        """Return the event of this call starting, the spawn of its subagent read in the home `launch`, the launch whose room ran the hook, registered.

        A call running a subagent (`Agent`) isn't counted: their own calls are.
        One asking `isolation: "worktree"` asks for its conversation to work
        apart, in a worktree named after its `description`.
        """
        spawns = self.tool_name in get_args(Spawning.__value__)
        spawn = Spawn.model_validate(self.tool_input) if spawns else Spawn()
        return CallStarted(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            spawned_by=spawned_by(self, launch),
            call=self.tool_use_id,
            tool=self.tool_name,
            spawns=spawns,
            apart=spawn.isolation == "worktree",
            purpose=spawn.description,
        )

    def spawn(self, bench: Bench, started: CallStarted) -> Output | None:
        """Give the conversation this call spawns the worktree they work apart in, where they do, in lup's place: Claude Code's own isolation is dropped, and the conversation is told where they work before their first move (`docs/judging-writes.md`, *A subagent lup isolates*).

        Measured on 2.1.310 (`docs/field-notes.md`, *lup's own isolation*): an
        `updatedInput` without `isolation`, with no decision, has Claude Code
        make no worktree and run no `WorktreeCreate`, and its guard on an
        isolated agent's shell, which refuses git aimed at another worktree and
        every compound command, applies nowhere; the subagent's first message
        is the prompt given. A worktree lup makes is printed before the answer
        for the room's hook to make (`Isolating`). Where lup can't make it, the
        call is refused, saying why.
        """
        try:
            reply = started.apply(bench)
        except WorktreeRefusedError as refused:
            said = (
                "lup made no worktree for the subagent this call spawns, so it "
                f"didn't run: {refused}"
            )
            answer = PreToolUseAnswer(
                permission_decision="deny", permission_decision_reason=said
            )
            return Specific(hook_specific_output=answer)
        if reply.given is None:
            return None
        spawn = Spawn.model_validate(self.tool_input)
        told = spawn.model_copy(
            update={"prompt": f"{reply.given.told()}\n\n{spawn.prompt}"}
        )
        updated = told.model_dump(exclude={"isolation": True}, exclude_unset=True)
        answer = Specific(hook_specific_output=PreToolUseAnswer(updated_input=updated))
        return (
            answer if reply.made is None else Isolating(made=reply.made, answer=answer)
        )

    def commanded(self, away: Apart | None) -> Output | None:
        """Return this call rewritten to start in the worktree its conversation works apart in, where it runs a shell command (`Commanding`); none otherwise.

        Measured on 2.1.310 (`docs/field-notes.md`, *lup's own isolation*): a
        subagent's shell starts in the session's working directory at each
        call, and a command rewritten as `cd -- <root> || exit 1`, a newline,
        then the command, runs whole in that one shell, compound commands,
        redirects, pipes, heredocs and a background command among them; the
        transcript keeps the model's own, and they're told only the output.
        """
        if away is None or self.tool_name not in get_args(Commanding.__value__):
            return None
        command = Command.model_validate(self.tool_input)
        start = f"cd -- {shlex.quote(str(away.root))} || exit 1"
        updated = command.model_copy(
            update={"command": f"{start}\n{command.command}"}
        ).model_dump(exclude_unset=True)
        return Specific(hook_specific_output=PreToolUseAnswer(updated_input=updated))

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Judge a file tool's write before it lands, and count the call as running; a write held and declined never runs, so it isn't counted.

        A call spawning a subagent gives them the worktree they work apart in,
        where they do (`spawn`). A conversation working apart has their shell's
        commands start in their worktree (`commanded`), and a write of theirs in the
        worktree Claude Code names as their working directory, another
        conversation's, refused, saying the path in their own (`apart`).
        """
        started = self.started(bench.launch)
        if started.spawns:
            return self.spawn(bench, started)
        away = apart(bench, started, self.writes())
        if away is not None and away.refused is not None:
            refused = PreToolUseAnswer(
                permission_decision="deny", permission_decision_reason=away.refused
            )
            return Specific(hook_specific_output=refused)
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
                started.apply(bench)
                return self.commanded(away)
            case "deny":
                answer = PreToolUseAnswer(
                    permission_decision="deny",
                    permission_decision_reason=decision.reason,
                )
                return Specific(hook_specific_output=answer)
            case "allow":
                started.apply(bench)
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


class AgentResult(Model, extra="ignore", alias_generator=to_camel):
    """An `Agent` call's result, as far as the subagent it names: `agentId`, at their launch in the background as at their end (measured on 2.1.310, `docs/field-notes.md`, *lup's own isolation*)."""

    agent_id: str | None = None


class PostToolUse(Payload):
    """`PostToolUse` or `PostToolUseFailure`: a tool call finished, or failed."""

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    tool_name: str
    tool_use_id: str
    tool_response: JsonValue = None
    """What the call answered; `PostToolUseFailure` carries none."""

    def spawned(self) -> str | None:
        """Return the subagent a call spawning one names in its result; none for other calls, or one that failed."""
        if self.tool_name not in get_args(Spawning.__value__) or not isinstance(
            self.tool_response, dict
        ):
            return None
        return AgentResult.model_validate(self.tool_response).agent_id

    def heard(self, fits: int) -> Heard:
        """Read the call's finish: the judge reads it where it read the call's start (`judging`)."""
        return Heard(
            event=events.CallFinished(call=self.tool_use_id, tool=self.tool_name),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=judging(self.tool_name),
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation their items beside the call's result."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        finished = CallFinished(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            spawned_by=spawned_by(self, bench.launch),
            call=self.tool_use_id,
            tool=self.tool_name,
            spawns=self.tool_name in get_args(Spawning.__value__),
            spawned=self.spawned(),
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
    """`Stop`: the session's own conversation ends their turn.

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
            event=events.TurnEnded(),
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
            spawned_by=spawned_by(self, bench.launch),
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
    """`SubagentStop`: a subagent's conversation ends their turn, or was stopped.

    The hooks reference: it takes "the same decision control format as Stop
    hooks, including `hookSpecificOutput.additionalContext` with `hookEventName`
    set to `"SubagentStop"`, for non-error feedback that keeps the subagent
    running".

    Read in the 2.1.308 and 2.1.309 binaries (`docs/field-notes.md`, *A
    subagent's end*): the input carries `last_assistant_message`, as `Stop`'s
    does, when the subagent's turn ends; and a subagent whose run broke off,
    stopped by the operator or their parent or by an exception, runs
    `SubagentStop` once more as Claude Code cleans up after them ("SubagentStop on interrupted
    query"), within 5 seconds and with no message, so one without a message is
    taken as stopped: a turn ending with no text is rare (2 of 2,507 `Stop`s,
    *The end after a held end*), and taken so their end is held for nothing, and
    their time at work ends whatever it would tell (`ConversationEnded.final`),
    since nothing reads that hook's answer. One whose turn ends on an error
    from the model's API runs `StopFailure` instead (`StopFailure`).
    """

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool = False
    """Whether the subagent goes on because a `SubagentStop` hook held their turn's end already."""
    last_assistant_message: str | None = None
    """Their last message of the turn; absent where their run broke off."""

    @property
    def stopped(self) -> bool:
        """Say whether the subagent was stopped before they ended their turn: their run broke off, so the hook carries no message."""
        return self.last_assistant_message is None

    def heard(self, fits: int) -> Heard:
        """Read a subagent's turn's end, or their stop where it carries no message: the judge reads it."""
        return Heard(
            event=events.ConversationEnded(),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
            stopped=self.stopped,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the subagent's turn's end on their items, after anything it tells already."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id,
            agent=self.agent_id,
            cwd=self.cwd,
            spawned_by=spawned_by(self, bench.launch),
            final=self.stopped,
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


class StopFailure(Payload):
    """`StopFailure`: a conversation's turn ends on an error from the model's API, a subagent's or the session's own, in place of `SubagentStop` or `Stop`.

    The hooks reference (read 2026-10-23): it "Runs instead of Stop when the
    turn ends due to an API error"; "Claude Code ignores the hook's output and
    exit code, apart from `terminalSequence`", so nothing it's told holds it,
    nor could; its `error` is the error's kind, "`rate_limit`, `overloaded`,
    `authentication_failed`, `oauth_org_not_allowed`, `account_on_hold`,
    `billing_error`, `invalid_request`, `model_not_found`, `server_error`,
    `max_output_tokens`, `cloud_credential_error`, or `unknown`", and its
    `last_assistant_message` "the API error string itself", not the agent's
    words. Measured on 2.1.309 (`docs/field-notes.md`, *A subagent's end*): a
    subagent's carries their `agent_id` and `agent_type` and runs no
    `SubagentStop` after; the session's carries neither and runs no `Stop`.

    A subagent's is their conversation's end, failed: their parent is told the
    error's kind, and the judge ends it as at `SubagentStop`, their time at work
    over whatever it would tell (`ConversationEnded.final`). The session's is
    their turn's end, so the service knows they're idle, and is put before the
    operator in lup's words, the error's kind and Claude Code's text for it,
    rather than as the agent's last message, which it isn't; the judge doesn't
    read it, since what it told would reach no one, and the next turn's end
    judges what this one left.
    """

    hook_event_name: Literal["StopFailure"]
    error: str = "unknown"
    """The error's kind, which the hook's matcher filters on; Claude Code calls
    one it has no kind for `unknown`."""
    last_assistant_message: str | None = None
    """The error as the conversation shows it, `API Error: …`; absent where
    Claude Code renders it empty."""

    def heard(self, fits: int) -> Heard:
        """Read a subagent's end, or the session's turn's end, failed: the judge reads a subagent's alone."""
        return Heard(
            event=events.ConversationEnded() if self.agent_id else events.TurnEnded(),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=bool(self.agent_id),
            fits=fits,
            failed=Failure(kind=self.error, said=self.last_assistant_message),
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Add nothing: Claude Code reads none of this hook's answer."""
        del telling
        return said

    @override
    def answer(self, bench: Bench) -> Output | None:
        """End the subagent's conversation as `SubagentStop` does, whatever their end would tell; for the session's own, nothing, which their next turn's end judges."""
        if self.agent_id:
            ConversationEnded(
                session=self.session_id,
                agent=self.agent_id,
                cwd=self.cwd,
                spawned_by=spawned_by(self, bench.launch),
                final=True,
            ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Raise `failure`: no warning this hook answers is shown, so the repository's process and the host service say it in their output instead."""
        raise failure

    @override
    def unanswered(self, said: str) -> Output:
        """Warn the operator, which Claude Code drops as it drops every answer here: the host service's output has said it already."""
        return OperatorWarning(system_message=said)


class WorktreeCreate(Payload):
    """`WorktreeCreate`: Claude Code would make a worktree, for a subagent it isolates or a session entering one; lup makes it (`WorktreeAsked`), and the answer says where, for the room's hook to make it there.

    From the hooks reference (read 2026-10-25): it runs where "a subagent uses
    `isolation: "worktree"`", among other cases, and "replaces default git
    behavior"; its input is the common fields and `name`, "a slug identifier
    for the new worktree"; a command hook prints the worktree's path as "the
    last non-empty line of stdout" and "can't return JSON", and "If the hook
    fails or produces no path, worktree creation fails". Claude Code refuses a
    path with `.` or `..` segments, or through a symlink below the repository
    root, and keeps the worktree when the subagent ends, running no
    `WorktreeRemove` and deleting no branch: `land` removes both once the
    branch lands (`docs/judging-writes.md`, *Landing a branch*).

    Measured on 2.1.310 (`docs/field-notes.md`, *A worktree for an isolated
    subagent*): a subagent's `name` is `agent-<their agent_id>`; the input carries
    the session's `session_id` and `transcript_path`, a `prompt_id`, and as
    `cwd` the spawning conversation's working directory, never an `agent_id`,
    so it names the session alone; the subagent runs in the directory printed,
    each hook of their own carrying it as `cwd`, so their first call reaches it.
    """

    hook_event_name: Literal["WorktreeCreate"]
    name: str
    """Claude Code's name for the worktree, which its branch takes."""

    def heard(self, fits: int) -> Heard:
        """Read a worktree asked for, of the session as a whole: the judge reads it, and its answer, a path, tells the model nothing."""
        del fits
        return Heard(
            event=events.WorktreeAsked(name=self.name),
            session=self.session_id,
            agent=self.agent_id or None,
            judged=True,
            fits=0,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Add nothing: the answer is where the worktree is, which carries nothing else."""
        del telling
        return said

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Have lup make the worktree from the commit the asking conversation's worktree is at, and say where."""
        reply = WorktreeAsked(
            session=self.session_id, agent=self.agent_id, cwd=self.cwd, name=self.name
        ).apply(bench)
        return Placed(made=reply.made)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Fail the making, saying why: lup refused it, or judging failed."""
        why = (
            str(failure)
            if isinstance(failure, WorktreeRefusedError)
            else f"lup's judge failed: {failure!r}"
        )
        return Placed(refused=f"lup made no worktree: {why}")

    @override
    def unanswered(self, said: str) -> Output:
        """Fail the making, saying why: with the hook configured, Claude Code makes no worktree of its own in its place."""
        return Placed(refused=f"{said}, so lup made no worktree")


class SubagentRecord(Model, extra="ignore", alias_generator=to_camel):
    """What Claude Code records of a subagent beside the session's transcript, `<session>/subagents/agent-<id>.meta.json`.

    Undocumented, read as measured on 2.1.301 and 2.1.302
    (`docs/field-notes.md`, *Subagents' records*): the subagent's type, the
    name their parent gave them, and the subagent who spawned them, where one did;
    and, measured on 2.1.310 (*lup's own isolation*), the id of the `Agent`
    call that spawned them, written after `SubagentStart` and before their first
    call.
    """

    agent_type: str | None = None
    name: str | None = None
    parent_agent_id: str | None = None
    tool_use_id: str | None = None


class Subagented(Model, extra="ignore"):
    """Any hook's payload, as far as finding a subagent's record reads it."""

    session_id: str
    agent_id: str = ""
    agent_type: str = ""
    transcript_path: Path | None = None


# lup: defer(issue=52, why="Claude Code's spelling of a fork's agent type, a module constant until a `Spellings` each adapter implements gives it its home")
FORK = "fork"
"""The type of a subagent spawned with the conversation so far: their record's
`agentType` (measured on 2.1.303, `docs/field-notes.md`, *Subagents' records*).
A fork "sees the same system prompt, tools, model, and message history as the
main session" (the `sub-agents` docs, *Fork the current conversation*), so they
read the session's guidance, which the system prompt carries."""


def subagent_record(
    transcript: Path | None,
    agent: str,
    launch: Register | None,
    largest: int = 1024 * 1024,
) -> SubagentRecord | None:
    """Return what Claude Code records of subagent `agent` beside the session's `transcript`, a path a hook's payload names; none where it records nothing, or not yet, or where the path isn't under the own runtime directory of `launch`, the launch whose room ran the hook, which is the only place the host reads one, in the home that launch registered (`lup_dev.host.homes.translated`).

    It's read confined to that home, at most `largest` bytes, since a room
    writes it.
    """
    if transcript is None or not plain(agent):
        return None
    found = translated(launch, transcript)
    if found is None:
        return None
    meta = found.record.with_suffix("") / "subagents" / f"agent-{agent}.meta.json"
    reading = opened(found.root, meta)
    if reading is None:
        return None
    with reading:
        text = reading.read(largest + 1)
    if len(text) > largest:
        return None
    try:
        return SubagentRecord.model_validate_json(text)
    except ValidationError:
        return None


def spawned_by(payload: Payload, launch: Register | None) -> str | None:
    """Return the id of the call that spawned the subagent `payload` is of, as their record in `launch`'s home says; none for the session's own conversation, before the record is written, at `SubagentStart`, or for a hook no launch's room ran."""
    record = subagent_record(payload.transcript_path, payload.agent_id, launch)
    return None if record is None else record.tool_use_id


def spawned(raw: str, launch: Register) -> Spawned | None:
    """Return how the subagent a Claude Code hook of `launch`'s fires for was spawned, from their record beside the session's transcript, in the home `launch` registered; none for the session's own conversation.

    A subagent whose record isn't there is said by their type alone; one with
    neither is Claude Code's own (`Spawned.internal`), which writes no record:
    its prompt suggestions and `/btw`, heard only at `SubagentStop`, and the
    fork of a background subagent's conversation that summarizes their progress
    every 30 seconds, heard at that alone where they answer in words, and where
    they call a tool anyway, at that call's `PreToolUse` alone, Claude Code
    denying the call and running no other hook for it, so nothing ends their
    conversation (measured on 2.1.309, `docs/field-notes.md`, *A runtime's own agents*).
    A type is taken as a spawn's even without the subagent's record, which is written
    only after `SubagentStart`: taking a spawn for Claude Code's own would
    hide them and lose their end to their parent.

    Only a fork reads the session's guidance: every other subagent's system
    prompt is "the agent's own prompt plus environment details that Claude
    Code appends, not the Claude Code system prompt" (the `sub-agents` docs,
    *What loads at startup*), which lup's guidance is appended to.

    Claude Code hands every subagent's last message to their parent itself
    (`Spawned.handed`): the result of a foreground `Agent` call, or a
    background one's task notification, its `<result>` whole, beside the
    parent's next call's result or starting their turn (`docs/field-notes.md`,
    *A subagent's end*).
    """
    payload = Subagented.model_validate_json(raw)
    if not payload.agent_id:
        return None
    kind = payload.agent_type or None
    kept = subagent_record(payload.transcript_path, payload.agent_id, launch)
    if kept is None:
        return Spawned(
            kind=kind, guided=kind == FORK, internal=kind is None, handed=True
        )
    kind = kept.agent_type or kind
    return Spawned(
        name=kept.name,
        parent=kept.parent_agent_id,
        kind=kind,
        guided=kind == FORK,
        handed=True,
    )


type Received = Annotated[
    SessionStart
    | UserPromptSubmit
    | PreToolUse
    | WorktreeCreate
    | PostToolUse
    | Stop
    | SubagentStop
    | StopFailure,
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
    return output.printed()


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
    return output.printed()


def heard(raw: str) -> Heard:
    """Read one Claude Code hook as the host service does: who's speaking, about which call, and whether the judge reads it.

    Each hook's answer tells what Claude Code's cap allows whole (`Claude.fits`).
    Raise `ValidationError` where the payload isn't one of the hooks this
    adapter reads.
    """
    return TypeAdapter[Received](Received).validate_json(raw).heard(Claude().fits())


def told(raw: str, answer: str, telling: Telling) -> str | None:
    """Return what a Claude Code hook prints: `answer`, the judge's or none, with `telling` added; none where nothing is.

    Claude Code reads an answer starting with `{` as JSON, and any other as
    text, as `WorktreeCreate`'s path (`Placed`), which nothing is added to. A
    worktree the room's hook makes before printing the rest (`Isolating`)
    stays before it. Raise `ValidationError` where the payload isn't one of
    the hooks this adapter reads, or the answer isn't a hook's; and
    `ValueError` where `telling` would add to an answer read as text, so what
    it tells is put back.
    """
    received = TypeAdapter[Received](Received).validate_json(raw)
    made = making(answer)
    rest = answer.removeprefix(made)
    text = rest.strip()
    read = not text or text.startswith("{")
    said = Said.model_validate_json(rest) if text and read else Said()
    added = received.told(said, telling)
    if added == said:
        return None
    if not read:
        message = "lup can't add to an answer Claude Code reads as text"
        raise ValueError(message)
    return f"{made}{added.printed()}"


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


# lup: defer(issue=244, why="the frame's details, a non-empty `content`, a `session_id` other than the session's own dropped and a missing `priority` interrupting nothing, are read from the binary, owed live on the version a launch runs")
def woken(session: str, text: str) -> str:
    """Return the line that starts a turn of the idle Claude Code session `session` with `text`, on their messaging socket.

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


# lup: defer(issue=52, why="Claude Code's spelling of the channel capability, a module constant until a `Spellings` each adapter implements gives it its home")
CHANNEL = "claude/channel"
"""The experimental capability a server declares to be a channel."""


def pushed(text: str, token: str) -> Notice:
    """Return the notice that starts a turn of an idle Claude Code session with `text`, a channel's message whose tag carries `token`.

    >>> pushed("Hi.", "t1").params
    {'content': 'Hi.', 'meta': {'wake': 't1'}}
    """
    message = ChannelMessage(content=text, meta={"wake": token})
    return Notice(method=f"notifications/{CHANNEL}", params=message.model_dump())


def hooks(
    command: Callable[[type[SessionEvent]], list[str]], timeout: timedelta
) -> list[Hook]:
    """Return the hooks a launched Claude Code session runs at the events the host service hears, each running the command `command` gives for its event.

    `SessionStart`; `UserPromptSubmit`, each turn's start, a channel's message
    among them, which clears the calls the session's records show over (one
    interrupted); `PreToolUse` on every call, the file tools' writes judged
    before they land, every call told what waits for its conversation, and a
    call to lup's tools stamped with its caller; `WorktreeCreate`, a worktree
    asked for, which lup makes; `PostToolUse` and
    `PostToolUseFailure` on every call, the checkpoint after it; `Stop` and
    `SubagentStop`, each conversation's turn's end, which clears the calls they
    left that no finish reported and judges what the turn left; and
    `StopFailure`, registered with `Stop` (`spelled`, `lup.adapters.claude.terminal`),
    a turn's end on an error from the model's API, which ends a subagent's
    conversation and leaves the session's idle. Each waits up to `timeout`, which a hold's wait for the operator
    needs, at a call's start, its finish or a turn's end.
    """
    heard: list[type[SessionEvent]] = [
        events.SessionStarted,
        events.TurnStarted,
        events.CallStarted,
        events.WorktreeAsked,
        events.CallFinished,
        events.TurnEnded,
        events.ConversationEnded,
    ]
    return [
        Hook(event=event, command=command(event), timeout=timeout) for event in heard
    ]


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
    """One line of a Claude Code session's record, for the directory they ran in, where it says."""

    cwd: Path | None = None


class ClaudeRecords(Model, Records):
    """Claude Code's records: a folder per directory sessions ran in, under `projects/`, and each session's file history.

    A folder's directory is read off its records' own lines, the first naming one,
    never from the folder's name; and a folder is a directory's only where it's
    named as Claude Code names that directory's (`folder_named`). Every room
    could write the operator's directory until rooms had homes of their own, so
    a line saying the repository's directory, written into the folder of
    another's, would otherwise have that other's sessions taken for the
    repository's, copied where its rooms read them and moved into their home
    (`lup_dev.migration`). Each record is read as data alone
    (`lup_dev.host.records`).

    A launched session's is in the home their launch registered alone, as the
    host service kept it (`lup_dev.host.homes`), and any other's in the
    operator's directory alone, so a room can't have one read from its own
    home under another session's id. Rooms write a home, so the record is
    read inside it alone (`Found.root`). The records a module copies (`kept`)
    are each home's: the operator's directory's, the repository's rooms' and
    the shared one's (`homes`).
    """

    directory: Path
    """The operator's Claude Code directory, `~/.claude` or `CLAUDE_CONFIG_DIR`."""
    host: HostLayout | None = None
    """Where the host service keeps each launched session's home; none looks
    in the operator's directory alone."""
    homes: HomesLayout | None = None
    """The rooms' own homes, whose records a module copies beside the
    operator's (`kept`); none keeps the operator's directory's alone."""

    @override
    def conversation(self, session: str, agent: str | None) -> Found | None:
        """Return the record of one conversation, in its launch's home or the operator's directory, with that directory; none for an id that isn't a plain name, as a hook's payload, which a room writes, may give, or for what isn't a file there."""
        if not plain(session) or (agent is not None and not plain(agent)):
            return None
        name = (
            f"{session}.jsonl"
            if agent is None
            else f"{session}/subagents/agent-{agent}.jsonl"
        )
        home = (
            None if self.host is None else home_of(self.host, Claude().name(), session)
        )
        root = self.directory if home is None else home
        projects = root / "projects"
        if not projects.is_dir():
            return None
        return next(
            (
                Found(record=each, root=root)
                for each in sorted(projects.glob(f"*/{name}"))
                if inside(root, each) and each.is_file()
            ),
            None,
        )

    @override
    def held(self, session: str) -> bool:
        """Say whether the operator's own directory holds a record of session `session`, a regular file inside it, opened as every read is (`lup.rooms.homes.opened`)."""
        found = self.model_copy(update={"host": None}).conversation(session, None)
        reading = None if found is None else opened(found.root, found.record)
        if reading is None:
            return False
        reading.close()
        return True

    @override
    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        """Return the folders of `projects/` whose sessions ran under `under`, and each of their sessions' file history, in each home keeping the repository's records: each only where it's reached from its home without a link, a folder's directory read off its records' heads."""
        held = homes(self.directory, self.homes, repository, Claude().name())
        return [record for home in held for record in kept_in(home, under)]


def session_at(place: PurePosixPath) -> str | None:
    """Return the session whose own record is at `place` in one of Claude Code's homes, `projects/<folder>/<id>.jsonl`, as `ClaudeRecords.conversation` finds it; none for any other place.

    >>> session_at(PurePosixPath("projects/-w/8f2c.jsonl")), session_at(PurePosixPath("projects/-w/8f2c/subagents/agent-a.jsonl"))
    ('8f2c', None)
    """
    match place.parts:
        case ("projects", _, name) if PurePosixPath(name).suffix == ".jsonl" and plain(
            PurePosixPath(name).stem
        ):
            return PurePosixPath(name).stem
        case _:
            return None


def resumed(arguments: list[str]) -> str | None:
    """Return the session Claude Code's arguments resume, `--resume <id>`, `-r <id>` or `--resume=<id>`: the value given, which it takes as a session's id, or as what its picker searches for where no session has that id; none where they resume none, or open the picker bare.

    Read in its 2.1.311 help: `-r, --resume [value]`, "Resume a conversation by
    session ID, or open interactive picker with optional search term".

    >>> resumed(["--resume", "8f2c"]), resumed(["-p", "-r", "8f2c"]), resumed(["--resume=8f2c"])
    ('8f2c', '8f2c', '8f2c')
    >>> resumed(["--resume"]), resumed(["--resume", "--model", "opus"]), resumed([])
    (None, None, None)
    """
    for index, each in enumerate(arguments):
        if each.startswith("--resume="):
            return each.removeprefix("--resume=") or None
        following = arguments[index + 1 : index + 2]
        if (
            each in ["--resume", "-r"]
            and following
            and not following[0].startswith("-")
        ):
            return following[0]
    return None


def kept_in(home: Home, under: list[Path]) -> list[Record]:
    """Return the records in one of Claude Code's homes of the sessions that ran under `under`: each folder of `projects/` they ran in, named for the directory its sessions say (`filed`), and each of their sessions' `file-history/`."""
    directory = home.directory
    projects = directory / "projects"
    if not reached(directory, projects) or not projects.is_dir():
        return []
    ours = [
        folder
        for folder in sorted(projects.iterdir())
        if folder.is_dir(follow_symlinks=False)
        and (ran := ran_in(folder)) is not None
        and filed(folder, ran)
        and within(ran, under)
    ]
    histories = [
        directory / "file-history" / session.stem
        for folder in ours
        for session in sorted(folder.glob("*.jsonl"))
    ]

    def record(place: PurePosixPath) -> Record:
        return Record(home=directory, whose=home.whose, place=place)

    return [
        *(record(PurePosixPath("projects", folder.name)) for folder in ours),
        *(
            record(PurePosixPath("file-history", each.name))
            for each in histories
            if reached(directory, each) and each.is_dir()
        ),
    ]


def folder_named(directory: Path) -> str:
    """Return the name Claude Code gives the folder of the sessions run in `directory`, before it cuts a long one (`filed`): each character but an ASCII letter or digit a `-`, one per UTF-16 unit, as its 2.1.311 binary writes it (`replace(/[^a-zA-Z0-9]/g, "-")`).

    >>> folder_named(Path("/w/lup.git/tree/dev")), folder_named(Path("/w/é😀"))
    ('-w-lup-git-tree-dev', '-w----')
    """
    return "".join(
        char if char.isascii() and char.isalnum() else "-" * units(char)
        for char in str(directory)
    )


def units(char: str) -> int:
    """Return how many UTF-16 units `char` takes, as a JavaScript string counts it: two past the basic plane.

    >>> units("a"), units("😀")
    (1, 2)
    """
    return len(char.encode("utf-16-le")) // 2


def filed(folder: Path, ran: Path, longest: int = 200) -> bool:
    """Say whether `folder` is named as Claude Code names the folder of sessions run in `ran`: its name in full, or, past `longest` units, cut there with a `-` and a hash of its own after, which this doesn't check. A folder whose sessions say otherwise was written so by something else.

    >>> filed(Path("/h/projects/-w-lup-git"), Path("/w/lup.git"))
    True
    >>> filed(Path("/h/projects/-w-other"), Path("/w/lup.git"))
    False
    >>> filed(Path("/h/projects/-aaa-k3j"), Path("/aaaa"), longest=4)
    True
    """
    named = folder_named(ran)
    if len(named) <= longest:
        return folder.name == named
    # lup: ignore("string-slice", why="Claude Code cuts a long folder's name at a count of units, and what's compared is that cut, not a format read")
    return folder.name.startswith(f"{named[:longest]}-")


def ran_in(folder: Path) -> Path | None:
    """Return the directory the sessions recorded in `folder` ran in, read off their first line naming one, within each record's head (`head`); none where none does."""
    for record in sorted(folder.glob("*.jsonl")):
        for line in head(record):
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
    """A call to a tool, by its name, its id, which the call's hooks carry as `tool_use_id`, and its input, read for the calls that write the task list."""

    type: Literal["tool_use"]
    name: str
    id: str | None = None
    input: JsonObject = {}


class ResultPart(Model, extra="ignore"):
    """A part of a call's result: text, an image, or a tool found by `ToolSearch`."""

    type: str
    text: str | None = None
    tool_name: str | None = None

    def said(self) -> str:
        """Return what the part says: its text, or what it is where it isn't text.

        >>> ResultPart(type="tool_reference", tool_name="mcp__lup__rename").said()
        '[tool_reference: mcp__lup__rename]'
        """
        if self.text is not None:
            return self.text
        named = "" if self.tool_name is None else f": {self.tool_name}"
        return f"[{self.type}{named}]"


class ToolResult(Model, extra="ignore"):
    """A call's result, by the id of the call it answers: what the agent was given, and whether Claude Code marked it an error."""

    type: Literal["tool_result"]
    tool_use_id: str
    content: str | list[ResultPart] | None = None
    is_error: bool = False

    def said(self) -> str:
        """Return what the agent was given, its parts one after another."""
        match self.content:
            case None:
                return ""
            case str() as text:
                return text
            case parts:
                return "\n".join(part.said() for part in parts)


type Background = Literal["command", "monitor", "subagent"]
"""What a call starts in the background: a command `Bash` runs, a `Monitor`'s
watch, or a subagent `Agent` spawns."""


class TaskMade(Model, extra="ignore"):
    """A task as `TaskCreate`'s result names it: its id, numbered in the session's list, and its subject."""

    id: str
    subject: str


class ToolResulted(
    Model, extra="ignore", alias_generator=to_camel, populate_by_name=True
):
    """What a `user` line keeps of a call's result beyond its text (`toolUseResult`): the task a `TaskCreate` made, where it's one, where a command's whole output was saved where the agent was given only its start, and what the call started in the background."""

    task: TaskMade | None = None
    persisted_output_path: Path | None = None
    """The file Claude Code saved a command's whole output to, under the
    session's own folder, where the result the agent was given is its start and
    that path (`docs/field-notes.md`, *A session's record*)."""
    background_task_id: str | None = None
    """The task a `Bash` call run in the background started, which the
    `<task-notification>` of its end names as its `<task-id>`."""
    task_id: str | None = None
    """The task a `Monitor` call started, which each of its events names."""
    agent_id: str | None = None
    """The subagent an `Agent` call started in the background, which the
    notification of its end names as its `<task-id>`."""

    def started(self) -> dict[str, Background]:
        """Return what the call started in the background, by the id its notifications name: a command, a Monitor's watch or a subagent.

        >>> ToolResulted(background_task_id="b1").started()
        {'b1': 'command'}
        """
        kinds: list[Background] = ["command", "monitor", "subagent"]
        named = [self.background_task_id, self.task_id, self.agent_id]
        return {
            each: kind
            for each, kind in zip(named, kinds, strict=True)
            if each is not None
        }


class CommandRun(Model, extra="ignore"):
    """`Bash`'s input: the command, and what it does in a few words, where the agent said."""

    command: str
    description: str | None = None


class FileRead(Model, extra="ignore"):
    """`Read`'s input: the file, and the line it starts at, where it isn't the first."""

    file_path: str
    offset: int | None = None


class FileWritten(Model, extra="ignore"):
    """The input of a tool writing one file, `Edit`'s or `Write`'s: the file."""

    file_path: str


class NotebookWritten(Model, extra="ignore"):
    """`NotebookEdit`'s input: the notebook."""

    notebook_path: str


class Searched(Model, extra="ignore"):
    """A search's input, `Grep`'s or `Glob`'s: its pattern."""

    pattern: str


def gisted(call: ToolUse) -> str | None:
    """Return what a call did, in a line: `Bash`'s description, else its command; the file a `Read` reads, at the line it starts at; the file an `Edit`, a `Write` or a `NotebookEdit` writes; a search's pattern; any other's first argument, as its input is read where it isn't its tool's.

    >>> gisted(ToolUse(type="tool_use", name="Read", input={"file_path": "/w/src/review.ts", "offset": 480}))
    'review.ts:480'
    >>> gisted(ToolUse(type="tool_use", name="Bash", input={"command": "uv run pytest", "description": "Run the tests"}))
    'Run the tests'
    """
    try:
        match call.name:
            case "Bash":
                run = CommandRun.model_validate(call.input)
                return gist(run.description or run.command)
            case "Read":
                read = FileRead.model_validate(call.input)
                name = PurePosixPath(read.file_path).name
                return gist(name if read.offset is None else f"{name}:{read.offset}")
            case "Edit" | "Write":
                written = FileWritten.model_validate(call.input)
                return gist(PurePosixPath(written.file_path).name)
            case "NotebookEdit":
                notebook = NotebookWritten.model_validate(call.input)
                return gist(PurePosixPath(notebook.notebook_path).name)
            case "Grep" | "Glob":
                return gist(Searched.model_validate(call.input).pattern)
            case _:
                pass
    except ValidationError:
        pass
    return gist(first(call.input))


class TaskCreated(
    Model, extra="ignore", alias_generator=to_camel, populate_by_name=True
):
    """`TaskCreate`'s input: the task's subject, and what it says while in progress."""

    subject: str
    active_form: str | None = None


class TaskUpdated(
    Model, extra="ignore", alias_generator=to_camel, populate_by_name=True
):
    """`TaskUpdate`'s input: the task, by its id, and what changes of it: its status, `deleted` taking it off the list, its subject, or what it says while in progress."""

    task_id: str
    status: Status | Literal["deleted"] | None = None
    subject: str | None = None
    active_form: str | None = None


class Todo(Model, extra="ignore", alias_generator=to_camel, populate_by_name=True):
    """One entry of `TodoWrite`'s list: what's to do, where it stands, and what it says while in progress."""

    content: str
    status: Status
    active_form: str | None = None


class TodosWritten(Model, extra="ignore"):
    """`TodoWrite`'s input: the whole list, which replaces the one before."""

    todos: list[Todo]


class Counted(Model, extra="ignore"):
    """What a reply's `usage` counts of its input: the tokens read anew, those written to the cache, and those read from it, which together are the context the reply was made in."""

    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def used(self) -> int:
        """Return the tokens the context held at the reply: each part of its input.

        >>> Counted(input_tokens=2, cache_creation_input_tokens=14149, cache_read_input_tokens=8077).used()
        22228
        """
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


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
    tool_use_result: Annotated[
        ToolResulted | JsonValue, Field(union_mode="left_to_right")
    ] = None
    """What the line keeps of the result it carries, where it carries one: an
    object for most tools, which lup reads; the error's text for a call that
    failed or was refused, and the parts of a server's result, which it doesn't."""

    def answers(self) -> list[str]:
        """Return the ids of the calls whose results the line carries."""
        match self.message.content:
            case str():
                return []
            case blocks:
                return [
                    block.tool_use_id
                    for block in blocks
                    if isinstance(block, ToolResult)
                ]

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
    """An assistant line's message: its parts, the model that made it, and what its input counted."""

    content: list[Block] = []
    model: str | None = None
    """The model that made it, as the API names it, never with `[1m]` after it;
    `<synthetic>` on a reply of Claude Code's own."""
    usage: Counted | None = None


class AssistantLine(Model, extra="ignore", alias_generator=to_camel):
    """An `assistant` line: the agent's text, and the tools they called."""

    type: Literal["assistant"]
    message: AssistantMessage
    timestamp: datetime | None = None
    is_sidechain: bool = False
    requested_model: str | None = None
    """The model the conversation asked for, `[1m]` after it where they chose
    the long variant; none in a record before Claude Code 2.1.295."""


class QueuedCommand(Model, extra="ignore", alias_generator=to_camel):
    """A message that arrived while the agent worked, given to them at their next step."""

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
    attachment: Annotated[
        QueuedCommand | OtherAttachment, Field(union_mode="left_to_right")
    ]
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
    """Claude Code's records, read: a session's file per session under `projects/<folder>/`, its subagents' in a folder beside it; each conversation's context from its last reply, in the window of the model that made it."""

    settings: Path | None = None
    """The operator's own settings file, whose `env` may turn the long window
    off for every session it starts; none reads nothing of it, as for a copy
    of the records."""
    layout: Layout | None = None
    """Where lup keeps the rooms' homes and launches: a session recorded in a
    home ran in a room, whose settings carry nothing of the operator's `env`,
    and a call's saved output is named under its launch's own runtime
    directory; none where neither is read."""
    window: int = 200_000
    """The standard context window, in tokens."""
    long: str = "[1m]"
    """What follows a model's name, in any case, where the long variant was
    chosen (`model-config`, *1M context window*)."""
    long_window: int = 1_000_000
    """The long context's window, in tokens."""
    synthetic: str = "<synthetic>"
    """The model a reply of Claude Code's own names, an error's or an
    interruption's: no model made it, and its usage counts nothing."""

    @override
    def sessions(self, copies: Path) -> list[Path]:
        projects = copies / "projects"
        return sorted(projects.glob("*/*.jsonl")) if projects.is_dir() else []

    @override
    def read(self, record: Path, root: Path | None = None) -> Transcript:
        lines = list(parsed(record, root))
        ran = [each.cwd for each in lines if isinstance(each, UserLine) and each.cwd]
        # A subagent's own record, `<session>/subagents/agent-<id>.jsonl`, is all
        # sidechain; a session's own is its main line.
        sidechain = record.parent.name == "subagents"
        own = [
            each
            for each in lines
            if isinstance(each, AssistantLine) and each.is_sidechain == sidechain
        ]
        return Transcript(
            runtime=Claude().name(),
            session=record.stem,
            title=named(lines),
            directory=next(iter(ran), None),
            entries=[
                entry for each in lines for entry in entries(each, sidechain=sidechain)
            ],
            usage=self.usage(own, record),
            tasks=tasks(lines),
        )

    @override
    def calls(
        self, record: Path, ids: list[str], root: Path | None = None
    ) -> list[Call]:
        """Read calls whole: each one's input from the `tool_use` part calling it, and its output from the `tool_result` answering it, or from the file Claude Code saved a command's whole output to, where that's in the session's own folder.

        A saved output is read only from the session's folder, as Claude Code
        writes it there, so a record naming a file elsewhere, written in a room,
        reads nothing outside the records.
        """
        lines = list(parsed(record, root))
        inputs = {
            block.id: block.input
            for line in lines
            if isinstance(line, AssistantLine)
            for block in line.message.content
            if isinstance(block, ToolUse) and block.id is not None and block.id in ids
        }
        results = {
            block.tool_use_id: Call(
                id=block.tool_use_id,
                input=None,
                output=saved(record, line, root, self.layout) or block.said(),
                failed=block.is_error,
            )
            for line in lines
            if isinstance(line, UserLine) and isinstance(line.message.content, list)
            for block in line.message.content
            if isinstance(block, ToolResult) and block.tool_use_id in ids
        }
        return [
            (results.get(each) or Call(id=each, input=None)).model_copy(
                update={"input": inputs[each]}
            )
            for each in ids
            if each in inputs
        ]

    def usage(self, own: list[AssistantLine], record: Path) -> Usage | None:
        """Return what the context held at the last of `own`, the conversation's replies in `record`, that a model made and that counted its input; none where none did."""
        counted = [
            each
            for each in own
            if each.message.usage is not None and each.message.model != self.synthetic
        ]
        if not counted:
            return None
        last = counted[-1]
        return Usage(
            used=last.message.usage.used() if last.message.usage is not None else 0,
            window=self.windowed(last, shortened=self.shortened(record)),
            model=last.message.model,
        )

    def windowed(self, reply: AssistantLine, *, shortened: bool | None) -> int | None:
        """Return the context window `reply` was made in, by the model that made it (`lup.adapters.claude.windows`); none where that isn't known.

        A model with the long window natively reads it, and one that reaches it
        only through its `[1m]` variant reads it where the conversation asked
        for that variant, which their record says from Claude Code 2.1.295 on
        (`requested_model`). Every model reads the standard window where
        `shortened`, the long one turned off; none where that can't be read.

        >>> reading, reply = ClaudeTranscripts(), AssistantLine.model_validate(
        ...     {"type": "assistant", "message": {"model": "claude-opus-4-6"}, "requestedModel": "claude-opus-4-6[1m]"}
        ... )
        >>> reading.windowed(reply, shortened=False), reading.windowed(reply, shortened=True)
        (1000000, 200000)
        """
        model = reply.message.model
        if model is None or not catalogued(model) or shortened is None:
            return None
        if shortened:
            return self.window
        match reach(model), reply.requested_model:
            case "long", _:
                return self.long_window
            case "chosen", str() as requested:
                chose = self.long in requested.lower()
                return self.long_window if chose else self.window
            case "chosen", None:
                return None
            case "standard", _:
                return self.window

    def shortened(self, record: Path) -> bool | None:
        """Return whether the operator's settings turn the long window off for the session of `record`, as the file stands at this reading; none where it doesn't read.

        A session recorded in a room's home started with none of it: a room's
        settings leave the operator's `env` out (`ClaudeHome.blocked`).

        A session applies their settings' `env` as they start, so a change made
        after reads here before the session has it. `/model` never writes it, as it
        writes the model the record names instead (#282), so it changes only
        where the operator edits it. A launched room's environment carries the
        variable only from that file: lup's own settings and its environment
        never set it, and the operator's shell doesn't reach the room.
        """
        roomed = self.layout is not None and record.is_relative_to(
            self.layout.homes.home
        )
        if self.settings is None or roomed:
            return False
        try:
            return own_settings(self.settings).shortened()
        except TerminalError:
            return None


class Replay(MutableModel):
    """The task list as the calls of a record so far left it, and the `TaskCreate`s waiting for their result to number them."""

    kept: dict[str, Task] = {}
    creating: dict[str, TaskCreated] = {}
    """By the id of the call, until its result is read."""

    def take(self, line: Line) -> None:
        """Make what `line` does to the list: a call that writes it, or the result numbering a task created."""
        match line:
            case AssistantLine(message=message):
                for block in message.content:
                    if isinstance(block, ToolUse):
                        self.kept = self.written(block)
            case (
                UserLine(tool_use_result=ToolResulted(task=TaskMade() as made)) as user
            ):
                for answered in user.answers():
                    created = self.creating.pop(answered, None)
                    if created is not None:
                        self.kept[made.id] = Task(
                            id=made.id,
                            subject=made.subject,
                            status="pending",
                            active=created.active_form,
                        )
            case _:
                pass

    def written(self, call: ToolUse) -> dict[str, Task]:
        """Return the list as `call` leaves it, noting a `TaskCreate` until its result numbers it; a call whose input doesn't read as its tool's leaves it as it is."""
        try:
            match call.name:
                case "TaskCreate" if call.id is not None:
                    self.creating[call.id] = TaskCreated.model_validate(call.input)
                case "TaskUpdate":
                    return updated(self.kept, TaskUpdated.model_validate(call.input))
                case "TodoWrite":
                    todos = TodosWritten.model_validate(call.input).todos
                    return {
                        str(at): Task(
                            id=str(at),
                            subject=each.content,
                            status=each.status,
                            active=each.active_form,
                        )
                        for at, each in enumerate(todos, start=1)
                    }
                case _:
                    pass
        except ValidationError:
            return self.kept
        return self.kept


def tasks(lines: list[Line]) -> list[Task]:
    """Replay the task list from the calls that wrote it, and return it as it stands at the record's end.

    `TaskCreate` adds an entry, numbered by its result (`TaskMade`), so a
    subagent's, sharing their session's list, takes the number the list
    gave it; `TaskUpdate` changes one, `deleted` taking it off; `TodoWrite`
    replaces the whole list, its entries numbered in order.
    """
    replay = Replay()
    for line in lines:
        replay.take(line)
    return list(replay.kept.values())


def updated(kept: dict[str, Task], change: TaskUpdated) -> dict[str, Task]:
    """Return the task list `kept` with `change` made to the task it names, or as it was where the list has no such task."""
    task = kept.get(change.task_id)
    if task is None:
        return kept
    if change.status == "deleted":
        return {key: each for key, each in kept.items() if key != change.task_id}
    changed = task.model_copy(
        update={
            "status": task.status if change.status is None else change.status,
            "subject": task.subject if change.subject is None else change.subject,
            "active": task.active if change.active_form is None else change.active_form,
        }
    )
    return {**kept, change.task_id: changed}


def parsed(record: Path, root: Path | None = None) -> Iterator[Line]:
    """Yield each line of `record` lup reads, passing over the others, any that isn't JSON, and any too long to hold (`lup.rooms.homes.lines`); with `root`, read only where, opened, the record is inside it, nothing otherwise."""
    reading = TypeAdapter[Line](Line)
    written = record.open("rb") if root is None else opened(root, record)
    if written is None:
        return
    with written:
        for raw in lines(written):
            try:
                yield reading.validate_json(raw.decode(errors="replace"))
            except ValidationError:
                continue


def saved(
    record: Path, line: UserLine, root: Path | None = None, layout: Layout | None = None
) -> str | None:
    """Return the whole output Claude Code saved of the call whose result `line` carries, where it saved one in the session's own folder beside `record`; none where it saved none, or the file isn't there.

    The session's folder is `<session>/` beside its record, and a subagent's
    record is in its `subagents/` folder, so it's the folder holding that. A
    room's session names their saved output under their launch's own runtime
    directory, which is read as the same place in the home it registered
    (`lup_dev.host.homes.translated`). This is the host reading a record it
    keeps, not answering a hook, and a session resumed in a later launch has
    lines naming each launch's own directory, so the path is taken as any
    served launch's (`served`). The output is read only from inside the
    session's folder, as the line names it, and only where, opened, it's
    inside `root`, or inside the folder holding the record without one, so a
    record naming a file elsewhere, in another launch's home among them, or a
    folder a room swapped for a link, reads nothing outside the records.
    """
    match line.tool_use_result:
        case ToolResulted(persisted_output_path=Path() as named):
            pass
        case _:
            return None
    launches = [] if layout is None else served(layout)
    found = next(
        (
            each
            for launch in launches
            if (each := translated(launch, named)) is not None
        ),
        None,
    )
    path = named if found is None else found.record
    folder = (
        record.parent.parent
        if record.parent.name == "subagents"
        else record.with_suffix("")
    )
    if not path.is_relative_to(folder) or ".." in path.relative_to(folder).parts:
        return None
    reading = opened(record.parent if root is None else root, path)
    if reading is None:
        return None
    with reading:
        return reading.read().decode(errors="replace")


def recorded(transcript: Path, agent: str) -> Path:
    """Return where Claude Code records conversation `agent` of the session whose transcript is `transcript`: the transcript for the session's own, `<session>/subagents/agent-<id>.jsonl` beside it for a subagent's (`docs/field-notes.md`, *Subagents' records*)."""
    if not agent:
        return transcript
    return transcript.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"


def resulted(record: Path, calls: list[str], root: Path | None = None) -> list[str]:
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
        for line in parsed(record, root)
        if isinstance(line, UserLine) and not isinstance(line.message.content, str)
        for block in line.message.content
        if isinstance(block, ToolResult)
    ]
    return [call for call in calls if call in found]


def named(lines: list[Line]) -> str | None:
    """Return a session's name: the last one the operator or lup gave them, else their last agent name, else Claude Code's last title; none where they have none."""
    custom = [each.custom_title for each in lines if isinstance(each, CustomTitle)]
    agents = [each.agent_name for each in lines if isinstance(each, AgentName)]
    titles = [each.ai_title for each in lines if isinstance(each, AiTitle)]
    return next((names[-1] for names in [custom, agents, titles] if names), None)


def entries(line: Line, *, sidechain: bool = False) -> list[Entry]:
    """Return the steps one line of a record holds: the operator's words, the agent's text, the tools they called; the agent's on the record's own line, its main one or, in a subagent's record, its `sidechain`."""
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
            attachment=QueuedCommand(
                command_mode="prompt", origin=Origin(kind="human")
            ) as queued,
            timestamp=at,
        ):
            return [Spoken(by="operator", text=queued.prompt, at=at)]
        case _:
            return []


def said_by_agent(block: Block, at: datetime | None) -> Entry | None:
    """Return the step a part of the agent's message is: its text, or a tool they called; none for any other part."""
    match block:
        case TextBlock(text=text):
            return Spoken(by="agent", text=text, at=at)
        case ToolUse(name=name, id=id_) as call:
            return Called(tool=name, gist=gisted(call), id=id_, at=at)
        case _:
            return None


class QueueOperation(Model, extra="ignore"):
    """A line saying what Claude Code did with its session's queue, which holds what reaches a conversation once their running call returns: `enqueue` puts a prompt there; `dequeue` hands the oldest to an idle session as their turn's prompt; `remove` takes one out by its text, absorbed into a running turn; `popAll` takes the operator's typed words back into the input to edit."""

    type: Literal["queue-operation"]
    operation: Literal["enqueue", "dequeue", "remove", "popAll"]
    content: str | None = None


type Followed = Annotated[QueueOperation | UserLine, Field(discriminator="type")]
"""A line of a record its queue is followed through: one saying what Claude Code
did with the queue, or one carrying a call's result, which says what the call
started in the background."""


class Pending(Model):
    """A prompt Claude Code holds in its session's queue: where its `enqueue` line starts in the record, and its text."""

    at: int
    content: str


class Following(MutableModel):
    """A conversation's record as read so far, for what Claude Code holds queued: how far it was read, the queue its lines leave where it's a session's own record, and what the conversation's calls started."""

    read: int = 0
    """The bytes read, to the end of the last whole line."""
    pending: list[Pending] = []
    started: dict[str, Background] = {}
    """What the conversation's calls started in the background, by each id its
    notifications name: its task's, and its call's."""


class Attributes(Model, extra="ignore"):
    """What lup reads of the attributes of the tag a queued prompt opens with."""

    source: str | None = None
    """A channel's: the server that pushed it."""
    from_name: str | None = Field(default=None, alias="from-name")
    """Another session's message: the name of the session who sent it."""


class Opening(HTMLParser):
    """Reads what a queued prompt opens with: the tag it starts with, where text doesn't come first, its attributes, and the text of each element inside it, such as `<task-id>` and `<summary>`."""

    def __init__(self) -> None:
        """Read nothing yet."""
        super().__init__(convert_charrefs=True)
        self.tag: str | None = None
        self.attributes = Attributes()
        self.texts: dict[str, str] = {}
        self.inside: list[str] = []
        self.worded = False
        """Whether text came before any tag: the operator's words, typed."""

    @override
    def handle_starttag(
        self,
        tag: str,
        # lup: ignore("tuple-shape", why="`HTMLParser`'s own signature, which this overrides")
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.tag is None and not self.worded:
            self.tag = tag
            self.attributes = Attributes.model_validate(
                {name: value or "" for name, value in attrs}
            )
        self.inside = [*self.inside, tag]

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in self.inside:
            last = len(self.inside) - 1 - self.inside[::-1].index(tag)
            self.inside = self.inside[:last]

    @override
    def handle_data(self, data: str) -> None:
        if self.tag is None and data.strip():
            self.worded = True
        if self.inside:
            innermost = self.inside[-1]
            self.texts = {
                **self.texts,
                innermost: self.texts.get(innermost, "") + data,
            }

    def text(self, tag: str) -> str | None:
        """Return the text of the element `tag` inside the prompt, without the space around it; none where there's none, or it's blank."""
        said = self.texts.get(tag, "").strip()
        return said or None


class Prompted(Model):
    """What a prompt Claude Code queued is, read off its text: what it holds for the agent, the ids tying it to the conversation that started what it's about, and what it says it is."""

    kind: Queuing
    names: list[str] = []
    """The ids of the task and of the call it's about; none for what's the
    session's own conversation's, whatever made it."""
    summary: str | None = None


def prompted(content: str) -> Prompted | None:
    r"""Read what a prompt Claude Code queued for its session is; none for lup's own push or doorbell, which lup's inbox tells already.

    Measured on 2.1.311 (`docs/field-notes.md`, *What a session holds queued*):
    a background command's end, a Monitor's event and a background subagent's
    end are each a `<task-notification>`, naming its `<task-id>` and, but for
    most Monitors', its call's `<tool-use-id>`; a background subagent's report
    is an `<agent-message>`, and another session's message a
    `<cross-session-message>`, both the session's own conversation's; the
    operator's typed words are their text. What opens with no tag lup knows
    is taken for the operator's, so a call is never held past it.

    >>> prompted("Stop the gate.").kind
    'typed'
    >>> prompted('<channel source="lup" wake="t1">\n<note item="7"/>\n</channel>') is None
    True
    >>> notice = prompted(
    ...     "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>toolu_1</tool-use-id>\n"
    ...     '<summary>Background command "gate" completed (exit code 0)</summary>\n'
    ...     "</task-notification>"
    ... )
    >>> notice.kind, notice.names, notice.summary
    ('task', ['b1', 'toolu_1'], 'Background command "gate" completed (exit code 0)')
    >>> prompted('<cross-session-message from="uds:/s" from-name="main-09">\nHi\n</cross-session-message>').summary
    'from main-09'
    """
    opening = Opening()
    opening.feed(content)
    opening.close()
    match opening.tag:
        case "channel" if opening.attributes.source == SERVER:
            return None
        case "doorbell":
            return None
        case "task-notification":
            named = [opening.text("task-id"), opening.text("tool-use-id")]
            return Prompted(
                kind="task",
                names=[each for each in named if each is not None],
                summary=opening.text("summary"),
            )
        case "agent-message":
            return Prompted(kind="subagent")
        case "cross-session-message":
            sender = opening.attributes.from_name
            return Prompted(
                kind="message", summary=None if sender is None else f"from {sender}"
            )
        case _:
            return Prompted(kind="typed")


class ClaudeQueues(MutableModel, Queues, arbitrary_types_allowed=True):
    """What Claude Code holds queued for each conversation of a session, read from its records as they grow (`docs/field-notes.md`, *What a session holds queued*).

    Measured on 2.1.311: a session has one queue, written in its own record as
    `queue-operation` lines whoever it's for, a subagent's background command
    among it; what a subagent absorbs is written in their own record only once
    they have. So the queue is replayed from the session's record (`Following`),
    and a prompt is a subagent's where the task or the call it names was
    started by that subagent's own calls, as their record says; the operator's
    words, a subagent's report and another session's message, which name
    none, are the session's own conversation's.
    """

    records: ClaudeRecords
    followed: dict[Path, Following] = {}
    """Each record as read so far, by its path, so a look reads only what it
    gained since."""
    found: dict[str, Found] = {}
    """Each conversation's record, by `session/agent`, once found."""
    largest: int = 64 * 1024 * 1024
    """The longest line held: a longer one, which a room's record could hold,
    is read past."""
    reading: threading.Lock = Field(default_factory=threading.Lock)
    """Held while a look reads, since held calls look from threads of their own."""

    @override
    def queued(
        self, session: str, agent: str | None, home: Path | None
    ) -> list[Queued]:
        with self.reading:
            main = self.record(session, None, home)
            if main is None:
                return []
            queue = self.following(main, sidechains=False)
            own = queue
            if agent is not None:
                record = self.record(session, agent, home)
                own = (
                    Following()
                    if record is None
                    else self.following(record, sidechains=True)
                )
            pending = list(queue.pending)

        def held(each: Pending) -> Queued | None:
            said = prompted(each.content)
            if said is None:
                return None
            ours = any(name in own.started for name in said.names)
            if (said.names and not ours) or (not said.names and agent is not None):
                return None
            ended = said.kind == "task" and any(
                own.started.get(name) == "subagent" for name in said.names
            )
            return Queued(
                id=str(each.at),
                kind="subagent" if ended else said.kind,
                summary=said.summary,
            )

        return [queued for each in pending if (queued := held(each)) is not None]

    def record(
        self, session: str, agent: str | None, home: Path | None
    ) -> Found | None:
        """Return conversation `agent`'s record of session `session`, the session's own for none, found once and looked for again where it's gone; none where it isn't on this machine, or is found in a home other than `home`, where one is given (`Queues.queued`)."""
        key = f"{session}/{agent}"
        kept = self.found.get(key)
        found = (
            kept
            if kept is not None and kept.record.is_file()
            else self.records.conversation(session, agent)
        )
        if found is not None:
            self.found = {**self.found, key: found}
        if found is None or (home is not None and found.root != home):
            return None
        return found

    def following(self, found: Found, *, sidechains: bool) -> Following:
        """Return the record `found` as read so far, read on from where the last look left off to the end of its last whole line; read anew where it shrank, written again. `sidechains` says whether its lines marked a subagent's are its own: in a subagent's record they all are, and in a session's an earlier release kept its subagents' there.

        It's read through what was opened, confined to its home
        (`lup.rooms.homes.opened`), a line at a time, a line past `largest`
        read past without being held.
        """
        record = found.record
        kept = self.followed.get(record, Following())
        reading = opened(found.root, record)
        if reading is None:
            return kept
        with reading:
            size = os.fstat(reading.fileno()).st_size
            if size < kept.read:
                kept = Following()
            reading.seek(kept.read)
            at = kept.read
            while at < size:
                raw = reading.readline(self.largest + 1)
                if raw.endswith(b"\n") and len(raw) <= self.largest:
                    followed(kept, raw, at, sidechains=sidechains)
                    at += len(raw)
                    continue
                if len(raw) <= self.largest:
                    break
                past = len(raw)
                while raw and not raw.endswith(b"\n"):
                    raw = reading.readline(self.largest)
                    past += len(raw)
                if not raw.endswith(b"\n"):
                    break
                at += past
            kept.read = at
        self.followed = {**self.followed, record: kept}
        return kept


def followed(kept: Following, raw: bytes, at: int, *, sidechains: bool) -> None:
    """Follow one whole line of a record, starting at byte `at`, into what was read of it: its queue, where it says what Claude Code did with it, and what the conversation's calls started, where it carries a call's result.

    Only a line naming the queue or a call's result is parsed, a record being
    mostly the conversation's own steps; one that isn't JSON, or isn't either,
    is passed over.
    """
    if b'"queue-operation"' not in raw and b'"toolUseResult"' not in raw:
        return
    try:
        line = TypeAdapter[Followed](Followed).validate_json(raw)
    except ValidationError:
        return
    match line:
        case QueueOperation(operation="enqueue", content=str() as content):
            kept.pending = [*kept.pending, Pending(at=at, content=content)]
        case QueueOperation(operation="dequeue"):
            kept.pending = kept.pending[1:]
        case QueueOperation(operation="remove", content=content):
            taken = next(
                (each for each in kept.pending if each.content == content), None
            )
            kept.pending = [each for each in kept.pending if each is not taken]
        case QueueOperation(operation="popAll"):
            kept.pending = [
                each
                for each in kept.pending
                if (said := prompted(each.content)) is None or said.kind != "typed"
            ]
        case UserLine(is_sidechain=True) if not sidechains:
            return
        case UserLine(tool_use_result=ToolResulted() as result) as user:
            started = result.started()
            calls: dict[str, Background] = {
                call: kind for call in user.answers() for kind in started.values()
            }
            kept.started = {**kept.started, **started, **calls}
        case _:
            return


class HostPermissions(Model, extra="ignore", alias_generator=to_camel):
    """What the operator's own settings let a host session do without asking, and what they ask before or deny."""

    allow: list[str] = []
    ask: list[str] = []
    deny: list[str] = []
    default_mode: str | None = None
    additional_directories: list[str] = []


class HostSettings(Model, extra="ignore", alias_generator=to_camel):
    """What of the operator's own `settings.json` a host session runs, sets, loads or acts on without asking, read in the `settings` docs (2026-10-28) for the check of what rooms could have written there."""

    hooks: JsonValue = None
    status_line: JsonValue = None
    file_suggestion: JsonValue = None
    api_key_helper: str | None = None
    aws_auth_refresh: str | None = None
    aws_credential_export: str | None = None
    otel_headers_helper: str | None = None
    env: dict[str, JsonValue] = {}
    enabled_plugins: dict[str, JsonValue] = {}
    extra_known_marketplaces: dict[str, JsonValue] = {}
    permissions: HostPermissions = HostPermissions()
    skip_dangerous_mode_permission_prompt: bool = False
    enable_all_project_mcp_servers: bool = False

    def runs(self) -> list[str]:
        """List each command it has a host session run: its hooks', the status line's, the file suggestion's, and each credential helper."""
        helpers = [
            self.api_key_helper,
            self.aws_auth_refresh,
            self.aws_credential_export,
            self.otel_headers_helper,
        ]
        return [
            *written.commands(self.hooks),
            *written.commands(self.status_line),
            *written.commands(self.file_suggestion),
            *(each for each in helpers if each is not None),
        ]

    def unasked(self) -> list[str]:
        """Say each thing it lets a host session do without asking."""
        permissions = self.permissions
        return [
            *(f"allows `{each}`" for each in permissions.allow),
            *(
                [f"starts in `{permissions.default_mode}`"]
                if permissions.default_mode not in [None, "default"]
                else []
            ),
            *(
                f"reaches `{each}` beside its project"
                for each in permissions.additional_directories
            ),
            *(
                ["skips the warning before bypassing permissions"]
                if self.skip_dangerous_mode_permission_prompt
                else []
            ),
            *(
                ["starts every project's MCP servers"]
                if self.enable_all_project_mcp_servers
                else []
            ),
        ]

    def enabled(self) -> list[str]:
        """List each plugin it turns on."""
        return [name for name, on in self.enabled_plugins.items() if on is True]


class ClaudeWritten(Model):
    """What a host Claude Code session acts on in the operator's own directory, which every room could write before rooms had homes of their own, checked as it stands (`lup_dev.host.written`).

    Each item read in the `claude-directory` docs (2026-10-27) and the 2.1.311
    binary: the settings, memory and what a session loads; what a session runs
    before their commands; the background sessions' supervisor's state; the mods
    sessions made; the record folders whose name and sessions disagree; and the
    login every room could read.
    """

    directory: Path
    """The operator's Claude Code directory, `~/.claude` or `CLAUDE_CONFIG_DIR`."""
    loaded: list[str] = ["agents", "commands", "output-styles", "rules", "workflows"]
    """The directories whose files a host session loads, beside their skills and
    plugins."""
    configuration: list[str] = [
        "settings.json",
        "CLAUDE.md",
        "keybindings.json",
        "skills",
        "plugins",
        "agents",
        "commands",
        "output-styles",
        "rules",
        "workflows",
        "dev-mods",
    ]
    """Where Claude Code makes no link itself: one found there is said."""

    def checked(self, places: written.Places) -> written.Checked:
        """Say what a host session acts on in the directory, a line each: what's there, what of it looks planted, and what to do, the login apart."""
        settings = self.settings()
        return written.Checked.of(
            [
                self.read_settings(settings, places),
                written.Checked(found=[*self.memory(), *self.skills()]),
                self.plugins(settings),
                written.Checked(
                    found=[
                        *self.links(places),
                        *self.run_before(places),
                        *self.supervisor(),
                        *self.folders(),
                    ]
                ),
            ],
            login=self.login(),
        )

    def settings(self) -> HostSettings | str | None:
        """Read the operator's settings, or say why they couldn't be; none where there are none."""
        path = self.directory / "settings.json"
        if not path.exists() and not path.is_symlink():
            return None
        held = written.read(path)
        if held is None:
            return (
                "`settings.json` isn't a regular file lup reads, or is past 4 MiB: "
                "look at it yourself."
            )
        try:
            return HostSettings.model_validate_json(held)
        except ValidationError:
            return "`settings.json` isn't settings lup reads: look at it yourself."

    def read_settings(
        self, settings: HostSettings | str | None, places: written.Places
    ) -> written.Checked:
        """Say what the settings have a host session run, set, and do without asking, the commands flagged where they name a directory rooms write; fine where they do none of it."""
        match settings:
            case None:
                return written.Checked()
            case str():
                return written.Checked(found=[settings])
            case HostSettings():
                pass
        runs = [written.quoted(each, places) for each in settings.runs()]
        said = [
            *([f"runs on the host {'; '.join(runs)}"] if runs else []),
            *(
                [
                    "sets in every host session's environment "
                    + ", ".join(f"`{name}`" for name in settings.env)
                ]
                if settings.env
                else []
            ),
            *(
                [
                    "adds the plugin marketplaces "
                    + ", ".join(
                        f"`{name}`" for name in settings.extra_known_marketplaces
                    )
                ]
                if settings.extra_known_marketplaces
                else []
            ),
            *(
                [f"lets a host session act without asking: {'; '.join(unasked)}"]
                if (unasked := settings.unasked())
                else []
            ),
        ]
        first = (
            f"`settings.json` {'; it '.join(said)}. Each is yours only if you set it."
            if said
            else (
                "`settings.json`: nothing in it runs a command, sets a variable, or "
                "lets a session act without asking."
            )
        )
        permissions = settings.permissions
        kept = (
            f" It asks before {written.counted(len(permissions.ask), 'kind of call', 'kinds of call')} "
            f"and denies {len(permissions.deny)}: a room could have taken one "
            "out, so check each you set is there."
            if permissions.ask or permissions.deny
            else ""
        )
        if said or kept:
            return written.Checked(found=[f"{first}{kept}"])
        return written.Checked(fine=[first])

    def memory(self) -> list[str]:
        """Say the memory every host session reads, and each directory whose files they load."""
        memory = written.read(self.directory / "CLAUDE.md")
        loaded = [
            f"`{name}/` ({written.counted(len(found), 'file', 'files')})"
            for name in self.loaded
            if (found := written.listed(self.directory / name).files)
        ]
        return [
            *(
                [
                    (
                        f"`CLAUDE.md`, {written.counted(len(memory.splitlines()), 'line', 'lines')}, "
                        "is read into every host session: check it's all yours."
                    )
                ]
                if memory is not None
                else []
            ),
            *(
                [
                    (
                        f"{', '.join(loaded)}: a host session loads each: check "
                        "they're yours."
                    )
                ]
                if loaded
                else []
            ),
        ]

    def skills(self) -> list[str]:
        """Say each skill a host session loads, by its directory's name."""
        found = [
            each.parent.name
            for each in written.listed(self.directory / "skills").files
            if each.name == "SKILL.md"
            and ".trash" not in each.relative_to(self.directory).parts
        ]
        if not found:
            return []
        names = sorted(dict.fromkeys(found))
        copies = (
            ""
            if len(names) == len(found)
            else f", {written.counted(len(found), 'copy', 'copies')} in all"
        )
        return [
            (
                f"`skills/`: {written.counted(len(names), 'skill', 'skills')} a host "
                f"session can load{copies}, "
                f"{', '.join(f'`{name}`' for name in names)}: check each is yours."
            )
        ]

    def plugins(self, settings: HostSettings | str | None) -> written.Checked:
        """Say which plugins load in a host session: those the settings turn on, whose code under `plugins/` a room could have changed; fine where none is."""
        if not (self.directory / "plugins").is_dir():
            return written.Checked()
        enabled = settings.enabled() if isinstance(settings, HostSettings) else []
        if not enabled:
            return written.Checked(
                fine=[
                    (
                        "`plugins/`: none is turned on in `settings.json`, so none "
                        "loads in a host session."
                    )
                ]
            )
        return written.Checked(
            found=[
                (
                    f"`plugins/`: {', '.join(f'`{name}`' for name in enabled)} turned "
                    "on, whose code under `plugins/` runs in host sessions and a room "
                    "could have changed: reinstall each (`/plugin`)."
                )
            ]
        )

    def links(self, places: written.Places) -> list[str]:
        """Say each link among what a host session loads, where Claude Code makes none, flagged where it lands in a directory rooms write."""
        found = [
            each
            for name in self.configuration
            for each in written.listed(self.directory / name).links
        ]
        return [
            f"`{each.path.relative_to(self.directory)}` is a link to `{each.aimed}`"
            + (
                ", in a directory rooms write"
                if places.aims(each.path, each.aimed)
                else ""
            )
            + ": Claude Code makes none there, so check it's yours."
            for each in found
        ]

    def run_before(self, places: written.Places) -> list[str]:
        """Say what a host session runs before their commands, which rooms could have written: their shell snapshot and their session's environment."""
        snapshots = written.listed(self.directory / "shell-snapshots").files
        environments = self.directory / "session-env"
        each = (
            sorted(path for path in environments.iterdir() if path.is_dir())
            if environments.is_dir() and not environments.is_symlink()
            else []
        )
        holding = [path for path in each if written.listed(path).files]
        shown = places.shown(self.directory)
        return [
            *(
                [
                    (
                        f"`shell-snapshots/`: {written.counted(len(snapshots), 'snapshot', 'snapshots')}. "
                        "A host session runs their own before each command, and a room "
                        "could have written any: with no host session running, "
                        f"`rm {shown}/shell-snapshots/*`; a session makes a new one as they "
                        "start."
                    )
                ]
                if snapshots
                else []
            ),
            *(
                [
                    (
                        f"`session-env/`: {written.counted(len(each), 'session', 'sessions')}' "
                        f"environments, {len(holding)} holding a file, which a session "
                        "runs before each of their commands, a resumed one too: with no "
                        f"host session running, `rm -r {shown}/session-env/*`."
                    )
                ]
                if holding
                else []
            ),
        ]

    def supervisor(self) -> list[str]:
        """Say the state of what runs background sessions, and the mods sessions made: rooms could have written either, and lup can't tell what of them a room changed."""
        there = [
            name for name in ["daemon", "jobs"] if (self.directory / name).is_dir()
        ]
        mods = self.directory / "dev-mods"
        made = (
            [path for path in mods.iterdir() if path.is_dir()]
            if mods.is_dir() and not mods.is_symlink()
            else []
        )
        return [
            *(
                [
                    (
                        f"{' and '.join(f'`{name}/`' for name in there)}, the state of "
                        "the supervisor that runs background sessions, its `control.key` "
                        "among it: rooms could read and write it, and lup can't tell "
                        "what of it a room changed: with no background session running, "
                        "look through it, or remove it."
                    )
                ]
                if there
                else []
            ),
            *(
                [
                    (
                        f"`dev-mods/`: mods made in {written.counted(len(made), 'session', 'sessions')}, "
                        "which can carry code a session runs: a room could have written "
                        "any, so look through them, or remove those you don't keep."
                    )
                ]
                if made
                else []
            ),
        ]

    def folders(self) -> list[str]:
        """Say each record folder whose sessions say they ran in a directory it isn't named for, or that's a link: a room could have written it so, and lup reads it as no directory's."""
        projects = self.directory / "projects"
        if not projects.is_dir() or projects.is_symlink():
            return []
        entries = sorted(projects.iterdir())
        return [
            *(
                f"`projects/{each.name}` is a link to `{each.readlink()}`: Claude Code "
                "makes none there, and lup reads none of it."
                for each in entries
                if each.is_symlink()
            ),
            *(
                f"`projects/{each.name}` says its sessions ran in {ran}, whose folder "
                f"Claude Code names `{folder_named(ran)}`: a room could have written "
                "it so; lup reads it as no directory's, and moves none of it."
                for each in entries
                if not each.is_symlink()
                and each.is_dir()
                and (ran := ran_in(each)) is not None
                and not filed(each, ran)
            ),
        ]

    def login(self) -> str | None:
        """Say how to replace the operator's own login, which every room could read; none where there's none."""
        if not written.held(self.directory / ".credentials.json"):
            return None
        return (
            "Your host login, `.credentials.json`, was readable by every room: in a "
            "Claude Code session on the host, run `/logout` then `/login`, so the "
            "refresh token they could read is replaced. Whether `/logout` revokes "
            "it with the provider isn't documented."
        )


def login(directory: Path) -> Path:
    """Return where Claude Code keeps its login in a directory of its own at `directory`, as `CLAUDE_CONFIG_DIR` names one: `.credentials.json` there."""
    return ClaudeLayout(home=Path.home(), configured=directory).credentials


def adapter() -> Adapter:
    """Return what lup needs of Claude Code: its hooks answered, and its launch."""
    layout = ClaudeLayout.of(ClaudeSettings())
    machine = Layout.of(LupDevSettings())
    records = ClaudeRecords(
        directory=layout.directory, host=machine.host, homes=machine.homes
    )
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
        login=login,
        records=records,
        directory=layout.directory,
        written=ClaudeWritten(directory=layout.directory).checked,
        recorded=session_at,
        resumed=resumed,
        reader=ClaudeTranscripts(settings=layout.settings, layout=machine),
        queues=ClaudeQueues(records=records),
    )
