"""Claude Code, as lup holds its sessions: its room, its hooks, its held protocol and its CLI's channel.

What each setting rests on was measured in the second lup (`docs/field-notes.md`,
*Claude Code 2.1.296: launching a session*, *A session held with no terminal*,
*A fork of a session*):
- **Settings outside the repository.** `--setting-sources user` drops the
  project's `.claude/` and `CLAUDE.md`, and `--settings` sits above the user's
  own, its `env` outranking theirs. `--strict-mcp-config` keeps every server but
  lup's out.
- **Guidance at system level,** `--append-system-prompt-file`, with
  `--system-prompt-snapshot off` so a resumed conversation is told this start's.
- **No prompts:** `bypassPermissions`, the warning pre-answered, onboarding and
  the worktree's trust written in the runtime's own `.claude.json`.
- **Held,** with no `-p`, whose default is moving to `--bare`, which runs no
  hooks: the terminal's command with stream-json on its input and output.
- **Named up front,** `--session-id` for a start, so lup's id for the session
  is Claude Code's; a fork is `--resume <parent> --fork-session --session-id`.
- **Tools left out** by a bare name in `permissions.deny`, which removes a tool
  from context, subagents' too: `Artifact` alone is 55 KB of every turn, and the
  native worktree tools are lup's to replace.
"""

import asyncio
import hashlib
import json
import shlex
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, override

from pydantic import Field, JsonValue, ValidationError

from lup.doors.parties import Agent
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

NAME = "claude"
"""lup's name for Claude Code, which its sessions, a profile's defaults and an
account's logins name it by."""


class ClaudeRooming(Rooming):
    """What Claude Code needs in a session's room: lup's settings, its tool server, its guidance, and the command running it."""

    denied: list[str] = [
        "Artifact",
        "SendFeedback",
        "Workflow",
        "ScheduleWakeup",
        "ReportFindings",
        "EnterWorktree",
        "ExitWorktree",
    ]
    """Built-in tools left out of every session: large, or lup's to do."""
    hook_timeout: timedelta = timedelta(hours=25)
    """How long a hook may hold its call: past any wait on the operator lup
    makes, which a hook's answer can be."""
    tool_timeout: timedelta = timedelta(hours=25)
    """How long a call to lup's tools may run, `wait_inbox` and `ask` among
    them."""
    variables: dict[str, str] = {
        "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_SILENT_TURN_REMINDER": "0",
    }
    """What every room runs it with: lup's long calls kept in the foreground,
    no update of a CLI lup fetches itself, no nudge to talk while working."""
    settings_env: dict[str, str] = {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "1h",
    }
    """What lup's settings set, outranking the operator's own: no auto memory,
    which one room would write and every later one read, and subagents' prompt
    cache kept an hour, as the main conversation's is."""
    kept_days: int = 36_500
    """How long Claude Code keeps a session's record after its last use
    (`cleanupPeriodDays`, 30 by default): for good, since transcripts read
    the records where the runtime keeps them."""

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
        hooks = {
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
            for hook in ClaudeHooks().hooks()
        }
        settings: dict[str, JsonValue] = {
            "env": dict[str, JsonValue](self.settings_env),
            "hooks": json.loads(json.dumps(hooks)),
            "permissions": {"deny": list[JsonValue](self.denied)},
            "idleCompaction": False,
            "cleanupPeriodDays": self.kept_days,
            "disableClaudeAiConnectors": True,
            "skipDangerousModePermissionPrompt": True,
        }
        servers = {
            "mcpServers": {
                "lup": {
                    "type": "stdio",
                    "command": bridge.tools[0],
                    "args": bridge.tools[1:],
                    "timeout": int(self.tool_timeout.total_seconds() * 1000),
                }
            }
        }
        trusted = {"hasTrustDialogAccepted": True}
        state = {
            "hasCompletedOnboarding": True,
            "projects": {str(placed.worktree): trusted},
        }
        command = [
            "claude",
            "--setting-sources",
            "user",
            "--settings",
            str(placed.session / "settings.json"),
            "--permission-mode",
            "bypassPermissions",
            "--mcp-config",
            str(placed.session / "mcp.json"),
            "--strict-mcp-config",
            *([] if begin.model is None else ["--model", begin.model]),
            *([] if begin.effort is None else ["--effort", begin.effort]),
            "--append-system-prompt-file",
            str(placed.session / "guidance.md"),
            "--system-prompt-snapshot",
            "off",
            *begun(begin),
            *(
                [
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--input-format",
                    "stream-json",
                ]
                if held
                else []
            ),
        ]
        return Prepared(
            files={
                "settings.json": json.dumps(settings, indent=2),
                "mcp.json": json.dumps(servers, indent=2),
                "guidance.md": guidance,
            },
            homed={".claude.json": json.dumps(state, indent=2)},
            env={**self.variables, "CLAUDE_CONFIG_DIR": str(placed.runtime)},
            command=command,
        )

    @override
    def login(self) -> str:
        return ".credentials.json"

    @override
    def kept(self) -> list[str]:
        return [
            "projects",
            "file-history",
            "tasks",
            "todos",
            "plans",
            "paste-cache",
            "history.jsonl",
        ]


