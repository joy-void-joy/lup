"""Claude Code in a terminal: the command line, settings and state a launched session starts with.

lup's settings reach the session as flags and files of the launch's own, never
written into the operator's directory or the repository (`docs/launch.md`, *The
settings compiled for each runtime*):
- `--settings <launch>/settings.json` with `--setting-sources user`: the user
  settings of the home the session runs on load (below), and the repository's
  `.claude/settings.json`, `.mcp.json`, skills and `CLAUDE.md` don't. lup's
  file holds the hooks, the session settings (below) and
  `skipDangerousModePermissionPrompt`;
- `--permission-mode bypassPermissions`: the room is the wall;
- lup's tool servers, where it gives any, with `--mcp-config <launch>/mcp.json`
  and `--strict-mcp-config`, so they're the session's only MCP servers (below);
  each that pushes (`ToolServer.pushes`) named to
  `--dangerously-load-development-channels` as `server:<name>`, so Claude Code
  takes what it pushes as a channel's messages (below);
- the session's messaging socket, where the settings place it, with
  `--messaging-socket-path`, and `crossSessionInbound: "accept"` in lup's file
  (below);
- the model with `--model` and the effort with `--effort`, each only where the
  declaration gives one: `--model` outranks the model the operator's settings
  choose, which `/model` saves there (`model-config`, *Setting your model*), so a
  declaration naming none leaves theirs to Claude Code, which reads it itself;
- the declaration's system prompt with `--system-prompt-file`, and the guidance
  with `--append-system-prompt-file` and `--system-prompt-snapshot off`, so the
  system prompt is rendered afresh at every request, a resumed conversation's
  too, and carries this launch's guidance;
- the variables: `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` so a held call isn't
  moved to the background after two minutes, `DISABLE_AUTOUPDATER` since the
  CLI's file is read-only, and `CLAUDE_CONFIG_DIR` naming the home;
- the launch's own state file, onboarding done and the trusted paths accepted,
  mounted read-write where Claude Code reads it, so concurrent starts can't
  race on one;
- the home (below), or, with none, the room's own home, gone with the launch.

**The home** (`TerminalSettings.home`, `at_home`): a directory of the rooms'
own, mounted read-write at its path, where Claude Code keeps its history and
state; nothing of the operator's directory is mounted. Inside it, each item of
configuration `ClaudeHome` names is mounted read-only, the launch's copy of the
layers holding it, the operator's directory's and then the home's own, or
empty, so no room leaves another a skill, a plugin or a `CLAUDE.md` to load;
`settings.json` is the launch's own, the layers' settings merged with what
would hand the room a credential left out (`lup.sessions.configuration`),
writable so `/model` saves, and what changed of its preferences carried back
into the home's own layer at the launch's end (`Terminal.preferences`); the
session's `shell-snapshots/` and `session-env/` are the launch's own, so no
room writes what another's Bash runs first; and `.credentials.json` is the
account's login, mounted alone, read-write. Claude Code refuses a login file
that's a link ("refused-symlink", in the 2.1.311 binary), so it's a mount; it
reloads the file when it changes (`lastCredentialsMtimeMs`), so a sign-in in
one room reaches every room on the account.

**The session settings** go in lup's settings file, which outranks the
home's user settings: each one the settings impose (`TerminalSettings.session`),
and each of lup's defaults the user settings don't set (`OwnSettings.sets`, read
from the layers once at launch), so theirs outrank lup's defaults:
- the subagents' cache lifetime as `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`, and
  auto memory as `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, both in the file's `env`: a
  variable there outranks the same variable in their file's `env`, and each
  outranks its settings key (`subagentPromptCacheTtl`, `autoMemoryEnabled`), so
  an imposed value wins whichever way they set theirs. Theirs count as set by the
  key or by the variable in their `env`;
- idle compaction as `idleCompaction`, which only `false` changes: `true` turns
  nothing on, and is passed so an imposed one outranks their `false`, the
  highest source's value holding. Compaction when the context fills,
  `autoCompactEnabled`, stays theirs or the runtime's;
- the account's connectors as `disableClaudeAiConnectors`. Any source's `true`
  turns them off, and so does their `env`'s `ENABLE_CLAUDEAI_MCP_SERVERS=false`,
  so a session asking for the connectors can't turn on what their own settings
  turned off; and theirs count as set by either;
- the removed tools, as bare names in `permissions.deny`, imposed or a default
  alike: permission rules merge across scopes, their own deny rules adding to
  lup's and none taking one back, so lup's are never theirs to set.

A variable in the room's own environment would lose to their file's `env`,
which Claude Code applies over its environment at start; their shell's
variables don't reach the room.

**lup's tool servers** are stdio servers in `mcp.json`, each lup's bridge to
the server's socket (`lup.sessions.bridge`, written into the launch's directory,
which the room mounts), which carries the session across the server's
restarts, with the server's
`timeout` in milliseconds where it gives one: Claude Code aborts a stdio call
with no answer and no progress for 30 minutes, and a `timeout` raises that idle
limit along with the call's own. `--strict-mcp-config` keeps every other MCP
server out, managed ones included; where lup gives none, neither flag is passed.
Their tools stay behind Claude Code's tool search, as it defers every MCP tool:
no `alwaysLoad`.

**A server that pushes** is loaded as a channel: Claude Code queues each
`notifications/claude/channel` it sends as a prompt, `<channel source="<name>">`
around its `content`, which starts a turn of the idle session and reaches a busy
one after its running call (`docs/field-notes.md`, *Channels*). A server on no
allowlist takes `--dangerously-load-development-channels`, which shows a warning
the operator confirms at each start and is ignored under `-p`; the flag takes
several entries, so it comes before `--strict-mcp-config`, never last, where it
would take a prompt for one.

**The messaging socket**, where the settings place it, is the session's own
cross-session inbox, through which a message reaches it between calls, or
starts a turn when it's idle. A session that bypasses permission prompts, as a
launched one does, holds each incoming message for approval unless
`crossSessionInbound` is `"accept"`, which lup's file then sets; the operator's
other Claude Code sessions can then start a turn in the room too.

| lup's event | Claude Code's hook events |
|---|---|
| `session-started` | `SessionStart` |
| `turn-started` | `UserPromptSubmit` |
| `call-started` | `PreToolUse` |
| `worktree-asked` | `WorktreeCreate` |
| `call-finished` | `PostToolUse`, `PostToolUseFailure` |
| `turn-ended` | `Stop`, `StopFailure` |
| `conversation-ended` | `SubagentStop` |

`WorktreeCreate` runs where Claude Code would make a worktree itself, a
subagent's `isolation: "worktree"` among the cases, and "replaces default git
behavior": its command prints the worktree's absolute path, "the last non-empty
line of stdout", and any status but 0 fails the making (the `hooks` docs,
*WorktreeCreate*, read 2026-10-25).

`StopFailure` runs instead of `Stop` or `SubagentStop` where a turn ends on an
error from the model's API, a subagent's as the session's own, its `agent_id`
saying which (the `hooks` docs; measured on 2.1.309, `docs/field-notes.md`,
*A subagent's end*). Its matcher
filters by the error's kind, never by the conversation, so it's registered
once, with `Stop`: listed under both ends, it would run twice.

What this relies on, from Claude Code's docs (code.claude.com, `cli-reference`,
`permissions`, `env-vars`, `settings`, `settings-reference`, `mcp`, `hooks`) and
its 2.1.294, 2.1.296 and 2.1.301 binaries:
- the system prompt flags work interactively; `--system-prompt-file` replaces the
  prompt, `--append-system-prompt-file` appends to it;
- by default Claude Code records the system prompt on a conversation's first
  request, those flags' text included, and "every later request and resume
  sends the record as-is, even when a later launch passes different text, until
  the conversation is compacted"; with `--system-prompt-snapshot off` (2.1.257
  and later) it records none, and "the prompt is rendered fresh every request"
  (the 2.1.301 binary's help; `cli-reference`, *System prompt flags in resumed
  conversations*);
- `--settings` is a level above user settings, and "an `env` block inside a
  settings file is an ordinary key and follows the levels above"; lists "merge
  instead of overriding" (`settings`, *Settings precedence*). The 2.1.296 binary
  applies each source's `env` over its own environment at start, in that order,
  user's then `--settings`';
- `disableClaudeAiConnectors` turns off "the connectors it fetches itself", set
  "to `true` in any settings scope", with "any-source-true semantics: `true` in
  any settings source takes precedence"; `ENABLE_CLAUDEAI_MCP_SERVERS=false` "has
  the same effect for the current shell session" (`mcp`, *Disable claude.ai
  connectors*). In the 2.1.296 binary, either turns them off, and nothing turns
  them back on;
- `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` takes `5m` or `1h`, "the only values
  Claude Code accepts", and "takes precedence" over `subagentPromptCacheTtl`
  (its schema's description, 2.1.296). `FORCE_PROMPT_CACHING_5M` outranks both,
  so a person setting it keeps every cache at five minutes;
- `CLAUDE_CODE_DISABLE_AUTO_MEMORY` takes `1` to turn auto memory off and `0` to
  force it on, and the 2.1.296 binary reads it before `autoMemoryEnabled`;
- `idleCompaction`: "Set to false to stop Claude Code from compacting a long
  conversation while the session is idle. Setting it to true does not turn idle
  compaction on" (its schema's description, 2.1.296). In that binary it's read
  from the highest settings source that sets it, `true` where none does, and
  idle compaction runs only where Claude Code's own rollout turns it on,
  auto-compaction is on, and the value isn't `false`;
- with `CLAUDE_CONFIG_DIR` set, the state file is `.claude.json` inside it;
- a hook's `command` runs in a shell, and its `timeout` is in seconds;
- `--strict-mcp-config` is "Only use MCP servers from --mcp-config, ignoring all
  other MCP configurations" (`cli-reference`), managed servers along with every
  other (`managed-mcp`); a stdio entry takes `command`, `args` and `timeout` in
  milliseconds (`mcp`). In the 2.1.296 binary a call's limit is the server's
  `timeout` where it's at least 1,000 ms, else `MCP_TOOL_TIMEOUT`, else about
  28 hours; a stdio call's idle limit is 30 minutes, raised to the server's
  `timeout`; and under `bypassPermissions` an MCP tool prompts only where it's
  marked as needing the user (`mcp`, *Require approval for a specific tool*);
- `--messaging-socket-path <path>` is "Cross-session messaging server path: a
  Unix domain socket on Mac/Linux" (the 2.1.296 binary's help, not in
  `--help`'s list). "When the receiving session is idle, Claude Code starts a
  new turn with the message", and a session that bypasses permission prompts
  holds incoming messages unless `crossSessionInbound` is `"accept"`
  (`cross-session-messaging`). The binary skips the socket in a session it
  counts as restricted, or where a server-side gate is off, each said in its
  debug log; neither is checked in a room yet;
- `--dangerously-load-development-channels <servers...>` is "Load channel
  servers not on the approved allowlist. For local channel development only.
  Shows a confirmation dialog at startup" (the 2.1.304 binary's help); a
  `server:<name>` entry is a "manually configured MCP server", matched by name,
  an `--mcp-config` server among them (`channels-reference`, *Test during the
  research preview*; measured on 2.1.304, `docs/field-notes.md`, *Channels*);
- a single file mounted into the room can't be replaced by a rename ("Device or
  resource busy"), and Claude Code's writer falls back to writing in place
  ("in-place fallback write", in the binary), so the mounted state file stays
  writable.
"""

