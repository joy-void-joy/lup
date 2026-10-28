"""Codex's hooks: its payloads in, lup's events, its outputs out.

| Codex hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `UserPromptSubmit` | `TurnStarted` |
| `PreToolUse` | `CallStarted` |
| none, a gap (below) | `WorktreeAsked` |
| `PostToolUse` | `CallFinished` |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

Codex has no file tools that say what they'll write before they write it: its
`apply_patch` is judged at the checkpoint, like a command. Its `PreToolUse` can't
ask, so an ask is held at the checkpoint, as on every runtime, the agent waiting
inside the hook until the operator answers the item it is in their inbox. The
agent hears what deferred work came due as `additionalContext` of `SessionStart`,
and a checkpoint's report as `additionalContext` beside the call's result, and the
result reaches it untouched.

A Codex session holds only the worktree it started in, in a room as outside one
(`docs/judging-writes.md`, *Every worktree of the repository*): its hooks' `cwd` is
the "Working directory for the session", and `Bash` and `apply_patch` carry only
`tool_input.command` (its hooks docs), which lup doesn't parse. Under its
`workspace-write` sandbox a write elsewhere lies outside the writable roots, so
Codex's own approval decides it. For the same reason every conversation of a
Codex session works in that one worktree (`Holding.works`, a subagent's hooks
carrying the session's `cwd` too: `tool_hook_cwd`, below), so a subagent's
running call holds back the main conversation's checkpoints there, where a
runtime whose file tools say where they write lets a worker busy in a worktree
of its own hold back none: a gap declared with its evidence.

In a launched room (`docs/host.md`, *The one hook*), Codex
runs the room's hook on `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` and
`SubagentStop` (`hooks`): the checkpoint after each call, the only place its
hooks see a patch, and each conversation's turn's end, which clears the calls it
left that no `PostToolUse` finishes. That end is the judge's whole set's
(`docs/judging-writes.md`, *The turn's end*): the session's `Stop` runs a
checkpoint, waits for the importers pass, and holds the turn (`decision:
"block"`, a continuation prompt to Codex) on the type errors and ruff's findings
left in the files its own conversation touched, until the same findings follow a
block (`stop_hook_active`), when the turn ends saying nothing; a refusal, a move,
an answer to a hold, removed notes and mail hold it once each. A subagent's
`SubagentStop` never holds on findings, only on what it must be told. Where
the launch's judge can't answer a hook, the host service answers it through
`unanswered`: at `PostToolUse` the agent is told beside the call's result, as when
judging fails; anything else warns the operator in `systemMessage`, and the call
goes on. Where the room's hook can't reach the service, it ends with status 1:
Codex marks the hook's run failed, shows "hook exited with code 1" (not what the
hook wrote to standard error), and the call goes on. Where it reached the
service and the connection was lost before an answer, as when the service
restarts while a hold waits, it ends with status 2 at a call's start, its finish
and a turn's end, its line on standard error, and 1 at a session's start and a
turn's start (`lost`, `launch/session.py`). Read in each event's
`parse_completed` (`hooks/src/events/`) at `b89ce9a2b`, of 2026-06-06: status 2
with something on standard error blocks `PreToolUse`'s call with it as the
reason, gives it to the model as feedback at `PostToolUse`, continues the turn
on it at `Stop` and `SubagentStop`, and stops the turn at `UserPromptSubmit`,
which a turn's start mustn't do to the operator's prompt. So the service
answers every hook with something, `{}` where it decides nothing, which
`parse_json` (`hooks/src/engine/output_parser.rs`) reads with each field its
default: no decision.

The judge reads every hook a launched Codex session runs (`heard`). It adds to
each answer through `told`: a call to
lup's tools (`mcp__lup__<tool>`, `TOOL_PREFIX`) is rewritten to carry `caller`,
lup's id for the conversation calling, as `updatedInput` beside
`permissionDecision: "allow"`; and what the conversation is told goes in as
`additionalContext` beside a call or a session's start, or as the reason a turn's
end is held (`decision: "block"`). From the source at `rust-v0.162.1`:
- an MCP tool's hook names it `mcp__<server>__<tool>`: its namespace and name
  joined by `__`, `mcp__` put before them where they lack it
  (`core/src/tools/handlers/mcp.rs`, `hook_tool_name`), the server's namespace
  `mcp__<server>` (`codex-mcp/src/mcp/mod.rs`), and any character outside
  `[A-Za-z0-9_]` turned to `_`; its `tool_input` is the call's arguments as JSON,
  or the text as it came where that isn't JSON (`mcp_hook_tool_input`), which
  isn't stamped;
- `PreToolUse`'s `updatedInput` is applied only beside `permissionDecision:
  "allow"`: alone it's refused, "PreToolUse hook returned updatedInput without
  permissionDecision:allow", and so is `allow` without it ("unsupported
  permissionDecision:allow"); the `allow` only lets the rewrite through, since
  the hook's outcome holds nothing else of it (`hooks/src/engine/output_parser.rs`,
  `parse_pre_tool_use`, `hooks/src/events/pre_tool_use.rs`). The first lup
  measured on 0.158.0 that the rewrite reached the server so, and that without
  `allow` it "was dropped — the call ran as the model wrote it"; on 0.162.1 the
  rewrite beside `allow` was seen reaching the server live (`docs/field-notes.md`,
  *Piece 2, live*);
- `PreToolUse`'s `additionalContext` is collected for the model unless the
  answer is one it refuses (`pre_tool_use.rs`, `parse_completed`), as are
  `SessionStart`'s and `PostToolUse`'s; `Stop` and `SubagentStop` hold the turn
  on `decision: "block"` with a `reason` that isn't blank (`parse_stop`), and
  take no `additionalContext` that would tell the agent without a block: their
  outputs (`StopCommandOutputWire`,
  `SubagentStopCommandOutputWire`, `hooks/src/schema.rs`) hold the universal
  fields, `decision` and `reason`, with `deny_unknown_fields`, so an answer
  carrying `hookSpecificOutput` fails as "hook returned invalid stop hook JSON
  output" (`hooks/src/events/stop.rs`) and holds nothing. So a turn's end is
  held with a block here, a gap read again at `rust-v0.163.0`;
- what a hook tells whole is 10,000 bytes (`Codex.fits`): an
  `additionalContext` past its handler's `additionalContextLimit`, 2,500 tokens
  by default, and a turn's end's continuation past the same default, are kept
  in a file with a preview (`hooks/src/output_spill.rs`, `engine/mod.rs`'s
  `run_stop`), a token counted as 4 bytes (`utils/string/src/truncate.rs`,
  `approx_token_count`). The room's hooks don't raise the limit;
- `SubagentStop` carries `stop_hook_active` as `Stop` does
  (`subagent-stop.command.input`), so an end following a hold is let through.

Nothing reaches a Codex session idle between its turns, so the adapter has no
way to wake one (`woken` and `pushing` are none), a gap declared with its
evidence: what an MCP server sends unprompted is only logged
(`rmcp-client/src/logging_client_handler.rs`), and the app-server that could
start a turn (`turn/start`) runs inside the terminal's own process under
`--no-daemon`, out of reach. An item for an idle session waits for its next
turn: the operator typing in its terminal starts one, told it at
`UserPromptSubmit`.

Nor can lup see what Codex holds for a thread while one of its calls runs, so
a held call of lup's ends there on what reaches the inbox and on its time limit
alone (`queues` is none): a gap declared with its evidence, read at
`rust-v0.165.0` (`docs/field-notes.md`, *What a session holds queued*). What
arrives mid-call, the operator's words steered in with Enter among it, waits in
the process's memory (`InputQueue`, `core/src/session/input_queue.rs`) and
reaches the rollout only as the turn takes it up after the call returns
(`record_pending_input`, `core/src/session/turn.rs`); what's queued with Tab
waits in the TUI's until the turn ends; the app-server tells no other client of
either; and a background terminal's end queues nothing, the model learning of
it by polling.

Nor can lup's name for a session reach Codex's own title, at its start or at a
prompt after a rename, nor a `/rename` there reach lup: a gap declared with its
evidence. Codex names threads (`/rename`, its own generated titles, `codex
resume <name>`), but sets a name only through its app server's
`thread/name/set`, which runs inside the terminal's own process under
`--no-daemon`. Its hooks neither carry a thread's name nor set one, so none
takes a title (`Heard.takes_title`). Read in `hooks/src/schema.rs` at
`rust-v0.163.0`, the latest release on 2026-10-22: `UserPromptSubmit`'s input
(`UserPromptSubmitCommandInput`) carries the session, the turn, the agent, the
transcript, the directory, the model, the permission mode and the prompt, and
`SessionStart`'s the same less the turn, the agent and the prompt, plus its
`source`; `UserPromptSubmit`'s output (`UserPromptSubmitCommandOutputWire`)
takes the universal fields, `decision`, `reason` and a `hookSpecificOutput` of
`hookEventName` and `additionalContext` alone, and `SessionStart`'s the
universal fields and the same `hookSpecificOutput`, each refusing a field it
doesn't name (`deny_unknown_fields`). lup's names work on Codex everywhere in
lup; the title is Codex's own.

Nor does Codex isolate a subagent in a worktree of its own, so a worktree asked
for (`WorktreeAsked`) has no hook here, and lup makes none for a Codex worker:
a gap declared with its evidence, read at `rust-v0.164.0`, the latest release
on 2026-10-25. `spawn_agent` takes no working directory and no isolation
(`SpawnAgentArgs`, `core/src/tools/handlers/multi_agents/spawn.rs` and
`multi_agents_v2/spawn.rs`); a child's `cwd` is set to its parent turn's
(`apply_spawn_agent_runtime_overrides`, `core/src/agent/child_config.rs`); and
none of its 14 hook events makes a worktree (`HOOK_EVENT_NAMES`,
`hooks/src/lib.rs`), `SubagentStart` adding context alone. Codex makes a
worktree only for a whole session (`--worktree`,
`utils/cli/src/shared_options.rs`, and the TUI's `/worktree`), with its own
`git worktree add` (`worktree/src/lib.rs`), which no hook replaces. A Codex
subagent works in its parent's directory, and lup holds it in the session's one
worktree as every conversation of the session (above). So no spawn of Codex's
asks to work apart, and lup isolates none (`given`, `policy/checkpoint.py`): its
events never name the call that spawned a conversation (`spawned_by`).

What its judging relies on, from Codex's hooks documentation and its source at
`rust-v0.162.1` (paths under `codex-rs/`), whose hook schemas
(`hooks/schema/generated/`) are those of `rust-v0.156.1`, file for file; the
payloads 0.162.1 sent for a patch, a shell command and a turn's end are kept in
`packages/lup-dev/tests/payloads/codex-0.162.1/`:
- the inputs: `PreToolUse` and `PostToolUse` carry `tool_use_id`, `PostToolUse` its
  `tool_response`, `SubagentStop` its `agent_id`; a subagent's calls carry their
  `agent_id`; a turn's events carry its `turn_id`, which `PreToolUse` and
  `UserPromptSubmit` are read for; each carries more than this adapter reads
  (`model`, `permission_mode`, `transcript_path`);
- a patch's hooks name the tool `apply_patch` (a matcher of `Write` or `Edit`
  selects them too, the payload still saying `apply_patch`:
  `core/src/tools/hook_names.rs`), carry the patch as `tool_input.command`, and
  give both hooks the call's own id as `tool_use_id`
  (`core/src/tools/handlers/apply_patch.rs`), so a patch's start and finish match;
- `PostToolUse` runs only for a call that succeeded (`core/src/tools/registry.rs`):
  a patch that fails to apply, a call that's interrupted, and one another hook
  blocks have a `PreToolUse` and no `PostToolUse`. A shell command counts as
  succeeding whatever its exit status; one still running when its call returns
  has no `PostToolUse` then (`core/src/tools/context.rs`, `ExecCommandToolOutput`),
  but at the `write_stdin` poll that sees it end (below);
- a call's hooks carry as `cwd` the session's local working directory, or the
  turn's where there's none (`core/src/hook_runtime.rs`, `tool_hook_cwd`);
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
  own, under the original command's `tool_use_id`
  (`core/src/tools/handlers/unified_exec/write_stdin.rs`);
- a hook's `timeout` defaults to 600 seconds and has no maximum, so the hook
  configuration gives `PostToolUse` and `Stop` a day and more, for holds;
- "Subagent hooks use the parent session id" (its docs), a thread-spawned
  subagent's tool hooks carry its `agent_id`, and each of its turns ends with
  `SubagentStop` under the same `agent_id`, where a root turn runs `Stop`
  (`core/src/hook_runtime.rs`, `run_turn_stop_hooks`). `spawn_agent` "Returns the
  spawned agent id", and a parent waits only through `wait_agent`, so its turn can
  end while a subagent works;
- `Stop`'s `stop_hook_active` says "Whether this turn was already continued by
  `Stop`"; `SubagentStop`'s output takes `decision`, `reason` and `systemMessage`
  as `Stop`'s does (`subagent-stop.command.output`);
- how a hook's end reads (`hooks/src/events/`, each event's `parse_completed`):
  status 0 with nothing printed completes with no decision; any status but 0 or 2
  marks the run failed with the entry "hook exited with code <status>", and the
  call goes on; status 2 blocks where the event can, so the room's hook ends with
  it only where its connection to the host service was lost before an answer;
  `systemMessage` alone is a valid answer to every event this adapter
  hooks, shown as a warning entry.

Its release channel (`CodexChannel`) is the one its standalone installer reads
(`https://chatgpt.com/codex/install.sh`, which the repository's README gives,
read on 2026-10-13). The installer falls back to GitHub Releases when this one is
unavailable; a launch runs what's kept instead.
- `<releases>/channels/latest` describes the newest release, and
  `<releases>/releases/<version>/release.json` a given one, as GitHub's releases
  API does: its tag, `rust-v<version>`, and each file's name, address and
  `digest`, `sha256:<hex>`;
- the package for Linux on x86-64 is `codex-package-x86_64-unknown-linux-musl.tar.gz`:
  `codex-package.json`, naming the version, the target and the binary
  (`entrypoint`, `bin/codex`), with the helpers it finds beside it,
  `bin/codex-code-mode-host`, `codex-path/rg` and `codex-resources/bwrap`; the
  installer checks it against `codex-package_SHA256SUMS`, itself checked against
  its `digest`, which holds the same checksum as the package's own `digest`;
- each package also has a Sigstore bundle (`<package>.sigstore`), which lup
  doesn't check.
"""