def begun(begin: Begin) -> list[str]:
    """Return the arguments naming a session begun as `begin` says: lup's id given up front for a start or a fork, the runtime's id resumed or forked from.

    Raise `ValueError` where a resume or a fork names nothing to begin from.

    >>> begun(Begin(begun="fork", session="n", known_as="p"))
    ['--resume', 'p', '--fork-session', '--session-id', 'n']
    """
    match begin.begun:
        case "start":
            return ["--session-id", begin.session]
        case "resume" | "fork" if begin.known_as is None:
            message = (
                f"a {begin.begun} of a Claude Code session names the session it's of"
            )
            raise ValueError(message)
        case "resume":
            return ["--resume", str(begin.known_as)]
        case "fork":
            return [
                "--resume",
                str(begin.known_as),
                "--fork-session",
                "--session-id",
                begin.session,
            ]


class Payload(Model):
    """What any of Claude Code's hooks is given, of which lup reads what it names: unknown fields are left alone, since every version adds some."""

    hook_event_name: str = ""
    session_id: str = ""
    cwd: Path = Path()
    source: str = "startup"
    """A session's start: `startup`, `resume`, `clear`, `compact` or `fork`."""
    prompt: str = ""
    tool_name: str = ""
    tool_input: JsonValue = None
    tool_use_id: str = ""
    last_assistant_message: str = ""
    error: str = ""
    agent_id: str | None = None
    """The subagent whose conversation it is; none for the session's own."""
    agent_type: str = ""


class Written(Model):
    """What a file tool is given, of which lup reads the file it writes."""

    file_path: Path | None = None
    notebook_path: Path | None = None


def begun_as(source: str) -> Begun:
    """Return how a session began, in lup's words, as Claude Code's `SessionStart` says it: a start where it says something lup doesn't know.

    >>> begun_as("startup"), begun_as("compact")
    ('start', 'compact')
    """
    match source:
        case "resume" | "fork" | "clear" | "compact":
            return source
        case _:
            return "start"


def writes(payload: Payload, tools: list[str]) -> list[Path]:
    """Return the files a call writes, read from what its tool was given: one for a file tool among `tools`, none for any other."""
    if payload.tool_name not in tools:
        return []
    try:
        written = Written.model_validate(payload.tool_input)
    except ValidationError:
        return []
    return [
        each for each in [written.file_path, written.notebook_path] if each is not None
    ]