import json
from datetime import timedelta
from shlex import join
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import JsonValue, ValidationError
from pydantic.alias_generators import to_camel

from lup.adapters.claude.layout import ClaudeHome, ClaudeLaunch, ClaudeLayout
from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    WorktreeAsked,
)
from lup.rooms.container import Mount
from lup.sessions.configuration import Homed, configured, layered
from lup.sessions.terminal import (
    Cli,
    Preferences,
    Setting,
    Terminal,
    TerminalError,
)
from lup.types import Model

if TYPE_CHECKING:
    from pathlib import Path

    from lup.adapters.claude import Effort
    from lup.events import SessionEvent
    from lup.sessions.terminal import (
        Hook,
        RuntimeHome,
        TerminalSettings,
        ToolServer,
    )

# lup: defer(issue=52, why="Claude Code's variable, shared with an ask, a module constant until a `Spellings` each adapter implements gives it its home")
AUTO_MEMORY_OFF = "CLAUDE_CODE_DISABLE_AUTO_MEMORY"
"""The variable turning Claude Code's auto memory off (`1`) or on (`0`); an ask
sets it too, since auto memory loads whatever the settings sources say."""

SUBAGENT_CACHE = "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL"
"""The variable setting the prompt cache's lifetime outside the main conversation."""

CONNECTORS = "ENABLE_CLAUDEAI_MCP_SERVERS"
"""The variable that, false, keeps the account's claude.ai connectors from being fetched."""