import shlex
import tomllib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, get_args, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup import events
from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.settings import CodexSettings
from lup.rooms.homes import inside, lines, opened, plain
from lup.sessions.terminal import Cli, Hook
from lup.types import JsonObject, Model, Settings
from lup_dev.adapters import Adapter
from lup_dev.host import written
from lup_dev.host.courier import Heard, Spawned, Telling
from lup_dev.host.homes import Found, home_of, translated
from lup_dev.host.records import (
    Call,
    Called,
    Entry,
    Home,
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
    document,
    download,
    extract,
)
from lup_dev.layout import HomesLayout, HostLayout, Layout
from lup_dev.policy.checkpoint import (
    Bench,
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    first_warning,
)
from lup_dev.policy.report import judge_failed
from lup_dev.policy.runtime import Runtime
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from datetime import timedelta

    import httpx

    from lup.events import SessionEvent
    from lup.sessions.declaration import Declaration


# lup: defer(issue=52, why="Codex's spelling of a tool's name in a hook, a module constant until a `Spellings` each adapter implements gives it its home")
TOOL_PREFIX = f"mcp__{SERVER}__"
"""What Codex names each of lup's tools by in a hook: `mcp__lup__blocked`."""


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
    def inside(self) -> bool:
        return bool(Variables().codex_thread_id)

    @override
    def fits(self) -> int:
        """Return 10,000: Codex's default limit on a hook's context, 2,500 tokens of 4 bytes (see the module's docstring)."""
        return 10_000

    @override
    def settings(self) -> PurePosixPath:
        """Return `.codex`: a project's own layer of Codex's configuration."""
        return PurePosixPath(".codex")