class ClaudeHooks(Hooks):
    """Claude Code's hooks, as lup listens at them, reads them and answers them."""

    ours: str = "mcp__lup__"
    """What the names of lup's own tools start with, as Claude Code names a
    server's tools."""
    files: list[str] = ["Edit", "Write", "MultiEdit", "NotebookEdit"]
    """The tools writing the file named in what they're given."""

    @override
    def hooks(self) -> list[Hook]:
        return [
            Hook(name=name)
            for name in [
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "PostToolUseFailure",
                "Stop",
                "StopFailure",
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
        event = self.event(hook, given, agent)
        return Heard(
            event=event,
            conversation=conversation,
            ours=hook == "PreToolUse" and given.tool_name.startswith(self.ours),
        )

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
                    writes=writes(given, self.files),
                )
            case "PostToolUse" | "PostToolUseFailure":
                return CallFinished(
                    agent=agent,
                    call=given.tool_use_id,
                    tool=given.tool_name,
                    writes=writes(given, self.files),
                    failed=hook == "PostToolUseFailure",
                )
            case "Stop":
                return TurnEnded(agent=agent, said=given.last_assistant_message)
            case "StopFailure":
                return TurnEnded(
                    agent=agent,
                    said=given.error or given.last_assistant_message,
                    failed=True,
                )
            case "SubagentStart":
                return ConversationStarted(agent=agent, called=given.agent_type)
            case "SubagentStop":
                return ConversationEnded(agent=agent, said=given.last_assistant_message)
            case "SessionEnd":
                return SessionEnded(agent=agent)
            case _:
                return None

    @override
    def answered(self, hook: str, payload: bytes, answer: Answer) -> Spoken:
        told: dict[str, JsonValue] = (
            {"additionalContext": answer.told} if answer.told else {}
        )
        decided: dict[str, JsonValue] = {}
        match hook, answer:
            case "PreToolUse", Answer(refused=str() as refused):
                decided = {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": refused,
                }
            case "PreToolUse", Answer(stamp=Stamp() as stamp):
                given = Payload.model_validate_json(payload).tool_input
                stamped = given if isinstance(given, dict) else {}
                decided = {"updatedInput": {**stamped, stamp.field: stamp.conversation}}
            case _:
                pass
        if not told and not decided:
            return Spoken(output="{}")
        specific = {"hookEventName": hook, **told, **decided}
        return Spoken(output=json.dumps({"hookSpecificOutput": specific}))


class Line(Model):
    """A line Claude Code writes on its output, of which lup reads its type and what it names."""

    type: str = ""
    subtype: str = ""
    session_id: str | None = None
    request_id: str | None = None


class ClaudeHolding(Holding):
    """A Claude Code session held over stream-json: a user turn written on its input starts a turn, or joins the one under way, and a `result` ends it."""

    def message(self, kind: str, body: dict[str, JsonValue]) -> str:
        """Return a line of `kind`, its body `body`, as stream-json writes one."""
        return json.dumps({"type": kind, **body})

    @override
    def turn(self, text: str) -> list[str]:
        self.busy = True
        return [
            self.message(
                "user",
                {
                    "message": {"role": "user", "content": text},
                    "parent_tool_use_id": None,
                    "session_id": "",
                },
            )
        ]

    @override
    def interrupt(self) -> list[str]:
        if not self.busy:
            return []
        return [
            self.message(
                "control_request",
                {
                    "request_id": uuid.uuid4().hex,
                    "request": {"subtype": "interrupt"},
                },
            )
        ]

    @override
    def read(self, line: str) -> list[str]:
        try:
            said = Line.model_validate_json(line)
        except ValidationError:
            return []
        match said.type:
            case "system" if said.subtype == "init" and said.session_id:
                self.known_as = said.session_id
                return []
            case "result":
                self.busy = False
                return []
            case "control_request" if said.request_id is not None:
                return [
                    self.message(
                        "control_response",
                        {
                            "response": {
                                "subtype": "error",
                                "request_id": said.request_id,
                                "error": "lup answers no request of its sessions",
                            }
                        },
                    )
                ]
            case _:
                return []


class ClaudeHolder(Holder):
    """How a Claude Code session is held: named up front, so it's ready as soon as it's connected."""

    @override
    def holding(self, begin: Begin, worktree: Path) -> Holding:
        del worktree
        known_as = begin.session if begin.begun != "resume" else begin.known_as
        return ClaudeHolding(known_as=known_as, up=True)


class Build(Model):
    """One platform's build, as a version's manifest lists it."""

    checksum: str
    """Its SHA-256, in hexadecimal."""


class Manifest(Model):
    """A version's manifest: each platform's build."""

    platforms: dict[str, Build]


class ClaudeChannel(Channel):
    """Claude Code's releases, as its native installer reads them: the newest version as text, each version's manifest with each build's checksum."""

    base: str = "https://downloads.claude.ai/claude-code-releases"
    which: Literal["latest", "stable"] = "latest"
    """The channel: `latest`, or `stable`, about a week older."""
    platform: str = "linux-x64"

    @override
    async def latest(self, got: Got, scratch: Path) -> str:
        answered = scratch / "latest"
        await got.got(f"{self.base}/{self.which}", answered)
        return (await asyncio.to_thread(answered.read_text)).strip()

    @override
    async def fetched(self, version: str, into: Path, got: Got) -> Fetched:
        await asyncio.to_thread(into.mkdir, parents=True, exist_ok=True)
        listed = into / "manifest.json"
        await got.got(f"{self.base}/{version}/manifest.json", listed)
        read = await asyncio.to_thread(listed.read_bytes)
        build = Manifest.model_validate_json(read).platforms.get(self.platform)
        if build is None:
            message = f"Claude Code {version} has no build for {self.platform}"
            raise ValueError(message)
        program = into / "claude"
        await got.got(f"{self.base}/{version}/{self.platform}/claude", program)
        binary = await asyncio.to_thread(program.read_bytes)
        if hashlib.sha256(binary).hexdigest() != build.checksum:
            await asyncio.to_thread(program.unlink)
            message = (
                f"Claude Code {version} for {self.platform} isn't what its manifest "
                "says: its checksum differs"
            )
            raise ValueError(message)
        await asyncio.to_thread(program.chmod, 0o755)
        return Fetched(version=version, directory=into, program=PurePosixPath("claude"))


class ClaudeCode(Runtime):
    """Claude Code, as lup holds its sessions."""

    name: str = NAME
    rooming: Rooming = Field(default_factory=ClaudeRooming)
    hooks: Hooks = Field(default_factory=ClaudeHooks)
    holder: Holder = Field(default_factory=ClaudeHolder)
    channel: Channel = Field(default_factory=ClaudeChannel)