KEEP_CALLS = "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS"
"""The variable after which a running MCP call moves to the background; `0` never moves it."""

NO_UPDATES = "DISABLE_AUTOUPDATER"
"""The variable turning off the CLI's own updater."""

CONFIG_DIR = "CLAUDE_CONFIG_DIR"
"""The variable moving Claude Code's directory."""

LONG_CONTEXT_OFF = "CLAUDE_CODE_DISABLE_1M_CONTEXT"
"""The variable keeping every model at the standard window, those with the long
one by default too (`model-config`, *Turn off 1M context*)."""

type Truthy = Literal["1", "true", "yes", "on"]
"""What Claude Code reads as a variable turned on, any case, around blanks (its
2.1.309 binary)."""


class Wire(Model, alias_generator=to_camel, populate_by_name=True):
    """A file Claude Code reads, its keys in camel case."""


class CommandHook(Wire):
    """A command Claude Code runs at a hook event."""

    type: str = "command"
    command: str
    timeout: int | None = None
    """In seconds; none keeps Claude Code's default."""


class HookGroup(Wire):
    """The hooks an event runs for the calls its matcher matches."""

    matcher: str | None = None
    hooks: list[CommandHook]


class Permissions(Wire):
    """The session's permission rules."""

    deny: list[str]


class StdioServer(Wire):
    """An MCP server Claude Code runs as a program speaking on its standard input and output."""

    type: str = "stdio"
    command: str
    args: list[str]
    timeout: int | None = None
    """In milliseconds; none keeps Claude Code's own limits."""


