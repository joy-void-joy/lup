"""Claude Code's hooks, its payloads in, lup's events, its outputs out; and its release channel.

| Claude Code hook | lup's event |
|---|---|
| `SessionStart` | `SessionStarted` |
| `PreToolUse` | `CallStarted`; for `Edit` and `Write`, judged before it lands first |
| `PostToolUse`, `PostToolUseFailure` | `CallFinished` |
| `Stop` | `TurnEnded` |
| `SubagentStop` | `ConversationEnded` |

Claude Code asks the operator in its own prompt: `PreToolUse` answers `allow`, `ask`
or `deny`, and a hook's `ask` prompts in auto mode too. The agent hears a
checkpoint's report as `additionalContext` beside the call's result, and a turn,
the session's or a subagent's, can't end while a `Stop` or `SubagentStop` hook
answers `decision: block`; `Stop`'s `stop_hook_active` says the session's turn's
end follows such a block. When judging itself fails at a turn's end, the turn
ends, and the operator is warned once in `systemMessage`, which also carries what
the session's turn's end tells without holding it.

In a launched room (`docs/launch.md`, *The one hook and the host service*), Claude
Code runs the room's hook on `SessionStart`, and on `PreToolUse` for the file tools
whose writes are judged before they land (`hooks`, `WRITING`): no checkpoint, as in
lup's own repository. Where the launch's judge can't answer a hook, the host
service answers it through `unanswered`: a file tool's write is denied, naming why,
since a write let through unjudged would land unseen; any other hook warns the
operator in `systemMessage`, and the call goes on. Where the room's hook can't
reach the service, it ends with status 1 and says why on standard error: a
non-blocking error, which Claude Code shows, and the call goes on.

What this relies on, from Claude Code's hooks reference
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
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup.sessions.terminal import Cli, Hook
from lup.types import JsonObject, Model, Settings
from lup_dev.adapters import Adapter
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
    from datetime import timedelta

    import httpx

    from lup.sessions.declaration import Declaration

WRITING = ["Edit", "Write"]
"""The file tools whose writes are judged before they land: `PreToolUse.proposal`
reads each, and a launched session's hook matches them."""


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
    def asks_before(self) -> bool:
        return True

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


def failure_note(failure: Exception) -> str:
    """Say that judging failed, for the agent to pass on."""
    return f"lup's judge failed, so this wasn't judged: {failure!r}. Tell the operator."


class Payload(Model, ABC):
    """What every Claude Code hook receives on stdin, and how each answers."""

    session_id: str
    cwd: Path
    agent_id: str = ""
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
        """Judge a file tool's write before it lands, and count the call as running.

        A refused call never runs, so it isn't counted.
        """
        proposed = self.proposal()
        decision = (
            Decision(outcome=None)
            if proposed is None
            else before(bench, proposed, self.session_id, self.cwd)
        )
        match decision.outcome:
            case "refuse":
                answer = PreToolUseAnswer(
                    permission_decision="deny",
                    permission_decision_reason=decision.reason,
                )
                return Specific(hook_specific_output=answer)
            case None:
                self.started().apply(bench)
                return None
            case "allow" | "ask" as outcome:
                self.started().apply(bench)
                answer = PreToolUseAnswer(
                    permission_decision=outcome,
                    permission_decision_reason=decision.reason or None,
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


def hooks(command: list[str], timeout: timedelta) -> list[Hook]:
    """Return the hooks a launched Claude Code session runs `command` at: the events the judge reads.

    `SessionStart`, and `PreToolUse` on the file tools, judged before they land.
    Each waits up to `timeout`, which a hold's wait for the operator needs.
    """
    return [
        Hook(event="session-started", command=command, timeout=timeout),
        Hook(
            event="call-started",
            matcher="|".join(WRITING),
            command=command,
            timeout=timeout,
        ),
    ]


def agent(fallback: str = "default") -> Declaration:
    """Return the declaration a launched Claude Code session runs: the model the operator's own settings choose.

    Where they choose none, `fallback`: `default`, which Claude Code documents as
    reverting "to the runtime default for your account" (`model-config`).
    """
    return lup.Claude.chosen(default=fallback)


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


def adapter() -> Adapter:
    """Return what lup needs of Claude Code: its hooks answered, and its launch."""
    return Adapter(
        runtime=Claude(),
        hook=hook,
        unanswered=unanswered,
        hooks=hooks,
        channel=ClaudeChannel(),
        agent=agent,
    )
