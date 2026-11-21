"""Codex, as lup holds its sessions: its room, its hooks, its held protocol and its CLI's channel.

What each setting rests on was read in Codex's source and measured in the second
lup (`docs/field-notes.md`, *Codex 0.162.1: launching a session*, *its hooks
around a call*, *A session held with no terminal*, *A conversation resumed in a
later launch*):
- **Held over `app-server`,** JSON-RPC a line, on the room's socket: a thread
  started, resumed or forked by the holder, whose id is Codex's own, said in
  its answer; a turn started on the operator's words, or steered into the one
  under way.
- **lup's hooks are managed:** a requirements file mounted at
  `/etc/codex/requirements.toml`, which needs no review of each hook, with
  `allow_managed_hooks_only` so no other hook runs; `app-server` skips a hook
  nobody trusted without a word.
- **Guidance at system level,** `additional_developer_instructions` in the same
  file: its own developer message, sent again whole where it changed on a
  resume, and refused past 10,000 tokens of four bytes, so the ceiling.
- **No prompts:** approvals never, full access, the worktree trusted, since the
  room is the wall; `AGENTS.md` read from nowhere (`project_doc_max_bytes`).
- **What lup turns off:** memories, connectors, plugins (and with them a sync
  at start), update checks, analytics and feedback.
- **A terminal** takes a held thread over with `--no-daemon`, without which
  Codex starts a daemon that keeps the thread from the next holder.
"""

import asyncio
import hashlib
import json
import shlex
import tarfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal, override

from pydantic import Field, JsonValue, ValidationError

from lup.doors.parties import Agent
from lup.runtimes.codex_records import CodexRecords
from lup.runtimes.runtime import (
    Answer,
    Begin,
    Bridge,
    Channel,
    Fetched,
    Got,
    Heard,
    Holder,
    Holding,
    Hook,
    Hooks,
    Placed,
    Placing,
    Prepared,
    Rooming,
    Runtime,
    Spoken,
    Stamp,
)
from lup.sessions.events import (
    Begun,
    CallFinished,
    CallStarting,
    ConversationEnded,
    ConversationStarted,
    Happened,
    SessionEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
)
from lup.types import Model
lazy from lup.runtimes.records import Records

NAME = "codex"
"""lup's name for Codex, which its sessions, a profile's defaults and an
account's logins name it by."""


def toml(value: JsonValue) -> str:
    """Return `value` as a TOML value on one line, its tables inline, as `-c` and a requirements file read one.

    A JSON string is a TOML basic string, its escapes TOML's too.

    >>> toml({"lup": {"args": ["-I"], "timeout": 5, "on": True}})
    '{ "lup" = { "args" = ["-I"], "timeout" = 5, "on" = true } }'

    Raise `ValueError` for a null, which TOML has no value for.
    """
    match value:
        case None:
            message = "TOML has no null"
            raise ValueError(message)
        case bool():
            return "true" if value else "false"
        case int() | float() | str():
            return json.dumps(value)
        case list():
            return "[" + ", ".join(toml(each) for each in value) + "]"
        case dict():
            pairs = [f"{json.dumps(key)} = {toml(each)}" for key, each in value.items()]
            return "{ " + ", ".join(pairs) + " }"