class Servers(Wire):
    """The file `--mcp-config` names: lup's tool servers, by name."""

    mcp_servers: dict[str, StdioServer]


def bridged(server: ToolServer, settings: TerminalSettings) -> StdioServer:
    """Return the entry for one of lup's tool servers: lup's bridge to its socket (`TerminalSettings.bridged`)."""
    program, *arguments = settings.bridged(server)
    return StdioServer(
        command=program,
        args=arguments,
        timeout=None
        if server.timeout is None
        else server.timeout // timedelta(milliseconds=1),
    )


class LaunchSettings(Wire):
    """lup's settings for a launched session, the file `--settings` names."""

    env: dict[str, str]
    """The session settings spelled as variables, which outrank the operator's."""
    hooks: dict[str, list[HookGroup]]
    permissions: Permissions
    idle_compaction: bool | None = None
    """False stops compaction while the session is idle; none leaves it to the
    operator's own settings."""
    disable_claude_ai_connectors: bool | None = None
    """True keeps the account's claude.ai connectors from being fetched; none
    leaves it to the operator's own settings."""
    cross_session_inbound: Literal["accept"] | None = None
    """`accept` delivers each message reaching the session's messaging socket,
    which a session bypassing permission prompts would hold for approval; none
    leaves it to the operator's own settings."""
    skip_dangerous_mode_permission_prompt: bool = True


class Trusted(Wire):
    """A folder whose trust question is answered."""

    has_trust_dialog_accepted: bool = True


class State(Wire):
    """The room's own state file: onboarding done, and its folders trusted."""

    has_completed_onboarding: bool = True
    projects: dict[str, Trusted]


class OwnSettings(Wire):
    """What lup reads of the operator's own Claude Code settings: which session settings they set themselves, and whether their `env` turns the long window off."""

    subagent_prompt_cache_ttl: Literal["5m", "1h"] | None = None
    auto_memory_enabled: bool | None = None
    idle_compaction: bool | None = None
    disable_claude_ai_connectors: bool | None = None
    env: dict[str, JsonValue] = {}
    """The variables Claude Code applies to its environment at start."""

    def sets(self) -> list[str]:
        """List the session settings their file sets, by lup's names: by the key, or by its variable in `env`."""
        spelled = {
            "subagent_cache": self.subagent_prompt_cache_ttl is not None
            or SUBAGENT_CACHE in self.env,
            "auto_memory": self.auto_memory_enabled is not None
            or AUTO_MEMORY_OFF in self.env,
            "idle_compaction": self.idle_compaction is not None,
            "account_connectors": self.disable_claude_ai_connectors is not None
            or CONNECTORS in self.env,
        }
        return [field for field, theirs in spelled.items() if theirs]

    def shortened(self) -> bool:
        """Return whether their `env` turns the long window off (`LONG_CONTEXT_OFF`), so every session it starts runs at the standard window.

        >>> OwnSettings(env={LONG_CONTEXT_OFF: " True "}).shortened(), OwnSettings().shortened()
        (True, False)
        """
        match self.env.get(LONG_CONTEXT_OFF):
            case str() as value:
                return value.strip().lower() in get_args(Truthy.__value__)
            case _:
                return False


