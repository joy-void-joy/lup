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

In a launched room (`docs/launch.md`, *The one hook and the host service*), Codex
runs the room's hook on `SessionStart`, `PreToolUse` and `PostToolUse` (`hooks`),
the checkpoint after each call being the only place its hooks see a patch. Where
the launch's judge can't answer a hook, the host service answers it through
`unanswered`: at `PostToolUse` the agent is told beside the call's result, as when
judging fails; anything else warns the operator in `systemMessage`, and the call
goes on. Where the room's hook can't reach the service, it ends with status 1:
Codex marks the hook's run failed, shows "hook exited with code 1" (not what the
hook wrote to standard error), and the call goes on.

What this relies on, from Codex's hooks documentation and its source at
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
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.alias_generators import to_camel

import lup
from lup.sessions.terminal import Cli, Hook
from lup.types import Model, Settings
from lup_dev.adapters import Adapter
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
    from datetime import timedelta

    import httpx

    from lup.sessions.declaration import Declaration
    from lup.sessions.terminal import Event


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


class OperatorWarning(Output):
    """A warning shown to the operator, not the agent, which lets the turn end.

    Codex's hooks docs: `Stop` "expects JSON on `stdout` when it exits `0`" and
    takes the common output fields, among them `systemMessage`, "Surfaced as a
    warning in the UI or event stream"; only `decision: "block"` continues the
    turn.
    """

    system_message: str


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


def hooks(command: list[str], timeout: timedelta) -> list[Hook]:
    """Return the hooks a launched Codex session runs `command` at: the events the judge reads.

    `SessionStart`, `PreToolUse` and `PostToolUse` on every tool: Codex is judged
    after each call. Each waits up to `timeout`, which a hold's wait for the
    operator needs.
    """
    events: list[Event] = ["session-started", "call-started", "call-finished"]
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


def adapter() -> Adapter:
    """Return what lup needs of Codex: its hooks answered, and its launch."""
    return Adapter(
        runtime=Codex(),
        hook=hook,
        unanswered=unanswered,
        hooks=hooks,
        channel=CodexChannel(),
        agent=agent,
    )
