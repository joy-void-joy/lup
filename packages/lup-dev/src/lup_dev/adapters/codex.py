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
ask, so an ask is held at the checkpoint, as on every runtime, the agent waiting
inside the hook until the operator answers the item it is in their inbox. The
agent hears a
checkpoint's report as `additionalContext` beside the call's result, and the result
reaches it untouched.

A Codex session holds only the worktree it started in, a declared gap until rooms
(`docs/judging-writes.md`, *Every worktree of the repository*): its hooks' `cwd` is
the "Working directory for the session", and `Bash` and `apply_patch` carry only
`tool_input.command` (its hooks docs), which lup doesn't parse. Under its
`workspace-write` sandbox a write elsewhere lies outside the writable roots, so
Codex's own approval decides it.

In a launched room (`docs/launch.md`, *The one hook and the host service*), Codex
runs the room's hook on `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop` and
`SubagentStop` (`hooks`): the checkpoint after each call, the only place its
hooks see a patch, and each conversation's turn's end, which clears the calls it
left that no `PostToolUse` finishes. That end is the judge's whole set's
(`docs/judging-writes.md`, *The turn's end*): the session's `Stop` runs a
checkpoint, waits for the importers pass, and holds the turn (`decision:
"block"`, a continuation prompt to Codex) on the type errors and ruff's findings
left in the files its own conversation touched, until the same findings follow a
block (`stop_hook_active`), when the turn ends and the operator is told in
`systemMessage`; a refusal, a move, an answer to a hold, removed notes and mail
hold it once each. A subagent's `SubagentStop` never holds on findings, only on
what it must be told. Where
the launch's judge can't answer a hook, the host service answers it through
`unanswered`: at `PostToolUse` the agent is told beside the call's result, as when
judging fails; anything else warns the operator in `systemMessage`, and the call
goes on. Where the room's hook can't reach the service, it ends with status 1:
Codex marks the hook's run failed, shows "hook exited with code 1" (not what the
hook wrote to standard error), and the call goes on.

The judge reads every hook a launched Codex session runs (`heard`), so the host
service answers none itself. It adds to each answer through `told`: a call to
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
  `allow` it "was dropped — the call ran as the model wrote it"; owed live on
  0.162.1 (`docs/field-notes.md`, *Piece 2, live*);
- `PreToolUse`'s `additionalContext` is collected for the model unless the
  answer is one it refuses (`pre_tool_use.rs`, `parse_completed`), as are
  `SessionStart`'s and `PostToolUse`'s; `Stop` and `SubagentStop` hold the turn
  on `decision: "block"` with a `reason` that isn't blank (`parse_stop`);