class CodexRooming(Rooming):
    """What Codex needs in a session's room: its requirements, lup's settings on its command line, and the command running it."""

    requirements: Path = Path("/etc/codex/requirements.toml")
    """Where Codex reads managed requirements on Linux."""
    hook_timeout: timedelta = timedelta(days=24)
    """How long a hook may hold its call: past any wait on the operator."""
    tool_timeout: timedelta = timedelta(days=24)
    """How long a call to lup's tools may run, `wait_inbox` and `ask` among
    them: Codex's own default is 300 s, and it sets no cap, so the same as
    Claude Code's, since a call held on the operator's answer waits as long as
    they take."""
    settings: dict[str, JsonValue] = {
        "features.memories": False,
        "features.apps": False,
        "features.plugins": False,
        "check_for_update_on_startup": False,
        "analytics.enabled": False,
        "feedback.enabled": False,
        "project_doc_max_bytes": 0,
        "cli_auth_credentials_store": "file",
    }
    """What lup sets on every session's command line: memories, connectors and
    plugins off, no update check, analytics or feedback, no `AGENTS.md`, and
    the login kept in its file, which a refresh under the keyring deletes."""

    @override
    def prepared(
        self,
        begin: Begin,
        placed: Placed,
        bridge: Bridge,
        guidance: str,
        *,
        held: bool,
    ) -> Prepared:
        groups: dict[str, JsonValue] = {
            hook.name: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": shlex.join([*bridge.hook, hook.name]),
                            "timeout": int(self.hook_timeout.total_seconds()),
                        }
                    ]
                }
            ]
            for hook in CodexHooks().hooks()
        }
        requirements = "\n".join(
            [
                "allow_managed_hooks_only = true",
                f"additional_developer_instructions = {toml(guidance)}",
                f"hooks = {toml(groups)}",
                "",
            ]
        )
        server: JsonValue = {
            "command": bridge.tools[0],
            "args": list[JsonValue](bridge.tools[1:]),
            "tool_timeout_sec": int(self.tool_timeout.total_seconds()),
            "default_tools_approval_mode": "approve",
        }
        overrides: dict[str, JsonValue] = {
            **self.settings,
            "projects": {str(placed.worktree): {"trust_level": "trusted"}},
            "mcp_servers": {"lup": server},
            **({} if begin.model is None else {"model": begin.model}),
            **(
                {} if begin.effort is None else {"model_reasoning_effort": begin.effort}
            ),
        }
        configured = [
            word
            for key, value in overrides.items()
            for word in ["-c", f"{key}={toml(value)}"]
        ]
        command = (
            ["codex", *configured, "app-server"]
            if held
            else [
                "codex",
                "--no-daemon",
                "--dangerously-bypass-approvals-and-sandbox",
                *configured,
                *terminal(begin),
            ]
        )
        return Prepared(
            files={"requirements.toml": requirements},
            placed=[Placing(name="requirements.toml", at=self.requirements)],
            env={"CODEX_HOME": str(placed.runtime)},
            command=command,
        )

    @override
    def login(self) -> str:
        return "auth.json"

    @override
    def kept(self) -> list[str]:
        return ["sessions", "archived_sessions", "history.jsonl", "session_index.jsonl"]


def terminal(begin: Begin) -> list[str]:
    """Return the words of Codex's terminal command beginning a session as `begin` says: a thread resumed or forked by its id, or a new one.

    >>> terminal(Begin(begun="resume", session="s", known_as="t"))
    ['resume', 't']
    """
    match begin.begun, begin.known_as:
        case "start", _:
            return []
        case "resume", str() as known_as:
            return ["resume", known_as]
        case "fork", str() as known_as:
            return ["fork", known_as]
        case _:
            message = f"a {begin.begun} of a Codex thread names the thread it's of"
            raise ValueError(message)


class Payload(Model):
    """What any of Codex's hooks is given, of which lup reads what it names: unknown fields are left alone."""

    session_id: str = ""
    cwd: Path = Path()
    source: str = "startup"
    prompt: str = ""
    tool_name: str = ""
    tool_input: JsonValue = None
    tool_use_id: str = ""
    last_assistant_message: str | None = None
    agent_id: str | None = None
    """The subagent whose conversation it is, where Codex names one."""
    agent_type: str | None = None


class Patching(Model):
    """What `apply_patch` is given: the patch, as the model wrote it."""

    command: str = ""


def patched(patch: str, markers: list[str]) -> list[Path]:
    r"""Return the files a patch writes: each a line of its own after one of `markers`, as `apply_patch`'s format names them.

    The format has no parser outside Codex, and names one file a line.

    >>> patched("*** Begin Patch\n*** Add File: a.py\n+x\n*** End Patch", ["*** Add File: "])
    [PosixPath('a.py')]
    """
    return [
        Path(line.removeprefix(marker))
        for line in patch.splitlines()
        for marker in markers
        if line.startswith(marker)
    ]


def begun_as(source: str) -> Begun:
    """Return how a thread began, in lup's words, as Codex's `SessionStart` says it.

    >>> begun_as("resume")
    'resume'
    """
    match source:
        case "resume" | "fork" | "clear" | "compact":
            return source
        case _:
            return "start"