def own_settings(settings: Path) -> OwnSettings:
    """Read the operator's own settings file at `settings`; empty where there's none."""
    if not settings.is_file():
        return OwnSettings()
    try:
        return OwnSettings.model_validate_json(settings.read_text())
    except ValidationError as failed:
        message = (
            f"the operator's Claude Code settings, {settings}, don't read: {failed}"
        )
        raise TerminalError(message) from failed


def spelled(event: type[SessionEvent]) -> list[str]:
    """Return Claude Code's hook events for one of lup's."""
    spellings: dict[type[SessionEvent], list[str]] = {
        SessionStarted: ["SessionStart"],
        TurnStarted: ["UserPromptSubmit"],
        CallStarted: ["PreToolUse"],
        WorktreeAsked: ["WorktreeCreate"],
        CallFinished: ["PostToolUse", "PostToolUseFailure"],
        TurnEnded: ["Stop", "StopFailure"],
        ConversationEnded: ["SubagentStop"],
    }
    return spellings[event]


class AtHome(Model):
    """What a terminal session of Claude Code gets on a home of the rooms' own: how its configuration and login reach the home, its own settings and state there, and the operator's settings as it reads them."""

    homed: Homed
    theirs: OwnSettings
    """The settings the session reads as its user settings, layered and with
    credentials left out, as lup reads which session settings they set."""
    preferences: Preferences | None


def at_home(home: RuntimeHome, layout: ClaudeLayout, launch: ClaudeLaunch) -> AtHome:
    """Return what a session of Claude Code gets on the home `home`, its layers below it the operator's directory where `home` keeps it, then `home`'s own.

    The settings, layered with what `ClaudeHome.blocked` names and any key
    named like a credential left out of each, are the launch's own file,
    mounted writable where Claude Code reads its user settings, so `/model`
    and the like save there; at the end, the launch carries what changed of
    the preferences into `home`'s own layer, where it has one. Raise
    `TerminalError` where a layer's settings don't read.
    """
    room = ClaudeHome(directory=home.directory)
    layers = [
        *([layout.directory] if home.operators else []),
        *([] if home.own is None else [home.own]),
    ]

    def blocked(path: list[str]) -> bool:
        return len(path) == 1 and path[0] in room.blocked

    settings = layered(layers, "settings.json", "json", blocked)
    try:
        theirs = OwnSettings.model_validate(settings.table)
    except ValidationError as failed:
        message = f"the settings layered for the room don't read: {failed}"
        raise TerminalError(message) from failed
    placed = configured(room.configuration, layers, room.directory, launch.home)
    own = [launch.home.own(name) for name in room.own]
    return AtHome(
        homed=Homed(
            copies=placed.copies,
            directories=[*placed.directories, *own],
            files={
                **placed.files,
                launch.home_settings: json.dumps(settings.table, indent=2),
            },
            mounts=[
                Mount(source=launch.home_settings, target=room.settings),
                Mount(source=launch.state, target=room.state),
                Mount(source=home.login, target=room.credentials),
                *(
                    Mount(source=launch.home.own(name), target=room.directory / name)
                    for name in room.own
                ),
                *placed.mounts,
            ],
            left=[*settings.left, *placed.left],
        ),
        theirs=theirs,
        preferences=None
        if home.own is None
        else Preferences(
            saved=launch.home_settings,
            into=home.own / "settings.json",
            syntax="json",
            written=[
                Setting(preference=each, value=each.held(settings.table))
                for each in room.preferences
            ],
        ),
    )