- what a hook tells whole is 10,000 bytes (`heard`'s `fits`): an
  `additionalContext` past its handler's `additionalContextLimit`, 2,500 tokens
  by default, and a turn's end's continuation past the same default, are kept
  in a file with a preview (`hooks/src/output_spill.rs`, `engine/mod.rs`'s
  `run_stop`), a token counted as 4 bytes (`utils/string/src/truncate.rs`,
  `approx_token_count`). The room's hooks don't raise the limit;
- `SubagentStop` carries `stop_hook_active` as `Stop` does
  (`subagent-stop.command.input`), so an end following a hold is let through.

Nothing reaches a Codex session idle between its turns, so the adapter has no
way to wake one (`woken` is none), a gap declared with its evidence: what an MCP
server sends unprompted is only logged (`rmcp-client/src/logging_client_handler.rs`),
and the app-server that could start a turn (`turn/start`) runs inside the
terminal's own process under `--no-daemon`, out of reach. An item for an idle
session waits for its next call; the operator typing in its terminal starts one.

What its judging relies on, from Codex's hooks documentation and its source at
`rust-v0.162.1` (paths under `codex-rs/`), whose hook schemas
(`hooks/schema/generated/`) are those of `rust-v0.156.1`, file for file; the
payloads 0.162.1 sent for a patch, a shell command and a turn's end are kept in
`packages/lup-dev/tests/payloads/codex-0.162.1/`:
- the inputs: `PreToolUse` and `PostToolUse` carry `tool_use_id`, `PostToolUse` its
  `tool_response`, `SubagentStop` its `agent_id`; a subagent's calls carry their
  `agent_id`; each carries more than this adapter reads (`model`,
  `permission_mode`, `transcript_path`, and on a turn's events `turn_id`);
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
  call goes on; status 2 blocks where the event can, so the room's hook never ends
  with it; `systemMessage` alone is a valid answer to every event this adapter
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

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.settings import CodexSettings
from lup.sessions.terminal import Cli, Hook
from lup.types import JsonObject, Model, Settings
from lup_dev.adapters import Adapter
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
    document,
    download,
    extract,
)
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


class SessionStart(Payload):
    """`SessionStart`: a session starts, resumes, or is cleared or compacted."""

    hook_event_name: Literal["SessionStart"]

    def heard(self, fits: int) -> Heard:
        """Read the session's start: the judge reads it."""
        return Heard(
            event="session-started",
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            fits=fits,
        )

    def told(self, said: Said, telling: Telling) -> Said:
        """Tell the conversation its items as it starts."""
        return context(said, self.hook_event_name, telling.items)

    @override
    def answer(self, bench: Bench) -> Output | None:
        SessionStarted(
            session=self.session_id, agent=self.agent_id or "", cwd=self.cwd
        ).apply(bench)
        return None

    @override
    def failed(self, bench: Bench, failure: Exception) -> Output | None:
        return None

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

    def heard(self, fits: int) -> Heard:
        """Read the call's start: the judge reads every one.

        A call spawning a subagent isn't heard as one, since its caller can't
        be asked to name what it spawns: the first version of `spawn_agent`
        takes no name (`create_spawn_agent_tool_v1`,
        `core/src/tools/handlers/multi_agents_spec.rs`, at `rust-v0.163.0`),
        and the second requires `task_name`. A subagent the first spawns is
        asked to name itself (`spawned`).
        """
        return Heard(
            event="call-started",
            session=self.session_id,
            agent=self.agent_id,
            call=self.tool_use_id,
            tool=self.tool_name,
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
            event="call-finished",
            session=self.session_id,
            agent=self.agent_id,
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

    What the turn's end tells without holding it goes to the operator, in
    `systemMessage`: its docs list no `additionalContext` for `Stop`, and a
    `reason` with `decision: "block"` becomes "a new continuation prompt".
    """

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool = False
    """Whether the turn goes on because a `Stop` hook blocked it already."""
    last_assistant_message: str | None = None
    """The agent's last message of the turn, as 0.162.1 sends it (`9-stop`)."""

    def heard(self, fits: int) -> Heard:
        """Read the turn's end: the judge reads it."""
        return Heard(
            event="turn-ended",
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
    """`SubagentStop`: a subagent's turn ends.

    Its output takes `decision: "block"` and `systemMessage` as `Stop`'s does
    (`subagent-stop.command.output`).
    """

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool = False
    """Whether the subagent's turn goes on because a `SubagentStop` hook blocked it already."""

    def heard(self, fits: int) -> Heard:
        """Read a subagent's turn's end: the judge reads it."""
        return Heard(
            event="conversation-ended",
            session=self.session_id,
            agent=self.agent_id,
            judged=True,
            after_block=self.stop_hook_active,
            fits=fits,
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


def spawned(raw: str) -> Spawned | None:
    """Return how the subagent a Codex hook fires for was spawned, from its own rollout's first line; none for the session's own conversation.

    A subagent's hooks name its own rollout (`transcript_path`), whose
    `session_meta` gives its path, `/root/<parent>/<name>`, and its parent's
    thread; a parent that's the root is the session's own conversation. One
    spawned by the first version of `spawn_agent`, which takes no name, has no
    path, and so no name. Its end names the root's rollout instead (measured
    by the first lup on 0.158.0, `docs/field-notes.md`, *Subagents' records*),
    so a rollout whose meta is another thread's says nothing of it.
    """
    payload = Subagented.model_validate_json(raw)
    if payload.agent_id is None:
        return None
    kind = payload.agent_type or None
    rollout = payload.transcript_path
    if rollout is None or not rollout.is_file():
        return Spawned(kind=kind)
    with rollout.open() as lines:
        first = MetaLine.model_validate_json(lines.readline())
    meta = first.payload
    if meta.id != payload.agent_id:
        return Spawned(kind=kind)
    parent = (
        None if meta.parent_thread_id == payload.session_id else meta.parent_thread_id
    )
    return Spawned(
        name=None if meta.agent_path is None else PurePosixPath(meta.agent_path).name,
        parent=parent,
        kind=meta.agent_role or kind,
    )


def heard(raw: str, fits: int = 10_000) -> Heard:
    """Read one Codex hook as the host service does: who's speaking, about which call, and that the judge reads it.

    Each hook's answer tells `fits` bytes whole: Codex's default limit on a
    hook's context, 2,500 tokens of 4 bytes. Raise `ValidationError` where the
    payload isn't one of the hooks this adapter reads.
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


def hooks(command: list[str], timeout: timedelta) -> list[Hook]:
    """Return the hooks a launched Codex session runs `command` at: the events the judge reads.

    `SessionStart`, `PreToolUse` and `PostToolUse` on every tool: Codex is judged
    after each call. `Stop` and `SubagentStop`: a conversation's turn's end clears
    the calls it left that no `PostToolUse` finishes (a patch that failed to
    apply, a call interrupted), and judges what the turn left. Each waits up to
    `timeout`, which a hold's wait for the operator needs.
    """
    events: list[Event] = [
        "session-started",
        "call-started",
        "call-finished",
        "turn-ended",
        "conversation-ended",
    ]
    return [Hook(event=event, command=command, timeout=timeout) for event in events]


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
    """Codex's records: a rollout per session under `sessions/`, its first line saying where it ran."""

    home: Path
    """The operator's Codex home, `~/.codex` or `CODEX_HOME`."""

    @override
    def conversation(self, session: str, agent: str | None) -> Path | None:
        # A subagent is a thread of its own, its id its rollout's, as a session's is.
        sessions = self.home / "sessions"
        thread = session if agent is None else agent
        found = (
            sorted(sessions.rglob(f"rollout-*-{thread}.jsonl"))
            if sessions.is_dir()
            else []
        )
        return next(iter(found), None)

    @override
    def kept(self, under: list[Path]) -> list[Record]:
        sessions = self.home / "sessions"
        rollouts = (
            sorted(sessions.rglob("rollout-*.jsonl")) if sessions.is_dir() else []
        )
        return [
            Record(
                source=rollout,
                place=PurePosixPath("sessions", rollout.relative_to(sessions)),
            )
            for rollout in rollouts
            if (ran := started_in(rollout)) is not None and within(ran, under)
        ]


def started_in(rollout: Path) -> Path | None:
    """Return the directory the session of `rollout` ran in, from its first line; none where it doesn't say."""
    with rollout.open(encoding="utf-8", errors="replace") as lines:
        first = lines.readline()
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


class OtherEvent(Model, extra="ignore"):
    """Any other event."""

    type: str


class EventRecord(Model, extra="ignore"):
    """An `event_msg` line."""

    type: Literal["event_msg"]
    timestamp: datetime | None = None
    payload: Annotated[
        Typed | Answered | Completed | Renamed | OtherEvent,
        Field(union_mode="left_to_right"),
    ]


class ToolCalled(Model, extra="ignore"):
    """A `function_call` or `custom_tool_call`: a tool, by its namespace and name (`protocol/src/models.rs`, `ResponseItem`)."""

    type: Literal["function_call", "custom_tool_call"]
    name: str
    namespace: str | None = None
    call_id: str | None = None
    """The call's id, which its hooks carry as `tool_use_id`."""

    def tool(self) -> str:
        """Return the tool's name as Codex shows it: its namespace before its name, but for the default one (`protocol/src/tool_name.rs`)."""
        if self.namespace is None or self.namespace in ["", "functions"]:
            return self.name
        return f"{self.namespace}{self.name}"


class ShellCalled(Model, extra="ignore"):
    """A `local_shell_call`: a command, with no tool's name."""

    type: Literal["local_shell_call"]
    call_id: str | None = None


class OtherItem(Model, extra="ignore"):
    """Any other response item: a message, which the events say once, reasoning."""

    type: str


class ResponseRecord(Model, extra="ignore"):
    """A `response_item` line."""

    type: Literal["response_item"]
    timestamp: datetime | None = None
    payload: Annotated[
        ToolCalled | ShellCalled | OtherItem, Field(union_mode="left_to_right")
    ]


type Rolled = Annotated[
    MetaRecord | EventRecord | ResponseRecord, Field(discriminator="type")
]
"""A line of a rollout lup reads; the others it passes over."""


class CodexTranscripts(Model, Reader):
    """Codex's records, read: a rollout per thread under `sessions/`, a subagent's among them, which isn't a session of its own.

    Read from Codex's source at `rust-v0.163.0` (`docs/field-notes.md`, *A
    thread's rollout*): the operator's words and the agent's are the events,
    which the legacy history mode writes as `user_message` and `agent_message`,
    and the paginated one, the default from 0.163, as `item_completed`; the
    `response_item` messages repeat them, and carry injected context too, so
    they're passed over. Tools called are `response_item`s.
    """

    @override
    def sessions(self, copies: Path) -> list[Path]:
        threads = copies / "sessions"
        rollouts = sorted(threads.rglob("rollout-*.jsonl")) if threads.is_dir() else []
        return [each for each in rollouts if spawned_by(each) is None]

    @override
    def read(self, record: Path) -> Transcript:
        lines = list(rolled(record))
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
        )


def rolled(record: Path) -> Iterator[Rolled]:
    """Yield each line of a rollout lup reads, passing over the others and any that isn't JSON."""
    reading = TypeAdapter[Rolled](Rolled)
    with record.open(encoding="utf-8", errors="replace") as written:
        for raw in written:
            try:
                yield reading.validate_json(raw)
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
            return [Called(tool=called.tool(), id=called.call_id, at=at)]
        case ResponseRecord(payload=ShellCalled(call_id=id_), timestamp=at):
            return [Called(tool="shell", id=id_, at=at)]
        case _:
            return []


def adapter() -> Adapter:
    """Return what lup needs of Codex: its hooks answered, and its launch."""
    return Adapter(
        runtime=Codex(),
        hook=hook,
        unanswered=unanswered,
        heard=heard,
        told=told,
        ends=ends,
        spawned=spawned,
        woken=None,
        hooks=hooks,
        channel=CodexChannel(),
        agent=agent,
        records=CodexRecords(home=CodexLayout.of(CodexSettings()).operator_home),
        reader=CodexTranscripts(),
    )