class CodexHooks(Hooks):
    """Codex's hooks, as lup listens at them, reads them and answers them."""

    ours: str = "mcp__lup__"
    """What the names of lup's own tools start with, as Codex names a server's
    tools."""
    patching: str = "apply_patch"
    """The tool writing files, named in its patch."""
    markers: list[str] = ["*** Add File: ", "*** Update File: ", "*** Move to: "]
    """What a patch writes a file after, one a line."""

    @override
    def hooks(self) -> list[Hook]:
        return [
            Hook(name=name)
            for name in [
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "SubagentStart",
                "SubagentStop",
                "SessionEnd",
            ]
        ]

    @override
    def heard(self, hook: str, payload: bytes, session: str) -> Heard:
        given = Payload.model_validate_json(payload)
        conversation = given.agent_id or None
        agent = Agent.of(session, conversation)
        return Heard(
            event=self.event(hook, given, agent),
            conversation=conversation,
            ours=hook == "PreToolUse" and given.tool_name.startswith(self.ours),
        )

    def writes(self, given: Payload) -> list[Path]:
        """Return the files a call writes: those its patch names, for a patch; none for any other call."""
        if given.tool_name != self.patching:
            return []
        try:
            patch = Patching.model_validate(given.tool_input).command
        except ValidationError:
            return []
        return patched(patch, self.markers)

    def event(self, hook: str, given: Payload, agent: Agent) -> Happened | None:
        """Return the event the hook named `hook` is, given `given`, of `agent`'s conversation; none for a hook lup reads nothing of."""
        match hook:
            case "SessionStart":
                return SessionStarted(
                    agent=agent,
                    begun=begun_as(given.source),
                    runtime=NAME,
                    known_as=given.session_id,
                    worktree=given.cwd,
                )
            case "UserPromptSubmit":
                return TurnStarted(agent=agent, prompt=given.prompt)
            case "PreToolUse":
                return CallStarting(
                    agent=agent,
                    call=given.tool_use_id,
                    tool=given.tool_name,
                    given=given.tool_input,
                    writes=self.writes(given),
                )
            case "PostToolUse":
                return CallFinished(
                    agent=agent,
                    call=given.tool_use_id,
                    tool=given.tool_name,
                    writes=self.writes(given),
                )
            case "Stop":
                return TurnEnded(agent=agent, said=given.last_assistant_message or "")
            case "SubagentStart":
                return ConversationStarted(agent=agent, called=given.agent_type or "")
            case "SubagentStop":
                return ConversationEnded(
                    agent=agent, said=given.last_assistant_message or ""
                )
            case "SessionEnd":
                return SessionEnded(agent=agent)
            case _:
                return None

    @override
    def answered(self, hook: str, payload: bytes, answer: Answer) -> Spoken:
        match hook, answer:
            case "Stop" | "SubagentStop", Answer(told=str() as words) if words:
                return Spoken(output=json.dumps({"decision": "block", "reason": words}))
            case "PreToolUse", Answer(refused=str() as refused):
                decided: dict[str, JsonValue] = {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": refused,
                }
            case "PreToolUse", Answer(stamp=Stamp() as stamp):
                given = Payload.model_validate_json(payload).tool_input
                stamped = given if isinstance(given, dict) else {}
                decided = {
                    "permissionDecision": "allow",
                    "updatedInput": {**stamped, stamp.field: stamp.conversation},
                }
            case _:
                decided = {}
        told: dict[str, JsonValue] = (
            {"additionalContext": answer.told}
            if answer.told and hook not in ["Stop", "SubagentStop"]
            else {}
        )
        if not told and not decided:
            return Spoken(output="{}")
        specific = {"hookEventName": hook, **told, **decided}
        return Spoken(output=json.dumps({"hookSpecificOutput": specific}))


class Message(Model):
    """A JSON-RPC message of `app-server`'s, of which lup reads what it needs: a request carries `id` and `method`, a response `id` alone, a notification `method` alone."""

    id: int | str | None = None
    method: str | None = None
    params: JsonValue = None
    result: JsonValue = None
    error: JsonValue = None


class Thread(Model):
    """A thread, as an answer names it: its id."""

    id: str


class Opened(Model):
    """The answer to starting, resuming or forking a thread."""

    thread: Thread


class TurnOf(Model):
    """A turn, as a notification names it."""

    id: str