def compiled(
    model: str | None,
    system_prompt: str | None,
    effort: Effort | None,
    settings: TerminalSettings,
    layout: ClaudeLayout,
) -> Terminal:
    """Return the terminal session of Claude Code for a declaration's fields, with lup's settings."""
    launch = ClaudeLaunch(directory=settings.directory)
    cli = Cli(program=layout.bundled) if settings.cli is None else settings.cli
    home = None if settings.home is None else at_home(settings.home, layout, launch)
    session = settings.passed(
        OwnSettings().sets() if home is None else home.theirs.sets()
    )

    def group(hook: Hook) -> HookGroup:
        timeout = None if hook.timeout is None else int(hook.timeout.total_seconds())
        command = CommandHook(command=join(hook.command), timeout=timeout)
        return HookGroup(matcher=hook.matcher, hooks=[command])

    memory = (
        {}
        if session.auto_memory is None
        else {AUTO_MEMORY_OFF: "0" if session.auto_memory else "1"}
    )
    cache = (
        {}
        if session.subagent_cache is None
        else {
            SUBAGENT_CACHE: "1h"
            if session.subagent_cache == timedelta(hours=1)
            else "5m"
        }
    )
    events = dict.fromkeys(
        name for hook in settings.hooks for name in spelled(hook.event)
    )
    lup_settings = LaunchSettings(
        env={**memory, **cache},
        hooks={
            name: [
                group(hook) for hook in settings.hooks if name in spelled(hook.event)
            ]
            for name in events
        },
        permissions=Permissions(deny=session.removed_tools or []),
        idle_compaction=session.idle_compaction,
        disable_claude_ai_connectors=None
        if session.account_connectors is None
        else not session.account_connectors,
        cross_session_inbound=None if settings.messages is None else "accept",
    )
    state = State(
        projects={str(path): Trusted() for path in settings.trusted},
    )
    servers = Servers(
        mcp_servers={
            server.name: bridged(server, settings) for server in settings.servers
        }
    )
    pushing = [f"server:{server.name}" for server in settings.servers if server.pushes]
    channels = ["--dangerously-load-development-channels", *pushing] if pushing else []
    moved = {} if settings.home is None else {CONFIG_DIR: str(settings.home.directory)}
    prompt = {} if system_prompt is None else {launch.system_prompt: system_prompt}
    guidance = {} if settings.guidance is None else {launch.guidance: settings.guidance}
    served = (
        {
            launch.servers: servers.model_dump_json(
                by_alias=True, exclude_none=True, indent=2
            )
        }
        if settings.servers
        else {}
    )
    homed = Homed() if home is None else home.homed
    files: dict[Path, str] = {
        launch.settings: lup_settings.model_dump_json(
            by_alias=True, exclude_none=True, indent=2
        ),
        launch.state: state.model_dump_json(by_alias=True, indent=2),
        **served,
        **settings.bridges(),
        **prompt,
        **guidance,
        **homed.files,
    }
    return Terminal(
        command=[
            str(cli.program),
            "--setting-sources",
            "user",
            "--settings",
            str(launch.settings),
            "--permission-mode",
            "bypassPermissions",
            *(
                [
                    "--mcp-config",
                    str(launch.servers),
                    *channels,
                    "--strict-mcp-config",
                ]
                if settings.servers
                else []
            ),
            # lup: defer(issue=244, why="the binary skips the socket in a session it counts as restricted, or where a server-side gate is off, neither checked in a room")
            *(
                []
                if settings.messages is None
                else ["--messaging-socket-path", str(settings.messages)]
            ),
            *([] if model is None else ["--model", model]),
            *([] if effort is None else ["--effort", effort]),
            *(
                []
                if system_prompt is None
                else ["--system-prompt-file", str(launch.system_prompt)]
            ),
            *(
                []
                if settings.guidance is None
                else [
                    "--append-system-prompt-file",
                    str(launch.guidance),
                    "--system-prompt-snapshot",
                    "off",
                ]
            ),
        ],
        env={KEEP_CALLS: "0", NO_UPDATES: "1", **moved},
        files=files,
        directories=homed.directories,
        copies=homed.copies,
        mounts=[
            *([] if settings.home is None else [Mount(source=settings.home.directory)]),
            cli.mount,
            Mount(source=settings.directory, read_only=True),
            *(
                [
                    Mount(
                        source=launch.state, target=ClaudeLayout(home=layout.home).state
                    )
                ]
                if settings.home is None
                else []
            ),
            *homed.mounts,
        ],
        home=None if settings.home is None else settings.home.directory,
        left_out=homed.left,
        preferences=None if home is None else home.preferences,
    )