class Output(Model, alias_generator=to_camel, populate_by_name=True):
    """What a hook prints for Codex, its fields in camel case."""


class SessionStartAnswer(Output):
    """What `SessionStart` adds to the conversation's context as it starts."""

    hook_event_name: Literal["SessionStart"] = "SessionStart"
    additional_context: str


class PostToolUseAnswer(Output):
    """What `PostToolUse` adds beside the call's result."""

    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    additional_context: str


class Specific(Output):
    """An answer in the `hookSpecificOutput` field."""

    hook_specific_output: SessionStartAnswer | PostToolUseAnswer


class Blocked(Output):
    """`Stop` or `SubagentStop` keeping the conversation going, and why."""

    decision: Literal["block"] = "block"
    reason: str


class OperatorWarning(Output):
    """A warning shown to the operator, not the agent, which lets the turn end.

    Codex's hooks docs: `Stop` "expects JSON on `stdout` when it exits `0`" and
    takes the common output fields, among them `systemMessage`, "Surfaced as a
    warning in the UI or event stream"; only `decision: "block"` continues the
    turn.
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


class Said(Output, extra="allow"):
    """Any answer a Codex hook prints, the judge's or none: what `told` reads and adds to.

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


# lup: defer(issue=245, why="a turn's end tells through a block, Codex's `Stop` and `SubagentStop` taking no `additionalContext` at `rust-v0.163.0`")
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
    """What every Codex hook receives on stdin, and how each answers."""

    session_id: str
    cwd: Path
    agent_id: str | None = None
    """The subagent the hook fires for; absent for the session's own conversation."""

    @abstractmethod
    def answer(self, bench: Bench) -> Output | None:
        """Act on the hook, and return what to print; none to print nothing."""

    @abstractmethod
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        """Return what to print when judging itself failed."""

    @abstractmethod
    def unanswered(self, said: str) -> Output:
        """Return what to print where lup's judge couldn't answer the hook at all, `said` saying why."""


type FreshStart = Literal["startup", "clear"]
"""The starts (`SessionStart`'s `source`) whose thread begins empty: started, or
cleared; a resume, a compaction or a fork carries one on (`Heard.fresh`)."""

type ForgettingStart = Literal["compact", "clear"]
"""The starts (`SessionStart`'s `source`) after which the thread holds none of
what it was told: a compaction summarizes it, and clearing empties it, so the
judge tells again the findings that still stand (`SessionStarted.forgotten`)."""