class TurnSaid(Model):
    """A notification about a turn: the thread it's of, and the turn."""

    thread: str = Field(default="", alias="threadId")
    turn: TurnOf | None = None


class CodexHolding(Holding):
    """A Codex session held over `app-server`: the connection initialized, a thread opened, and each turn started, steered into, or interrupted on it."""

    begin: Begin
    worktree: Path
    numbered: int = 0
    """The last request's id."""
    turning: str | None = None
    """The turn under way, by its id, while one is."""
    waiting: list[str] = []
    """The operator's words given before the thread was open, to start its
    first turn with."""
    first: int = 1
    """The id of the request initializing the connection."""

    def request(self, method: str, params: JsonValue) -> str:
        """Return a request of `method` with `params`, under the next id."""
        self.numbered += 1
        return json.dumps({"id": self.numbered, "method": method, "params": params})

    def notice(self, method: str) -> str:
        """Return a notification of `method`, with no params."""
        return json.dumps({"method": method})

    def opening_thread(self) -> str:
        """Return the request opening the session's thread: started, resumed or forked."""
        settings: dict[str, JsonValue] = {
            "cwd": str(self.worktree),
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            **({} if self.begin.model is None else {"model": self.begin.model}),
        }
        match self.begin.begun, self.begin.known_as:
            case "resume", str() as known_as:
                return self.request("thread/resume", {"threadId": known_as, **settings})
            case "fork", str() as known_as:
                return self.request("thread/fork", {"threadId": known_as, **settings})
            case _:
                return self.request("thread/start", settings)

    def input(self, text: str) -> JsonValue:
        """Return `text` as a turn's input."""
        return [{"type": "text", "text": text}]

    @override
    def turn(self, text: str) -> list[str]:
        if self.known_as is None:
            self.waiting = [*self.waiting, text]
            return []
        if self.busy and self.turning is not None:
            return [
                self.request(
                    "turn/steer",
                    {
                        "threadId": self.known_as,
                        "input": self.input(text),
                        "expectedTurnId": self.turning,
                    },
                )
            ]
        self.busy = True
        effort: dict[str, JsonValue] = (
            {} if self.begin.effort is None else {"effort": self.begin.effort}
        )
        return [
            self.request(
                "turn/start",
                {"threadId": self.known_as, "input": self.input(text), **effort},
            )
        ]

    @override
    def interrupt(self) -> list[str]:
        if self.known_as is None or self.turning is None:
            return []
        return [
            self.request(
                "turn/interrupt", {"threadId": self.known_as, "turnId": self.turning}
            )
        ]

    @override
    def read(self, line: str) -> list[str]:
        try:
            said = Message.model_validate_json(line)
        except ValidationError:
            return []
        match said:
            case Message(id=self.first, method=None):
                return [self.notice("initialized"), self.opening_thread()]
            case Message(id=int(), method=None, result=dict() as result) if (
                self.known_as is None
            ):
                return self.opened(result)
            case Message(id=int(), method=None, error=dict() as error) if (
                self.known_as is None
            ):
                self.failed = json.dumps(error)
                return []
            case Message(id=int() | str() as asked, method=str() as method):
                return [self.refused(asked, method)]
            case Message(method="turn/started", params=params):
                self.turned(params, started=True)
                return []
            case Message(method="turn/completed", params=params):
                self.turned(params, started=False)
                return []
            case _:
                return []

    def opened(self, result: dict[str, JsonValue]) -> list[str]:
        """Keep the thread an answer opened, and start its first turn on the words waiting, where any are."""
        try:
            self.known_as = Opened.model_validate(result).thread.id
        except ValidationError:
            return []
        self.up = True
        waiting, self.waiting = self.waiting, []
        if not waiting:
            return []
        return self.turn("\n\n".join(waiting))

    def turned(self, params: JsonValue, *, started: bool) -> None:
        """Keep a turn of the session's own thread starting or ending: a subagent's thread's turns leave it as it is."""
        try:
            said = TurnSaid.model_validate(params)
        except ValidationError:
            return
        if said.thread != self.known_as:
            return
        self.busy = started
        self.turning = said.turn.id if started and said.turn is not None else None

    def refused(self, asked: int | str, method: str) -> str:
        """Return the answer to a request of Codex's: lup answers none, and says so, so no turn waits on it."""
        return json.dumps(
            {
                "id": asked,
                "error": {
                    "code": -32601,
                    "message": f"lup answers no `{method}` of its sessions",
                },
            }
        )


class CodexHolder(Holder):
    """How a Codex session is held: initialized, then its thread opened, which names it."""

    @override
    def holding(self, begin: Begin, worktree: Path) -> Holding:
        holding = CodexHolding(begin=begin, worktree=worktree)
        holding.opening = [
            holding.request(
                "initialize",
                {"clientInfo": {"name": "lup", "version": "0"}, "capabilities": {}},
            )
        ]
        return holding


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


class Package(Model):
    """A package's own manifest, `codex-package.json`: its version, its target, and its program."""

    version: str
    target: str
    entrypoint: PurePosixPath


class CodexChannel(Channel):
    """Codex's release channel, read as its standalone installer reads it: each release described as GitHub's API describes one, each file with its checksum."""

    releases: str = "https://releases.openai.com/codex"
    which: Literal["latest"] = "latest"
    target: str = "x86_64-unknown-linux-musl"
    """The packages' name for Linux on x86-64, built static."""
    tag: str = "rust-v"
    """What a release's tag holds before its version."""
    manifest: str = "codex-package.json"

    async def release(self, url: str, got: Got, into: Path) -> Release:
        """Return the release `url` describes, fetched by `got` into `into`."""
        await got.got(url, into)
        return Release.model_validate_json(await asyncio.to_thread(into.read_bytes))

    def version(self, release: Release) -> str:
        """Return the version a release's tag names.

        Raise `ValueError` where it isn't one of the channel's tags.
        """
        if not release.tag_name.startswith(self.tag):
            message = f"Codex's release is tagged {release.tag_name}, not {self.tag}…"
            raise ValueError(message)
        return release.tag_name.removeprefix(self.tag)

    @override
    async def latest(self, got: Got, scratch: Path) -> str:
        url = f"{self.releases}/channels/{self.which}"
        return self.version(await self.release(url, got, scratch / "latest.json"))

    @override
    async def fetched(self, version: str, into: Path, got: Got) -> Fetched:
        url = f"{self.releases}/releases/{version}/release.json"
        await asyncio.to_thread(into.mkdir, parents=True, exist_ok=True)
        release = await self.release(url, got, into / "release.json")
        name = f"codex-package-{self.target}.tar.gz"
        asset = next((each for each in release.assets if each.name == name), None)
        if self.version(release) != version or asset is None:
            message = f"{url} describes no {name} of Codex {version}"
            raise ValueError(message)
        archive = into / name
        await got.got(asset.browser_download_url, archive)
        packed = await asyncio.to_thread(archive.read_bytes)
        await asyncio.to_thread(archive.unlink)
        if f"sha256:{hashlib.sha256(packed).hexdigest()}" != asset.digest:
            message = f"{name} of Codex {version} isn't what its release says: its checksum differs"
            raise ValueError(message)
        await asyncio.to_thread(unpacked, packed, into)
        manifest = await asyncio.to_thread((into / self.manifest).read_text)
        package = Package.model_validate_json(manifest)
        if package.version != version or package.target != self.target:
            message = f"{name} of Codex {version} holds {package.version} for {package.target}"
            raise ValueError(message)
        return Fetched(version=version, directory=into, program=package.entrypoint)


def unpacked(packed: bytes, into: Path) -> None:
    """Write out the gzipped tar archive `packed` into `into`, refusing a member that would land outside it or isn't a plain file, directory or link within it (`tarfile`'s `data` filter)."""
    with tarfile.open(fileobj=BytesIO(packed), mode="r:gz") as archive:
        archive.extractall(into, filter="data")


class Codex(Runtime):
    """Codex, as lup holds its sessions."""

    name: str = NAME
    ceiling: int | None = 40_000 - 169
    """Codex refuses managed developer instructions past 10,000 tokens of four
    bytes, counted with the markers and notice it adds, 169 bytes."""
    rooming: Rooming = Field(default_factory=CodexRooming)
    hooks: Hooks = Field(default_factory=CodexHooks)
    holder: Holder = Field(default_factory=CodexHolder)
    channel: Channel = Field(default_factory=CodexChannel)
    records: Records = Field(default_factory=CodexRecords)