class SessionStart(Payload):
    """`SessionStart`: a session starts, resumes, or is cleared or compacted."""

    hook_event_name: Literal["SessionStart"]
    source: str | None = None
    """How it started: `startup`, `resume`, `clear`, `compact` or `fork`."""

    def heard(self, fits: int) -> Heard:
        """Read the session's start, and whether its thread begins empty (`FreshStart`): the judge reads it."""
        return Heard(
            event=events.SessionStarted(),
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            fits=fits,
            fresh=self.source in get_args(FreshStart.__value__) and not self.agent_id,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items as it starts."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Begin the session again in the worktree it holds, and tell its conversation what came due as it starts; the service adds its items after (`told`)."""
        reply = SessionStarted(
            session=self.session_id,
            agent=self.agent_id or "",
            cwd=self.cwd,
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
    """`UserPromptSubmit`: a turn starts on a prompt, the operator's typed in its terminal, or a prompt arrives in a turn.

    Its input carries the `prompt` and the `turn_id`
    (`user-prompt-submit.command.input`), and its output takes
    `hookSpecificOutput.additionalContext`, refusing any field it doesn't name
    (`UserPromptSubmitCommandOutputWire`, `hooks/src/schema.rs`). It runs for
    each input a turn takes (`inspect_pending_input`, `core/src/hook_runtime.rs`,
    at `rust-v0.163.0`), a message typed while the model runs among them, which
    the turn drains between its steps (`run_turn`, `core/src/session/turn.rs`),
    with that turn's own id (`turn_context.sub_id`), as every hook of the turn
    carries it.
    """

    hook_event_name: Literal["UserPromptSubmit"]
    prompt: str
    turn_id: str | None = None

    def heard(self, fits: int) -> Heard:
        """Read the turn's start, and the prompt it starts on: the judge reads it."""
        return Heard(
            event=events.TurnStarted(),
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            fits=fits,
            prompt=self.prompt,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items beside the prompt."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        """Stop counting the conversation's calls of an earlier turn: no `PostToolUse` reports the end of a call interrupted, and a prompt arriving in a turn carries that turn's id, so the turn's calls still running stay counted."""
        TurnStarted(
            session=self.session_id,
            agent=self.agent_id or "",
            cwd=self.cwd,
            turn=self.turn_id,
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


class PreToolUse(Payload):
    """`PreToolUse`: a tool call about to run."""

    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_use_id: str
    tool_input: JsonValue = None
    """The call's input: a command's or a patch's `command`, an MCP tool's
    arguments, or their text where that isn't JSON."""
    turn_id: str | None = None
    """The turn the call runs in, which a later turn's start says is over."""

    def heard(self, fits: int) -> Heard:
        """Read the call's start: the judge reads every one."""
        return Heard(
            event=events.CallStarted(call=self.tool_use_id, tool=self.tool_name),
            session=self.session_id,
            agent=self.agent_id,
            served=self.tool_name.startswith(TOOL_PREFIX),
            judged=True,
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items beside the call, and stamp a call to lup's tools with its caller.

        The stamp is `updatedInput` beside `permissionDecision: "allow"`, which
        Codex needs to apply it. A call the judge blocked never runs, and one
        whose arguments aren't a JSON object has nothing to carry the stamp, so
        neither is stamped.
        """
        told = context(said, self.hook_event_name, telling.items)
        given = told.hook_specific_output or Context(
            hook_event_name=self.hook_event_name
        )
        blocked = told.decision == "block" or given.permission_decision == "deny"
        if not self.tool_name.startswith(TOOL_PREFIX) or blocked:
            return told
        match self.tool_input:
            case dict():
                stamped = given.model_copy(
                    update={
                        "permission_decision": "allow",
                        "updated_input": stamp(
                            self.tool_input, telling.caller, self.tool_use_id
                        ),
                    }
                )
                return told.model_copy(update={"hook_specific_output": stamped})
            case _:
                return told

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
            turn=self.turn_id,
        ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None

    @override
    def unanswered(self, said: str) -> Output:
        return OperatorWarning(system_message=said)


class PostToolUse(Payload):
    """`PostToolUse`: a tool call finished."""

    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_use_id: str

    def heard(self, fits: int) -> Heard:
        """Read the call's finish: the judge reads every one."""
        return Heard(
            event=events.CallFinished(call=self.tool_use_id, tool=self.tool_name),
            session=self.session_id,
            agent=self.agent_id,
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
            agent=self.agent_id or "",
            cwd=self.cwd,
            call=self.tool_use_id,
            tool=self.tool_name,
        )
        reply = finished.apply(bench)
        if not reply.context:
            return None
        said = PostToolUseAnswer(additional_context=reply.context)
        return Specific(hook_specific_output=said)

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        said = PostToolUseAnswer(additional_context=failure_note(failure))
        return Specific(hook_specific_output=said)

    @override
    def unanswered(self, said: str) -> Output:
        """Tell the agent beside the call's result, as when judging fails: the checkpoint judged nothing."""
        told = PostToolUseAnswer(additional_context=f"{said}. Tell the operator.")
        return Specific(hook_specific_output=told)


class Stop(Payload):
    """`Stop`: the session's own conversation ends its turn.

    What the turn's end tells the agent holds it, as the `reason` of `decision:
    "block"`, which becomes "a new continuation prompt"; its docs list no
    `additionalContext` for `Stop`. An end that doesn't hold says nothing: only
    a judge's failure goes to the operator, in `systemMessage`.
    """

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""
    last_assistant_message: str | None = None
    """The agent's last message of the turn, as 0.162.1 sends it (`9-stop`)."""

    def heard(self, fits: int) -> Heard:
        """Read the turn's end: the judge reads it."""
        return Heard(
            event=events.TurnEnded(),
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the turn's end on the conversation's items, after any reason the judge holds it for."""
        return held(said, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = TurnEnded(
            session=self.session_id,
            agent="",
            cwd=self.cwd,
            after_block=self.stop_hook_active,
        )
        reply = ended.apply(bench)
        return Blocked(reason=reply.block) if reply.block else None

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
    """`SubagentStop`: a subagent's turn ends.

    Its output takes `decision: "block"` and `systemMessage` as `Stop`'s does
    (`subagent-stop.command.output`), and its input carries
    `last_assistant_message` and the subagent's own rollout as
    `agent_transcript_path` (`subagent-stop.command.input`, at `rust-v0.163.0`).
    It runs only where a turn completes (`run_turn_stop_hooks`, called from
    `run_turn` in `core/src/session/turn.rs`): a subagent stopped, or whose
    turn fails, runs none, and the `Interrupt` hook is a root turn's alone, so
    its parent isn't told (`docs/field-notes.md`, *A subagent's end*).
    """

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool = False
    """Whether the subagent's turn goes on because a `SubagentStop` hook blocked it already."""
    last_assistant_message: str | None = None
    """Its last message of the turn, where it left one."""

    def heard(self, fits: int) -> Heard:
        """Read a subagent's turn's end: the judge reads it."""
        return Heard(
            event=events.ConversationEnded(),
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
            said=self.last_assistant_message,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Hold the subagent's turn's end on its items, after any reason the judge holds it for."""
        return held(said, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        ended = ConversationEnded(
            session=self.session_id, agent=self.agent_id or "", cwd=self.cwd
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


type Received = Annotated[
    SessionStart | UserPromptSubmit | PreToolUse | PostToolUse | Stop | SubagentStop,
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
        output = received.failed(bench, failure)
    if output is None:
        return ""
    return output.model_dump_json(by_alias=True, exclude_none=True)


def unanswered(raw: str, failure: str) -> str:
    """Answer a hook lup's judge couldn't, saying `failure` in Codex's terms.

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


class SessionMeta(Model, extra="ignore"):
    """The part of a thread's `session_meta` lup reads of a subagent: its own id, its root's, its parent's, its path and its role (`protocol/src/protocol.rs`, `SessionMeta`, at `rust-v0.163.0`)."""

    id: str | None = None
    session_id: str | None = None
    parent_thread_id: str | None = None
    agent_path: str | None = None
    """`/root/<name>/…`: the subagent's name last, each ancestor's before it."""
    agent_role: str | None = None


class MetaLine(Model, extra="ignore"):
    """A rollout's first line, `{"type": "session_meta", "payload": …}`."""

    type: str
    payload: SessionMeta


class Subagented(Model, extra="ignore"):
    """Any hook's payload, as far as finding a subagent's record reads it."""

    session_id: str
    agent_id: str | None = None
    agent_type: str | None = None
    transcript_path: Path | None = None
    agent_transcript_path: Path | None = None
    """At `SubagentStop`, the subagent's own rollout, where `transcript_path` is
    its parent's."""


def spawned(raw: str, layout: Layout, largest: int = 1024 * 1024) -> Spawned | None:
    """Return how the subagent a Codex hook fires for was spawned, from its own rollout's first line; none for the session's own conversation.

    A subagent's hooks name its own rollout (`transcript_path`), whose
    `session_meta` gives its path, `/root/<parent>/<name>`, and its parent's
    thread; a parent that's the root is the session's own conversation. One
    spawned by the first version of `spawn_agent`, which takes no name, has no
    path, and so no name. Its end names its parent's rollout there (measured
    by the first lup on 0.158.0, `docs/field-notes.md`, *Subagents' records*)
    and its own as `agent_transcript_path`, read first, so a subagent first
    heard at its end is linked too; a rollout whose meta is another thread's
    says nothing of it.

    None is Codex's own (`Spawned.internal`): a hook names an agent only for a
    thread `spawn_agent` spawned (`thread_spawn_subagent_hook_context`,
    `core/src/hook_runtime.rs`), and its own threads, a review, the approvals'
    reviewer and the memory writer, are named by none (read at
    `rust-v0.163.0`, `docs/field-notes.md`, *A runtime's own agents*).

    Codex hands a subagent with a path its last message itself
    (`Spawned.handed`): as the subagent's turn completes, it queues a
    `FINAL_ANSWER` message holding it in its parent's mailbox
    (`notify_parent_of_terminal_turn`, `core/src/agent/control/completion.rs`).
    One without a path, the first `spawn_agent`'s, the one Codex turns on by
    default (`multi_agent` on, `multi_agent_v2` off, `features/src/lib.rs`), is
    handed nothing: its parent reads it only through `wait_agent`, so lup
    hands its last message on (`docs/field-notes.md`, *A subagent's end*).

    Every subagent reads the session's guidance, Codex's managed developer
    instructions: a spawned thread's configuration is its parent's, the
    requirements holding them among it, whatever its role
    (`core/src/agent/child_config.rs`, `build_agent_shared_config`;
    `core/src/agent/role.rs`, `build_config_layer_stack`), and every thread but
    a reviewer's of Codex's own is given them (`core/src/session/world_state.rs`),
    read at `rust-v0.163.0`.
    """
    payload = Subagented.model_validate_json(raw)
    if payload.agent_id is None:
        return None
    kind = payload.agent_type or None
    rollout = payload.agent_transcript_path or payload.transcript_path
    found = None if rollout is None else translated(layout, rollout)
    reading = None if found is None else opened(found.root, found.record)
    if reading is None:
        return Spawned(kind=kind, guided=True)
    with reading:
        line = reading.readline(largest + 1)
    try:
        first = MetaLine.model_validate_json(line)
    except ValidationError:
        return Spawned(kind=kind, guided=True)
    meta = first.payload
    if meta.id != payload.agent_id:
        return Spawned(kind=kind, guided=True)
    parent = (
        None if meta.parent_thread_id == payload.session_id else meta.parent_thread_id
    )
    return Spawned(
        name=None if meta.agent_path is None else PurePosixPath(meta.agent_path).name,
        parent=parent,
        kind=meta.agent_role or kind,
        guided=True,
        handed=meta.agent_path is not None,
    )


def heard(raw: str) -> Heard:
    """Read one Codex hook as the host service does: who's speaking, about which call, and that the judge reads it.

    Each hook's answer tells what Codex's limit allows whole (`Codex.fits`).
    Raise `ValidationError` where the payload isn't one of the hooks this
    adapter reads.
    """
    return TypeAdapter[Received](Received).validate_json(raw).heard(Codex().fits())


def told(raw: str, answer: str, telling: Telling) -> str | None:
    """Return what a Codex hook prints: `answer`, the judge's or none, with `telling` added; none where nothing is.

    Raise `ValidationError` where the payload isn't one of the hooks this adapter
    reads, or the answer isn't a hook's.
    """
    received = TypeAdapter[Received](Received).validate_json(raw)
    said = Said.model_validate_json(answer) if answer.strip() else Said()
    added = received.told(said, telling)
    if added == said:
        return None
    return added.model_dump_json(by_alias=True, exclude_none=True)


def hooks(
    command: Callable[[type[SessionEvent]], list[str]], timeout: timedelta
) -> list[Hook]:
    """Return the hooks a launched Codex session runs at the events the host service hears, each running the command `command` gives for its event.

    `SessionStart`; `UserPromptSubmit`, each turn's start, which clears the
    calls the conversation left in an earlier turn; `PreToolUse` and
    `PostToolUse` on every tool: Codex is judged after each call. `Stop` and `SubagentStop`: a conversation's
    turn's end clears the calls it left that no `PostToolUse` finishes (a patch
    that failed to apply, a call interrupted), and judges what the turn left.
    None at a worktree asked for, which Codex has no hook for (see the module's
    docstring). Each waits up to `timeout`, which a hold's wait for the
    operator needs.
    """
    heard: list[type[SessionEvent]] = [
        events.SessionStarted,
        events.TurnStarted,
        events.CallStarted,
        events.CallFinished,
        events.TurnEnded,
        events.ConversationEnded,
    ]
    return [
        Hook(event=event, command=command(event), timeout=timeout) for event in heard
    ]


def agent() -> Declaration:
    """Return the declaration a launched Codex session runs: no model, so Codex reads the operator's own."""
    return lup.Codex()


class Asset(Model):
    """A file of a release, as the channel lists it."""

    name: str
    browser_download_url: str
    digest: str
    """Its checksum, spelled `sha256:<hex>`."""


class Release(Model):
    """A release, as the channel describes it: its tag, and its files."""

    tag_name: str
    assets: list[Asset]


class Package(Model, alias_generator=to_camel, populate_by_name=True):
    """A package's own manifest, `codex-package.json`: what it holds, and where its binary is."""

    version: str
    target: str
    entrypoint: Path
    """The binary, from the package's directory."""


class CodexChannel(Channel):
    """Codex's release channel, read as its standalone installer reads it."""

    releases: str = "https://releases.openai.com/codex"
    """The channel's root: the newest release, and each release's description and files."""
    target: str = "x86_64-unknown-linux-musl"
    """The packages' name for Linux on x86-64, built static."""
    tag: str = "rust-v"
    """What a release's tag holds before its version."""
    manifest: str = "codex-package.json"
    """The package's own manifest, at its root."""

    @override
    def latest(self, client: httpx.Client) -> str:
        release = document(client, f"{self.releases}/channels/latest", Release)
        return self.version(release)

    @override
    def download(self, client: httpx.Client, version: str, into: Path) -> None:
        url = f"{self.releases}/releases/{version}/release.json"
        release = document(client, url, Release)
        if self.version(release) != version:
            message = f"{url} describes {release.tag_name}, not {version}"
            raise ChannelError(message)
        name = f"codex-package-{self.target}.tar.gz"
        found = [asset for asset in release.assets if asset.name == name]
        if not found:
            message = f"{url} lists no {name}"
            raise ChannelError(message)
        [asset] = found
        archive = into / name
        digest = download(client, asset.browser_download_url, archive)
        check(asset.browser_download_url, f"sha256:{digest}", asset.digest)
        extract(archive, into)
        archive.unlink()
        package = self.package(into)
        if package.version != version or package.target != self.target:
            message = (
                f"{name} of {version} holds {package.version} for {package.target}"
            )
            raise ChannelError(message)

    @override
    def cli(self, directory: Path) -> Cli:
        package = self.package(directory)
        return Cli(program=directory / package.entrypoint, directory=directory)

    def package(self, directory: Path) -> Package:
        """Read the manifest of the package in `directory`."""
        path = directory / self.manifest
        try:
            return Package.model_validate_json(path.read_text())
        except (OSError, ValidationError) as failed:
            message = f"{path} doesn't read as a package's manifest: {failed}"
            raise ChannelError(message) from failed

    def version(self, release: Release) -> str:
        """Return the version a release's tag names."""
        if not release.tag_name.startswith(self.tag):
            message = f"the release's tag, {release.tag_name}, doesn't start {self.tag}"
            raise ChannelError(message)
        return release.tag_name.removeprefix(self.tag)


class Started(Model, extra="ignore"):
    """What a Codex rollout's first line says of the session: where it ran."""

    class Meta(Model, extra="ignore"):
        """The session's own facts."""

        cwd: Path

    type: Literal["session_meta"]
    payload: Meta


class CodexRecords(Model, Records):
    """Codex's records: a rollout per session under `sessions/`, its first line saying where it ran.

    A launched session's is in the home its launch registered alone, as the
    host service kept it (`lup_dev.host.homes`), and any other's in the
    operator's home alone, so a room can't have one read from its own home
    under another thread's id. Rooms write a home, so the rollout is read
    inside it alone (`Found.root`). The records a module copies (`kept`) are
    each home's: the operator's, the repository's rooms' and the shared one's
    (`homes`).
    """

    home: Path
    """The operator's Codex home, `~/.codex` or `CODEX_HOME`."""
    host: HostLayout | None = None
    """Where the host service keeps each launched session's home; none looks
    in the operator's home alone."""
    homes: HomesLayout | None = None
    """The rooms' own homes, whose rollouts a module copies beside the
    operator's (`kept`); none keeps the operator's home's alone."""

    @override
    def conversation(self, session: str, agent: str | None) -> Found | None:
        """Return the rollout of one conversation, in its launch's home or the operator's home, with that home; none for an id that isn't a plain name, or for what isn't a file there. A subagent is a thread of its own, its id its rollout's, as a session's is, filed under its session's home."""
        thread = session if agent is None else agent
        if not plain(thread) or not plain(session):
            return None
        home = (
            None if self.host is None else home_of(self.host, Codex().name(), session)
        )
        root = self.home if home is None else home
        sessions = root / "sessions"
        if not sessions.is_dir():
            return None
        return next(
            (
                Found(record=each, root=root)
                for each in sorted(sessions.rglob(f"rollout-*-{thread}.jsonl"))
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
        """Return the rollouts under `sessions/` whose sessions ran under `under`, in each home keeping the repository's records: `sessions/` only where it's reached from its home without a link, each rollout's directory read off its head."""
        held = homes(self.home, self.homes, repository, Codex().name())
        return [record for home in held for record in kept_in(home, under)]


def session_at(place: PurePosixPath) -> str | None:
    """Return the thread whose own rollout is at `place` in one of Codex's homes, `sessions/…/rollout-<time>-<thread id>.jsonl`, the id a UUID, as `CodexRecords.conversation` finds it; none for any other place.

    >>> session_at(PurePosixPath("sessions/2026/10/28/rollout-2026-10-28T09-00-00-019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5b.jsonl"))
    '019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5b'
    >>> session_at(PurePosixPath("sessions/2026/10/28/rollout-x.jsonl")) is None
    True
    """
    match place.parts:
        case ("sessions", *_, file) if PurePosixPath(file).suffix == ".jsonl":
            stem = PurePosixPath(file).stem
        case _:
            return None
    # lup: ignore("string-slice", why="Codex names a rollout by its time and its thread's id, a UUID's 36 characters at the end of the name, which `uuid.UUID` then reads")
    thread = stem[-36:]
    try:
        uuid.UUID(thread)
    except ValueError:
        return None
    return thread if stem.endswith(f"-{thread}") else None


def resumed(arguments: list[str]) -> str | None:
    """Return the thread Codex's arguments resume, `resume <id>`, its subcommand first among a launch's own arguments, since lup's go before them; none where they resume none, or resume with `--last` or the picker.

    >>> resumed(["resume", "019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5b"])
    '019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5b'
    >>> resumed(["resume"]), resumed(["resume", "--last"]), resumed(["exec", "resume"])
    (None, None, None)
    """
    match arguments:
        case ["resume", thread, *_] if not thread.startswith("-"):
            return thread
        case _:
            return None


def kept_in(home: Home, under: list[Path]) -> list[Record]:
    """Return the rollouts in one of Codex's homes of the sessions that ran under `under`, each by its path under `sessions/`.

    `rglob` goes into no directory through a link, so each rollout is reached
    from `sessions/` without one but for its own name, which `head` reads only
    where it resolves inside its folder.
    """
    sessions = home.directory / "sessions"
    if not reached(home.directory, sessions) or not sessions.is_dir():
        return []
    return [
        Record(
            home=home.directory,
            whose=home.whose,
            place=PurePosixPath("sessions", rollout.relative_to(sessions)),
        )
        for rollout in sorted(sessions.rglob("rollout-*.jsonl"))
        if (ran := started_in(rollout)) is not None and within(ran, under)
    ]


def started_in(rollout: Path) -> Path | None:
    """Return the directory the session of `rollout` ran in, from its first line, within its head (`head`); none where it doesn't say."""
    first = next(iter(head(rollout)), "")
    try:
        return Started.model_validate_json(first).payload.cwd
    except ValidationError:
        return None


class ThreadStarted(Model, extra="ignore"):
    """A rollout's `session_meta`: the thread's id, where it ran, and the thread that spawned it, for a subagent's."""

    id: str
    cwd: Path | None = None
    parent_thread_id: str | None = None


class MetaRecord(Model, extra="ignore"):
    """A `session_meta` line."""

    type: Literal["session_meta"]
    payload: ThreadStarted


class Typed(Model, extra="ignore"):
    """`user_message`: what the operator typed, as a rollout of the legacy history mode records it (`protocol/src/protocol.rs`, `UserMessageEvent`, at `rust-v0.163.0`)."""

    type: Literal["user_message"]
    message: str


class Answered(Model, extra="ignore"):
    """`agent_message`: what the agent said, as the legacy history mode records it."""

    type: Literal["agent_message"]
    message: str


class Part(Model, extra="ignore"):
    """A part of an item's content: its text, where it has one."""

    text: str | None = None


class Item(Model, extra="ignore"):
    """An item a turn completed: `UserMessage` is what the operator typed, `AgentMessage` what the agent said (`protocol/src/items.rs`)."""

    type: str
    content: list[Part] = []

    def text(self) -> str:
        """Return its parts' text, in order."""
        return "\n".join(part.text for part in self.content if part.text is not None)


class Completed(Model, extra="ignore"):
    """`item_completed`: a turn's item, as the paginated history mode records it, the default of a session started at 0.163."""

    type: Literal["item_completed"]
    item: Item


class Renamed(Model, extra="ignore"):
    """`thread_name_updated`: the thread's name, as rollouts before 0.163 recorded it; 0.163 keeps it in `session_index.jsonl` instead."""

    type: Literal["thread_name_updated"]
    thread_name: str


class TokenUsage(Model, extra="ignore"):
    """What one request counted (`protocol/src/protocol.rs`, `TokenUsage`): its input, the cached part of it among it, its output, and the reasoning among that."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    def used(self) -> int:
        """Return the tokens the context holds after the request: the whole count but the reasoning, which the model keeps out of its context (`tokens_in_context_window`).

        >>> TokenUsage(input_tokens=1000, output_tokens=300, reasoning_output_tokens=200, total_tokens=1300).used()
        1100
        """
        return self.total_tokens - self.reasoning_output_tokens


class TokenInfo(Model, extra="ignore"):
    """What a `token_count` event says of the thread (`TokenUsageInfo`): the last request's count, and the model's context window."""

    last_token_usage: TokenUsage | None = None
    model_context_window: int | None = None


class TokenCounted(Model, extra="ignore"):
    """`token_count`: the thread's token usage, after each request; `info` is none on a turn that made no request."""

    type: Literal["token_count"]
    info: TokenInfo | None = None


class OtherEvent(Model, extra="ignore"):
    """Any other event."""

    type: str


class EventRecord(Model, extra="ignore"):
    """An `event_msg` line."""

    type: Literal["event_msg"]
    timestamp: datetime | None = None
    payload: Annotated[
        Typed | Answered | Completed | Renamed | TokenCounted | OtherEvent,
        Field(union_mode="left_to_right"),
    ]


class TurnSettings(Model, extra="ignore"):
    """What a `turn_context` line says of the turn: the model it runs."""

    model: str | None = None


class TurnRecord(Model, extra="ignore"):
    """A `turn_context` line."""

    type: Literal["turn_context"]
    payload: TurnSettings


class PlanStep(Model, extra="ignore"):
    """One step of the plan `update_plan` writes, and where it stands."""

    step: str
    status: Status


class PlanWritten(Model, extra="ignore"):
    """`update_plan`'s arguments: the whole plan, which replaces the one before."""

    plan: list[PlanStep]


class ToolCalled(Model, extra="ignore"):
    """A `function_call` or `custom_tool_call`: a tool, by its namespace and name (`protocol/src/models.rs`, `ResponseItem`), and its arguments, read for the call that writes the plan and for what each call did."""

    type: Literal["function_call", "custom_tool_call"]
    name: str
    namespace: str | None = None
    call_id: str | None = None
    """The call's id, which its hooks carry as `tool_use_id`."""
    arguments: str | None = None
    """A `function_call`'s arguments, as the model wrote them: JSON in a string."""
    input: str | None = None
    """A `custom_tool_call`'s input, the text the tool takes: a patch for
    `apply_patch`, a cell of code for `exec`."""

    def given(self) -> JsonValue:
        """Return what the call was given: a `function_call`'s arguments read as JSON, or as written where they don't read as it; a `custom_tool_call`'s text."""
        if self.arguments is None:
            return self.input
        try:
            return TypeAdapter[JsonValue](JsonValue).validate_json(self.arguments)
        except ValidationError:
            return self.arguments

    def gist(self) -> str | None:
        r"""Return what the call did, in a line: the files a patch touches, the command a shell runs, else its first argument, or its text's first line.

        >>> ToolCalled(type="custom_tool_call", name="apply_patch", input="*** Begin Patch\n*** Update File: src/review.ts\n@@\n*** End Patch").gist()
        'review.ts'
        >>> ToolCalled(type="function_call", name="exec_command", arguments='{"cmd": "rg -n gist", "workdir": "/w"}').gist()
        'rg -n gist'
        """
        given = self.given()
        match given:
            case str() if self.name == "apply_patch":
                return gist(
                    ", ".join(PurePosixPath(each).name for each in patched(given))
                )
            case {"input": str() as patch} if self.name == "apply_patch":
                return gist(
                    ", ".join(PurePosixPath(each).name for each in patched(patch))
                )
            case {"command": [*words]} if all(isinstance(each, str) for each in words):
                return gist(shlex.join(str(each) for each in words))
            case dict():
                return gist(first(given))
            case _:
                return gist(given)

    def planned(self) -> list[Task] | None:
        """Return the plan this call writes, where it's `update_plan` and its arguments read as one, each step numbered in order; none for any other call."""
        if self.name != "update_plan" or self.arguments is None:
            return None
        try:
            plan = PlanWritten.model_validate_json(self.arguments).plan
        except ValidationError:
            return None
        return [
            Task(id=str(at), subject=each.step, status=each.status)
            for at, each in enumerate(plan, start=1)
        ]

    def tool(self) -> str:
        """Return the tool's name as Codex shows it: its namespace before its name, but for the default one (`protocol/src/tool_name.rs`)."""
        if self.namespace is None or self.namespace in ["", "functions"]:
            return self.name
        return f"{self.namespace}{self.name}"


class ShellCalled(Model, extra="ignore"):
    """A `local_shell_call`: a command, with no tool's name, and what it runs (`LocalShellAction`)."""

    type: Literal["local_shell_call"]
    call_id: str | None = None
    action: JsonObject = {}

    def gist(self) -> str | None:
        """Return the command it runs, as a shell would read it; its action as JSON where it isn't a command."""
        match self.action:
            case {"command": [*words]} if all(isinstance(each, str) for each in words):
                return gist(shlex.join(str(each) for each in words))
            case _:
                return gist(self.action or None)


class OutputPart(Model, extra="ignore"):
    """A part of a call's output: its text, where it's text; an image otherwise."""

    type: str
    text: str | None = None


class ToolOutput(Model, extra="ignore"):
    """A `function_call_output` or `custom_tool_call_output`: what a call returned, by the call's id, as the model was given it, text or parts (`FunctionCallOutputPayload`)."""

    type: Literal["function_call_output", "custom_tool_call_output"]
    call_id: str
    output: str | list[OutputPart] = ""

    def said(self) -> str:
        """Return what the model was given, its parts one after another, an image said as such."""
        match self.output:
            case str() as text:
                return text
            case parts:
                return "\n".join(
                    part.text if part.text is not None else f"[{part.type}]"
                    for part in parts
                )


class OtherItem(Model, extra="ignore"):
    """Any other response item: a message, which the events say once, reasoning."""

    type: str


class ResponseRecord(Model, extra="ignore"):
    """A `response_item` line."""

    type: Literal["response_item"]
    timestamp: datetime | None = None
    payload: Annotated[
        ToolCalled | ShellCalled | ToolOutput | OtherItem,
        Field(union_mode="left_to_right"),
    ]


type Rolled = Annotated[
    MetaRecord | EventRecord | ResponseRecord | TurnRecord,
    Field(discriminator="type"),
]
"""A line of a rollout lup reads; the others it passes over."""


class CodexTranscripts(Model, Reader):
    """Codex's records, read: a rollout per thread under `sessions/`, a subagent's among them, which isn't a session of its own.

    Read from Codex's source at `rust-v0.163.0`, and measured on the rollouts
    lup keeps, 0.128.0 to 0.163.0 (`docs/field-notes.md`, *A thread's
    rollout*): the operator's words and the agent's are the events, which the
    legacy history mode writes as `user_message` and `agent_message`, and the
    paginated one, every kept thread's but a few subagents' of 0.144.3, as
    `item_completed`; the `response_item` messages repeat them, and carry
    injected context too, so they're passed over. Tools called are
    `response_item`s.
    """

    @override
    def sessions(self, copies: Path) -> list[Path]:
        threads = copies / "sessions"
        rollouts = sorted(threads.rglob("rollout-*.jsonl")) if threads.is_dir() else []
        return [each for each in rollouts if spawned_by(each) is None]

    @override
    def read(self, record: Path, root: Path | None = None) -> Transcript:
        lines = list(rolled(record, root))
        metas = [each.payload for each in lines if isinstance(each, MetaRecord)]
        names = [
            each.payload.thread_name
            for each in lines
            if isinstance(each, EventRecord) and isinstance(each.payload, Renamed)
        ]
        first = next(iter(metas), None)
        return Transcript(
            runtime=Codex().name(),
            session=record.stem if first is None else first.id,
            title=names[-1] if names else None,
            directory=None if first is None else first.cwd,
            entries=[entry for each in lines for entry in stepped(each)],
            usage=usage(lines),
            tasks=planned(lines),
        )

    @override
    def calls(
        self, record: Path, ids: list[str], root: Path | None = None
    ) -> list[Call]:
        """Read calls whole: each one's input from the `response_item` calling it, and its output from the one answering it, by the call's id; Codex keeps no mark of a call that failed beside its output."""
        lines = list(rolled(record, root))
        given: dict[str, JsonValue] = {
            payload.call_id: (
                payload.given() if isinstance(payload, ToolCalled) else payload.action
            )
            for line in lines
            if isinstance(line, ResponseRecord)
            and isinstance(payload := line.payload, ToolCalled | ShellCalled)
            and payload.call_id is not None
            and payload.call_id in ids
        }
        returned = {
            line.payload.call_id: line.payload.said()
            for line in lines
            if isinstance(line, ResponseRecord)
            and isinstance(line.payload, ToolOutput)
            and line.payload.call_id in ids
        }
        return [
            Call(id=each, input=given[each], output=returned.get(each))
            for each in ids
            if each in given
        ]


def patched(patch: str) -> list[str]:
    r"""Return the files a patch in Codex's own format touches, by the header naming each: added, updated or deleted (`apply-patch/src/parser.rs`).

    >>> patched("*** Begin Patch\n*** Add File: a.py\n+x\n*** Delete File: b.py\n*** End Patch")
    ['a.py', 'b.py']
    """
    heads = ["*** Add File: ", "*** Update File: ", "*** Delete File: "]
    return [
        line.removeprefix(head)
        for line in patch.splitlines()
        for head in heads
        if line.startswith(head)
    ]


def usage(lines: list[Rolled]) -> Usage | None:
    """Return what the thread's context held after its last request, from the last `token_count` event that counted one, and the model the last turn ran; none where no event counted.

    Read from Codex's source at `rust-v0.163.0`, and measured on 0.163.0's
    rollouts (`docs/field-notes.md`, *A thread's rollout*).
    """
    counted = [
        each.payload.info
        for each in lines
        if isinstance(each, EventRecord)
        and isinstance(each.payload, TokenCounted)
        and each.payload.info is not None
        and each.payload.info.last_token_usage is not None
    ]
    models = [
        each.payload.model
        for each in lines
        if isinstance(each, TurnRecord) and each.payload.model is not None
    ]
    if not counted:
        return None
    last = counted[-1]
    return Usage(
        used=0 if last.last_token_usage is None else last.last_token_usage.used(),
        window=last.model_context_window,
        model=models[-1] if models else None,
    )


def planned(lines: list[Rolled]) -> list[Task]:
    """Return the thread's plan as it stands at the rollout's end: the last `update_plan` call's, each replacing the one before; empty where it wrote none."""
    plans = [
        plan
        for each in lines
        if isinstance(each, ResponseRecord)
        and isinstance(each.payload, ToolCalled)
        and (plan := each.payload.planned()) is not None
    ]
    return plans[-1] if plans else []


def rolled(record: Path, root: Path | None = None) -> Iterator[Rolled]:
    """Yield each line of a rollout lup reads, passing over the others, any that isn't JSON, and any too long to hold (`lup.rooms.homes.lines`); with `root`, read only where, opened, the rollout is inside it, nothing otherwise."""
    reading = TypeAdapter[Rolled](Rolled)
    written = record.open("rb") if root is None else opened(root, record)
    if written is None:
        return
    with written:
        for raw in lines(written):
            try:
                yield reading.validate_json(raw.decode(errors="replace"))
            except ValidationError:
                continue


def spawned_by(rollout: Path) -> str | None:
    """Return the thread that spawned a rollout's, from its first line; none for a session's own thread."""
    first = next(rolled(rollout), None)
    match first:
        case MetaRecord(payload=ThreadStarted(parent_thread_id=parent)):
            return parent
        case _:
            return None


def stepped(line: Rolled) -> list[Entry]:
    """Return the steps one rollout line holds: the operator's words, the agent's, a tool called."""
    match line:
        case EventRecord(payload=Typed(message=text), timestamp=at):
            return [Spoken(by="operator", text=text, at=at)]
        case EventRecord(payload=Answered(message=text), timestamp=at):
            return [Spoken(by="agent", text=text, at=at)]
        case EventRecord(
            payload=Completed(item=Item(type="UserMessage") as item), timestamp=at
        ):
            return [Spoken(by="operator", text=item.text(), at=at)]
        case EventRecord(
            payload=Completed(item=Item(type="AgentMessage") as item), timestamp=at
        ):
            return [Spoken(by="agent", text=item.text(), at=at)]
        case ResponseRecord(payload=ToolCalled() as called, timestamp=at):
            return [
                Called(tool=called.tool(), gist=called.gist(), id=called.call_id, at=at)
            ]
        case ResponseRecord(payload=ShellCalled(call_id=id_) as shell, timestamp=at):
            return [Called(tool="shell", gist=shell.gist(), id=id_, at=at)]
        case _:
            return []


class HostServer(Model, extra="ignore"):
    """One of the operator's own MCP servers: the command a host session starts it with, or where it's reached."""

    command: str | None = None
    args: list[str] = []
    url: str | None = None


class HostEnvironment(Model, extra="ignore"):
    """What the operator's configuration sets in every command's environment."""

    variables: dict[str, JsonValue] = Field(default={}, alias="set")


class HostProvider(Model, extra="ignore"):
    """A model provider of the operator's: where a host session sends its requests."""

    base_url: str | None = None


class HostProject(Model, extra="ignore"):
    """A project the operator's configuration names: whether it's trusted."""

    trust_level: str | None = None


class HostConfig(Model, extra="ignore"):
    """What of the operator's own `config.toml`, or one of its profiles, a host session runs, sets, sends to or does without asking, read in Codex's `config` docs (2026-10-28) for the check of what rooms could have written there."""

    notify: list[str] = []
    mcp_servers: dict[str, HostServer] = {}
    shell_environment_policy: HostEnvironment = HostEnvironment()
    model_providers: dict[str, HostProvider] = {}
    approval_policy: JsonValue = None
    sandbox_mode: str | None = None
    projects: dict[str, HostProject] = {}
    profiles: dict[str, HostConfig] = {}

    def said(self, places: written.Places) -> list[str]:
        """Say what it has a host session run, set, send to and do without asking, its profiles' too, each command flagged where it names a directory rooms write."""
        runs = [
            *(
                [f"its `notify`, {written.quoted(shlex.join(self.notify), places)}"]
                if self.notify
                else []
            ),
            *(
                f"the MCP server `{name}`, "
                + written.quoted(shlex.join([server.command, *server.args]), places)
                for name, server in self.mcp_servers.items()
                if server.command is not None
            ),
        ]
        variables = self.shell_environment_policy.variables
        sent = [
            f"`{provider.base_url}` (the provider `{name}`)"
            for name, provider in self.model_providers.items()
            if provider.base_url is not None
        ]
        trusted = [
            path
            for path, project in self.projects.items()
            if project.trust_level == "trusted"
        ]
        unasked = [
            *(
                [f"`approval_policy` is `{self.approval_policy}`"]
                if self.approval_policy == "never"
                else []
            ),
            *(
                [f"`sandbox_mode` is `{self.sandbox_mode}`"]
                if self.sandbox_mode == "danger-full-access"
                else []
            ),
            *(
                [f"trusts {written.counted(len(trusted), 'project', 'projects')}"]
                if trusted
                else []
            ),
        ]
        return [
            *([f"runs on the host {'; '.join(runs)}"] if runs else []),
            *(
                [
                    "sets in every command's environment "
                    + ", ".join(f"`{name}`" for name in variables)
                ]
                if variables
                else []
            ),
            *([f"sends its requests to {', '.join(sent)}"] if sent else []),
            *(
                [f"lets a host session act without asking: {'; '.join(unasked)}"]
                if unasked
                else []
            ),
            *(
                f"its profile `{name}` {each}"
                for name, profile in self.profiles.items()
                for each in profile.said(places)
            ),
        ]


class CodexWritten(Model):
    """What a host Codex session acts on in the operator's own Codex home, which every room on Codex could write before rooms had homes of their own, checked as it stands (`lup_dev.host.written`).

    Each item read in Codex's docs (2026-10-28) and measured on 0.162.0
    (`docs/field-notes.md`, *A home of the rooms' own*): its configuration,
    hooks and instructions; what it loads; what it runs before its commands,
    its shell snapshots and the helpers it puts first on their `PATH`; and the
    login every room on Codex could read.
    """

    home: Path
    """The operator's Codex home, `~/.codex` or `CODEX_HOME`."""
    loaded: list[str] = ["rules", "prompts", "skills"]
    """The directories whose files a host session loads; `rules/` can let it
    run a command without asking."""
    instructions: list[str] = ["AGENTS.md", "AGENTS.override.md"]
    configuration: list[str] = [
        "config.toml",
        "hooks.json",
        "AGENTS.md",
        "AGENTS.override.md",
        "rules",
        "prompts",
        "skills",
    ]
    """Where Codex makes no link itself: one found there is said."""
    before: list[str] = ["shell_snapshots", "tmp"]
    """What a session runs before its commands: its shell snapshot, and the
    helpers it puts first on their `PATH`."""

    def checked(self, places: written.Places) -> written.Checked:
        """Say what a host session acts on in the home, a line each: what's there, what of it looks planted, and what to do, the login apart."""
        return written.Checked.of(
            [
                self.config(places),
                self.hooks(places),
                written.Checked(
                    found=[
                        *self.read_instructions(),
                        *self.loads(),
                        *self.links(places),
                        *self.run_before(places),
                    ]
                ),
            ],
            login=self.login(),
        )

    def config(self, places: written.Places) -> written.Checked:
        """Say what the configuration has a host session run, set, send to and do without asking; fine where it does none of it."""
        path = self.home / "config.toml"
        if not path.exists() and not path.is_symlink():
            return written.Checked()
        held = written.read(path)
        if held is None:
            return written.Checked(
                found=[
                    (
                        "`config.toml` isn't a regular file lup reads, or is past 4 "
                        "MiB: look at it yourself."
                    )
                ]
            )
        try:
            config = HostConfig.model_validate(tomllib.loads(held.decode()))
        except tomllib.TOMLDecodeError, UnicodeDecodeError, ValidationError:
            return written.Checked(
                found=[
                    "`config.toml` isn't configuration lup reads: look at it yourself."
                ]
            )
        said = config.said(places)
        if not said:
            return written.Checked(
                fine=[
                    (
                        "`config.toml`: nothing in it runs a command, sets a variable, "
                        "sends requests elsewhere, or lets a session act without "
                        "asking."
                    )
                ]
            )
        return written.Checked(
            found=[
                f"`config.toml` {'; it '.join(said)}. Each is yours only if you set it."
            ]
        )

    def hooks(self, places: written.Places) -> written.Checked:
        """Say each command the hooks have a host session run; fine where they hold none."""
        path = self.home / "hooks.json"
        if not path.exists() and not path.is_symlink():
            return written.Checked()
        held = written.read(path)
        try:
            hooked = (
                None
                if held is None
                else TypeAdapter[JsonValue](JsonValue).validate_json(held)
            )
        except ValidationError:
            hooked = None
        if hooked is None:
            return written.Checked(
                found=["`hooks.json` isn't hooks lup reads: look at it yourself."]
            )
        commands = written.commands(hooked)
        if not commands:
            return written.Checked(fine=["`hooks.json`: no command in it."])
        return written.Checked(
            found=[
                "`hooks.json` runs on the host "
                + "; ".join(written.quoted(each, places) for each in commands)
                + ". Each is yours only if you set it."
            ]
        )

    def read_instructions(self) -> list[str]:
        """Say the instructions every host session reads."""
        return [
            f"`{name}`, {written.counted(len(held.splitlines()), 'line', 'lines')}, "
            "is read into every host session: check it's all yours."
            for name in self.instructions
            if (held := written.read(self.home / name)) is not None
        ]

    def loads(self) -> list[str]:
        """Say each directory whose files a host session loads."""
        loaded = [
            f"`{name}/` ({written.counted(len(found), 'file', 'files')})"
            for name in self.loaded
            if (found := written.listed(self.home / name).files)
        ]
        if not loaded:
            return []
        return [
            (
                f"{', '.join(loaded)}: a host session loads each, and `rules/` can let "
                "it run a command without asking: check they're yours."
            )
        ]

    def links(self, places: written.Places) -> list[str]:
        """Say each link among what a host session loads, where Codex makes none, flagged where it lands in a directory rooms write."""
        return [
            f"`{each.path.relative_to(self.home)}` is a link to `{each.aimed}`"
            + (
                ", in a directory rooms write"
                if places.aims(each.path, each.aimed)
                else ""
            )
            + ": Codex makes none there, so check it's yours."
            for name in self.configuration
            for each in written.listed(self.home / name).links
        ]

    def run_before(self, places: written.Places) -> list[str]:
        """Say what a host session runs before its commands, which rooms could have written."""
        shown = places.shown(self.home)
        there = [name for name in self.before if written.listed(self.home / name).files]
        if not there:
            return []
        return [
            f"{' and '.join(f'`{name}/`' for name in there)}: a host session runs "
            "its shell snapshot and the helpers it puts first on its commands' "
            "`PATH` from them, and a room could have written any: with no host "
            "session running, "
            + "; ".join(f"`rm -r {shown}/{name}/*`" for name in there)
            + "; a session makes its own as it starts."
        ]

    def login(self) -> str | None:
        """Say how to replace the operator's own login, which every room on Codex could read; none where there's none."""
        if not written.held(self.home / "auth.json"):
            return None
        return (
            "Your host login, `auth.json`, was readable by every room on Codex: on "
            "the host, run `codex logout` then `codex login`, so the refresh token "
            "they could read is replaced. Whether `codex logout` revokes it with "
            "the provider isn't documented."
        )


def login(directory: Path) -> Path:
    """Return where Codex keeps its login in a home of its own at `directory`, as `CODEX_HOME` names one: `auth.json` there, as in the operator's."""
    return CodexLayout(home=directory, operator_home=directory).operator_login


def adapter() -> Adapter:
    """Return what lup needs of Codex: its hooks answered, and its launch."""
    home = CodexLayout.of(CodexSettings()).operator_home
    machine = Layout.of(LupDevSettings())
    return Adapter(
        runtime=Codex(),
        hook=hook,
        unanswered=unanswered,
        heard=heard,
        told=told,
        spawned=spawned,
        woken=None,
        pushing=None,
        hooks=hooks,
        channel=CodexChannel(),
        agent=agent,
        login=login,
        records=CodexRecords(home=home, host=machine.host, homes=machine.homes),
        directory=home,
        written=CodexWritten(home=home).checked,
        recorded=session_at,
        resumed=resumed,
        reader=CodexTranscripts(),
        queues=None,
    )
