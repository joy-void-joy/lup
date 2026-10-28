"""Codex in a terminal: the command line and requirements a launched session starts with.

lup's settings reach the session as flags, `-c` overrides on the configuration
of the home it runs on, and a requirements file of the launch's own, never
written into the operator's home or the repository (`docs/launch.md`, *The
settings compiled for each runtime*):
- `--no-daemon`, apart from the host's daemon on the same home, and
  `--dangerously-bypass-approvals-and-sandbox`: the room is the wall;
- the model with `--model` and the effort as `model_reasoning_effort`, each only
  where the declaration gives one: `--model` sets the model over the operator's
  configuration, so a declaration naming none leaves theirs to Codex, which reads
  it itself; and the declaration's system prompt as `instructions`, which
  replaces Codex's own;
- each trusted path in `projects`, as an inline table, since `-c` splits a dotted
  key at every `.`, which breaks a path like `lup.git`;
- the session settings (below); `check_for_update_on_startup = false`;
  `features.plugins = false`, which also stops a sync from GitHub at each start;
- lup's tool servers, the `mcp_servers` table (below);
- `project_doc_max_bytes = 0`, so the repository's `AGENTS.md` isn't loaded
  beside the guidance;
- lup's hooks as managed hooks, in a requirements file mounted at
  `/etc/codex/requirements.toml`, with `allow_managed_hooks_only` so no other hook
  runs **(leaning)**: managed hooks need no review, where hooks from any other
  source run only once trusted;
- the guidance as `additional_developer_instructions` in the same file (below);
- on a home of the rooms' own (`TerminalSettings.home`, `at_home`), `CODEX_HOME`
  naming it and `cli_auth_credentials_store = "file"`, so the login is the
  account's `auth.json`, never a keyring the room lacks; with none, the room's
  own home, gone with the launch.

**The home**: a directory of the rooms' own, mounted read-write at its path,
where Codex keeps its history and state; nothing of the operator's home is
mounted. Inside it, each item of configuration `CodexHome` names is mounted
read-only, the launch's copy of the layers holding it, the operator's home's
and then the home's own, or empty; `config.toml` is the launch's own, the
layers' merged with what would hand the room a credential left out
(`blocked`, `lup.sessions.configuration`), the operator's MCP servers among
it; each of Codex's own profiles, `<name>.config.toml`, is layered the same
way and mounted read-only, so `--profile` after `--` finds it; the
operator's `~/.agents/skills` is copied read-only into the room's home;
`shell_snapshots/`, `skills/` and `tmp/` are the launch's own, since Codex
runs a snapshot before each command, puts its `tmp/arg0/` helpers first on its
commands' `PATH`, and writes its own skills at each start; and `auth.json`
is the account's login, mounted alone, read-write. Codex 0.162.0 saves its
login in place, keeping the file and its mode, so a sign-in in a room reaches
the account's file through the mount; it reads an empty file as unreadable
rather than as no login, and `{}` as signed in, so a login made for an account
starts empty (measured in a room, `docs/field-notes.md`, *A home of the rooms'
own*).

**A declared gap:** Codex 0.162.0 saves its configuration by writing a new
file over `config.toml` (its inode changed, measured in a room), which a
single file mounted can't take ("Device or resource busy"), so a preference a
session saves there, `/model`'s choice among them, holds for that session
alone and isn't carried back; Codex says "Failed to save default model" (its
binary's text). The launch's copy marks `tui.screen_reader_detection_done`, so
the save Codex makes at each start isn't one of them.

| lup's event | Codex's hook event |
|---|---|
| `session-started` | `SessionStart` |
| `turn-started` | `UserPromptSubmit` |
| `call-started` | `PreToolUse` |
| `worktree-asked` | none: Codex never isolates a subagent in a worktree |
| `call-finished` | `PostToolUse` |
| `turn-ended` | `Stop` |
| `conversation-ended` | `SubagentStop` |

An event Codex has no hook for registers none, and its adapter declares the gap
(`lup_dev.adapters.codex`).

**The session settings** are `-c` overrides, which outrank the home's
`config.toml`: each one the settings impose (`TerminalSettings.session`), and
each of lup's defaults the layered configuration doesn't set
(`OperatorConfig.sets`, read once at launch), so theirs outrank lup's defaults. Auto memory switches
the `memories` feature, and the account's connectors the `apps` feature, which
is what Codex calls them. Each is spelled `features.<key>`, and also by each
older key their `[features]` table sets for it (`memory_tool`, `connectors`):
Codex applies the table's entries in the order of their keys, an older key
switching the same feature, so their `connectors = true` would apply after
lup's `apps = false` alone. Theirs count as set by either key.

**lup's tool servers** are stdio servers, each lup's bridge to the server's
socket (`lup.sessions.bridge`, written into the launch's directory and mounted
read-only at its path), which carries the session across the server's
restarts, with the server's timeout as `tool_timeout_sec`
where it gives one (Codex's own is 300 s) and `default_tools_approval_mode =
"approve"`, so no call asks. They're the whole `mcp_servers` table: the
operator's are left out of the home's configuration, so none of theirs lends
lup's its keys, as Codex would merge a table of one name key by key. Their
tools stay behind Codex's tool search where the model has it: no
`omit_tools_from`.

**The guidance** is Codex's managed developer instructions, which it keeps in a
thread's state by their hash and, at a resume where they changed, sends again
whole as replacing the earlier ones, so a conversation from an earlier launch
runs under this launch's guidance. `developer_instructions` reach a thread once,
in its first context, and a resumed thread again only once it's compacted.
Codex refuses to start where the managed instructions pass 10,000 estimated
tokens, counted as it would send them at such a resume, at 4 bytes a token, so
the compile refuses guidance past that first, naming its size, rather than fall
back to `developer_instructions` and leave a resumed thread the stale guidance.
A workspace's own managed requirements outrank the system file, so a workspace
setting managed instructions of its own drops lup's.

**Declared gaps.** Codex 0.162.1 has no setting for the prompt cache's lifetime,
and can't remove a built-in tool by name, only whole feature groups, so a
session's `subagent_cache` and `removed_tools` have nothing to compile to here.
Nor does it compact while a session is idle, so `idle_compaction` has nothing
to turn off: its compaction runs when the context passes
`model_auto_compact_token_limit`, and at a turn's end past
`model_post_turn_compact_threshold_percent`, off unless set
(`config/src/config_toml.rs`; the 0.162.1 binary names no other setting for
it), both left to the operator. And nothing reaches a session idle between its
turns, so `messages` and a tool server's `pushes` have nothing to compile to:
what a server sends unprompted is only logged
(`rmcp-client/src/logging_client_handler.rs`), and the app-server that could
start a turn (`turn/start`) runs inside the terminal's own process under
`--no-daemon`, out of reach. A message waits for the session's next call; the
operator typing in its terminal starts one, whose `UserPromptSubmit` tells it.

**TOML.** Each `-c` value and the requirements file are TOML, written by
`tomlkit`: a `-c` value on one line, its tables inline, and the requirements file
as a document.

What this relies on, read in Codex's source at `rust-v0.162.1` (paths under
`codex-rs/`):
- `-c key=value` parses the value as TOML, and takes it as a plain string when it
  doesn't parse (`utils/cli/src/config_override.rs`); the overrides are one layer,
  merged into the operator's configuration table by table (`config/src/merge.rs`),
  so `mcp_servers = {name = {enabled = false}}` keeps each server's command; and
  within the layer, a later override of the same key replaces the earlier
  (`config/src/overrides.rs`);
- an MCP server's entry takes `command`, `args`, `tool_timeout_sec` (seconds,
  read as a float, with no cap) and `default_tools_approval_mode`, and refuses
  a `url` beside a `command` ("url is not supported for stdio",
  `config/src/mcp_types.rs`); a call's limit is 300 s without it
  (`codex-mcp/src/rmcp_client.rs`), and progress doesn't extend it. `approve`
  answers every permission prompt of the server's tools
  (`codex-mcp/src/mcp/mod.rs`), as approval `never` with full access does too;
- a result with `structuredContent` shows the model only that, its content
  blocks dropped (`protocol/src/models.rs`), which is why lup's results carry
  none (`lup.tools.serving`);
- the requirements file is `/etc/codex/requirements.toml` on Unix
  (`config/src/loader/mod.rs`); its `hooks` table holds the events' matcher
  groups as a `hooks.json` does, and `allow_managed_hooks_only` there skips every
  hook that isn't managed (`hooks/src/engine/discovery.rs`);
- at `rust-v0.163.0`: `additional_developer_instructions` is a string of the
  requirements (`config/src/config_requirements.rs`), whose sources merge in
  ascending precedence, the system file lowest, below a workspace's cloud
  requirements and managed preferences (`config/src/loader/mod.rs`). The
  managed instructions are a developer message of their own between
  `<managed_developer_instructions>` markers, kept in the thread's world state
  by their hash: unchanged, nothing is sent; changed, they're sent whole,
  opening "These managed developer instructions replace all previously provided
  managed developer instructions." Codex refuses them past "the model-context
  limit of 10000 estimated tokens", counted with that notice and the markers
  (`core/src/context/world_state/managed_developer_instructions.rs`), at 4 bytes
  a token (`utils/string/src/truncate.rs`, `approx_bytes_for_tokens`).
  `developer_instructions` are part of a thread's initial context, written only
  to a thread with no recorded turn context, which a resumed thread has from its
  rollout, and again at a compaction (`core/src/session/mod.rs`,
  `core/src/compact.rs`);
- `instructions` becomes the base instructions when nothing else sets them
  (`core/src/config/mod.rs`); `features.memories` is the memories feature's
  switch, off by default, and `features.apps` the apps', on by default
  (`features/src/lib.rs`);
- the `[features]` table's switches are a `BTreeMap`, applied in the order of
  their keys (`features/src/lib.rs`, `apply_map`), and `memory_tool` and
  `connectors` are older keys for `memories` and `apps` (`features/src/legacy.rs`);
- a `profile` key in `config.toml` is refused, and a profile's own file,
  `$CODEX_HOME/<name>.config.toml`, is read only with `--profile`
  (`core/src/config/mod.rs`; the `config-advanced` docs), which lup doesn't
  pass and the operator may, after `--`.
"""

from datetime import timedelta
from math import ceil
from shlex import join
from typing import TYPE_CHECKING

import tomlkit
from pydantic import JsonValue, ValidationError
from tomlkit.exceptions import ConvertError

from lup.adapters.codex.layout import (
    MANAGED_REQUIREMENTS,
    CodexHome,
    CodexLaunch,
    CodexLayout,
)
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
from lup.sessions.configuration import Homed, configured, fits, layered, merged
from lup.sessions.terminal import (
    Cli,
    Copy,
    Preferences,
    Setting,
    Terminal,
    TerminalError,
)
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from lup.adapters.codex import Effort
    from lup.events import SessionEvent
    from lup.sessions.terminal import (
        Hook,
        RuntimeHome,
        TerminalSettings,
        ToolServer,
    )


def toml(value: JsonValue) -> str:
    """Return `value` as a TOML value on one line, its tables inline.

    It's written as `tomlkit` writes an array's item, which is how it writes a
    table inline, and every table inside it too.

    >>> toml({"/srv/lup.git": {"trust_level": "trusted"}})
    '{"/srv/lup.git" = {trust_level = "trusted"}}'
    """
    try:
        return tomlkit.item(value, _parent=tomlkit.array()).as_string()
    except ConvertError as failed:
        message = f"{value!r} has no TOML value: {failed}"
        raise TerminalError(message) from failed


class Feature(Model):
    """A Codex feature a session setting switches: its key in `[features]`, and the older keys Codex still reads for it."""

    key: str
    older: list[str] = []


MEMORIES = Feature(key="memories", older=["memory_tool"])
"""Codex's memories: the session's auto memory."""

APPS = Feature(key="apps", older=["connectors"])
"""Codex's apps: the account's connectors."""


class OperatorConfig(Model):
    """The part of the configuration a terminal session reads as its own that lup reads: the features it switches."""

    features: dict[str, JsonValue] = {}

    def keys(self, feature: Feature) -> list[str]:
        """Return the keys their `[features]` table switches `feature` by."""
        return [key for key in [feature.key, *feature.older] if key in self.features]

    def sets(self) -> list[str]:
        """List the session settings their configuration sets, by lup's names."""
        switched = {"auto_memory": MEMORIES, "account_connectors": APPS}
        return [field for field, feature in switched.items() if self.keys(feature)]


def blocked(path: list[str]) -> bool:
    """Say whether a key of Codex's configuration, by its path, is left out of a room's copy beside any named like a credential.

    The operator's MCP servers, set up for the host, whose `env` often holds a
    credential named otherwise; the variables `shell_environment_policy` sets
    in every command's environment; and the headers of any `otel` exporter,
    which carry its key whatever they're named.

    >>> [blocked(path) for path in [["mcp_servers"], ["otel", "exporter", "otlp-http", "headers"], ["model"]]]
    [True, True, False]
    """
    match path:
        case ["mcp_servers"] | ["shell_environment_policy", "set"]:
            return True
        case ["otel", *_, "headers"]:
            return True
        case _:
            return False


class AtHome(Model):
    """What a terminal session of Codex gets on a home of the rooms' own: how its configuration and login reach the home, its own configuration there, and the operator's as lup reads it."""

    homed: Homed
    theirs: OperatorConfig
    preferences: Preferences | None


def at_home(home: RuntimeHome, layout: CodexLayout, launch: CodexLaunch) -> AtHome:
    """Return what a session of Codex gets on the home `home`, its layers below it the operator's Codex home where `home` keeps it, then `home`'s own.

    The configuration, layered with what `blocked` names and any key named
    like a credential left out of each, is the launch's own `config.toml`,
    mounted writable where Codex reads it; each of Codex's own profiles a
    layer holds, `<name>.config.toml`, is layered the same way and mounted
    read-only. The operator's `~/.agents/skills`, where `home` keeps their
    layer, is copied and mounted read-only where Codex reads it in the room's
    home. Raise `TerminalError` where a layer's configuration doesn't read.
    """
    room = CodexHome(directory=home.directory)
    layers = [
        *([layout.operator_home] if home.operators else []),
        *([] if home.own is None else [home.own]),
    ]
    config = layered(layers, "config.toml", "toml", blocked)
    try:
        theirs = OperatorConfig.model_validate(config.table)
    except ValidationError as failed:
        message = f"the configuration layered for the room doesn't read: {failed}"
        raise TerminalError(message) from failed
    detected: JsonObject = {"tui": {"screen_reader_detection_done": True}}
    written = merged(detected, config.table)
    names = dict.fromkeys(
        each.name
        for layer in layers
        for each in sorted(layer.glob("*.config.toml"))
        if fits(each, directory=False)
    )
    profiles = {name: layered(layers, name, "toml", blocked) for name in names}
    placed = configured(room.configuration, layers, room.directory, launch.home)
    skills = layout.user_skills if home.operators else None
    copied = skills is not None and fits(skills, directory=True)
    own = [launch.home.own(name) for name in room.own]
    return AtHome(
        homed=Homed(
            copies=[
                *placed.copies,
                *(
                    [
                        Copy(
                            source=skills,
                            destination=launch.home.copied(".agents-skills"),
                        )
                    ]
                    if copied and skills is not None
                    else []
                ),
            ],
            directories=[*placed.directories, *own],
            files={
                **placed.files,
                launch.home_config: tomlkit.dumps(written),
                **{
                    launch.home.copied(name): tomlkit.dumps(each.table)
                    for name, each in profiles.items()
                },
            },
            mounts=[
                Mount(source=launch.home_config, target=room.config),
                Mount(source=home.login, target=room.login),
                *(
                    Mount(source=launch.home.own(name), target=room.directory / name)
                    for name in room.own
                ),
                *placed.mounts,
                *(
                    Mount(
                        source=launch.home.copied(name),
                        target=room.profile(name),
                        read_only=True,
                    )
                    for name in profiles
                ),
                *(
                    [
                        Mount(
                            source=launch.home.copied(".agents-skills"),
                            target=skills,
                            read_only=True,
                        )
                    ]
                    if copied and skills is not None
                    else []
                ),
            ],
            left=[
                *config.left,
                *(left for each in profiles.values() for left in each.left),
                *placed.left,
                *(
                    [f"{skills}, which is a link lup doesn't follow"]
                    if skills is not None and skills.is_symlink()
                    else []
                ),
            ],
        ),
        theirs=theirs,
        preferences=None
        if home.own is None
        else Preferences(
            saved=launch.home_config,
            into=home.own / "config.toml",
            syntax="toml",
            written=[
                Setting(preference=each, value=each.held(written))
                for each in room.preferences
            ],
        ),
    )


class Override(Model):
    """One `-c` override: a dotted key, and its value."""

    key: str
    value: JsonValue

    def argument(self) -> str:
        """Return the override as `-c` takes it."""
        return f"{self.key}={toml(self.value)}"


def switching(
    feature: Feature, theirs: OperatorConfig, *, on: bool | None
) -> list[Override]:
    """Return the overrides switching `feature` on or off; none where `on` is none.

    Its key, and each older key their configuration switches it by, so whichever
    Codex applies last agrees.
    """
    if on is None:
        return []
    keys = dict.fromkeys([feature.key, *theirs.keys(feature)])
    return [Override(key=f"features.{key}", value=on) for key in keys]


class CommandHook(Model):
    """A command Codex runs at a hook event."""

    type: str = "command"
    command: str
    timeout: int | None = None
    """In seconds; none keeps Codex's default."""


class HookGroup(Model):
    """The hooks an event runs for the calls its matcher matches."""

    matcher: str | None = None
    hooks: list[CommandHook]


MANAGED_OPENS = "<managed_developer_instructions>"
"""The marker Codex opens its managed developer instructions with."""

MANAGED_CLOSES = "</managed_developer_instructions>"
"""The marker Codex closes its managed developer instructions with."""

MANAGED_REPLACES = (
    "These managed developer instructions replace all previously provided managed "
    "developer instructions."
)
"""The notice opening the managed instructions where they're sent again, changed."""


def managed(guidance: str, tokens: int = 10_000, bytes_per_token: int = 4) -> str:
    """Return `guidance` as Codex's managed developer instructions, held to the size Codex takes.

    Codex counts them as it would send them at a resume where they changed,
    between its markers and after its notice, and refuses to start where that
    passes `tokens` estimated tokens of `bytes_per_token` bytes. Raise
    `TerminalError` there, naming the guidance's size and the limit, rather than
    launch a session Codex would refuse.
    """
    wrapped = f"{MANAGED_OPENS}\n{MANAGED_REPLACES}\n\n{guidance}\n{MANAGED_CLOSES}"
    sent = len(wrapped.encode())
    if sent > tokens * bytes_per_token:
        message = (
            f"the guidance is {len(guidance.encode()):,} bytes, {sent:,} as Codex "
            f"sends it between its markers: about {ceil(sent / bytes_per_token):,} "
            f"estimated tokens at {bytes_per_token} bytes each, past the "
            f"{tokens:,} Codex takes as managed developer instructions, so it "
            "wouldn't start. Shorten the guidance's sections to launch Codex."
        )
        raise TerminalError(message)
    return guidance


class Requirements(Model):
    """The launch's managed requirements: lup's hooks, and no others; and the guidance."""

    allow_managed_hooks_only: bool = True
    additional_developer_instructions: str | None = None
    """The guidance, as Codex's managed developer instructions: a developer
    message of their own, which Codex sends again whole at a resume where they
    changed; none gives none."""
    hooks: dict[str, list[HookGroup]]


class StdioServer(Model):
    """An MCP server Codex runs as a program speaking on its standard input and output."""

    command: str
    args: list[str]
    tool_timeout_sec: int | None = None
    """In seconds; none keeps Codex's own limit, 300 s."""
    default_tools_approval_mode: str = "approve"
    """Every call to the server's tools approved without asking."""


def bridged(server: ToolServer, settings: TerminalSettings) -> StdioServer:
    """Return the entry for one of lup's tool servers: lup's bridge to its socket (`TerminalSettings.bridged`)."""
    program, *arguments = settings.bridged(server)
    return StdioServer(
        command=program,
        args=arguments,
        tool_timeout_sec=None
        if server.timeout is None
        else server.timeout // timedelta(seconds=1),
    )


def served(settings: TerminalSettings) -> JsonObject:
    """Return the `mcp_servers` table: lup's servers, the only ones, since the operator's are left out of a room's configuration (`blocked`)."""
    return {
        server.name: bridged(server, settings).model_dump(
            mode="json", exclude_none=True
        )
        for server in settings.servers
    }


def spelled(event: type[SessionEvent]) -> str | None:
    """Return Codex's hook event for one of lup's; none where Codex has none."""
    spellings: dict[type[SessionEvent], str | None] = {
        SessionStarted: "SessionStart",
        TurnStarted: "UserPromptSubmit",
        CallStarted: "PreToolUse",
        WorktreeAsked: None,
        CallFinished: "PostToolUse",
        TurnEnded: "Stop",
        ConversationEnded: "SubagentStop",
    }
    return spellings[event]


def compiled(
    model: str | None,
    system_prompt: str | None,
    effort: Effort | None,
    settings: TerminalSettings,
    layout: CodexLayout,
) -> Terminal:
    """Return the terminal session of Codex for a declaration's fields, with lup's settings."""
    launch = CodexLaunch(directory=settings.directory)
    home = None if settings.home is None else at_home(settings.home, layout, launch)
    theirs = OperatorConfig() if home is None else home.theirs
    session = settings.passed(theirs.sets())
    cli = (
        Cli(program=layout.bundled_cli, directory=layout.bundled)
        if settings.cli is None
        else settings.cli
    )
    servers = served(settings)

    def group(hook: Hook) -> HookGroup:
        timeout = None if hook.timeout is None else int(hook.timeout.total_seconds())
        command = CommandHook(command=join(hook.command), timeout=timeout)
        return HookGroup(matcher=hook.matcher, hooks=[command])

    events = dict.fromkeys(
        name for hook in settings.hooks if (name := spelled(hook.event)) is not None
    )
    requirements = Requirements(
        additional_developer_instructions=None
        if settings.guidance is None
        else managed(settings.guidance),
        hooks={
            name: [
                group(hook) for hook in settings.hooks if spelled(hook.event) == name
            ]
            for name in events
        },
    )
    written = tomlkit.dumps(requirements.model_dump(mode="json", exclude_none=True))
    overrides = [
        *(
            []
            if effort is None
            else [Override(key="model_reasoning_effort", value=effort)]
        ),
        *(
            []
            if system_prompt is None
            else [Override(key="instructions", value=system_prompt)]
        ),
        *(
            [
                Override(
                    key="projects",
                    value={
                        str(path): {"trust_level": "trusted"}
                        for path in settings.trusted
                    },
                )
            ]
            if settings.trusted
            else []
        ),
        *switching(MEMORIES, theirs, on=session.auto_memory),
        Override(key="check_for_update_on_startup", value=False),
        *switching(APPS, theirs, on=session.account_connectors),
        Override(key="features.plugins", value=False),
        *([Override(key="mcp_servers", value=servers)] if servers else []),
        Override(key="project_doc_max_bytes", value=0),
        *(
            []
            if home is None
            else [Override(key="cli_auth_credentials_store", value="file")]
        ),
    ]
    homed = Homed() if home is None else home.homed
    return Terminal(
        command=[
            str(cli.program),
            "--no-daemon",
            "--dangerously-bypass-approvals-and-sandbox",
            *([] if model is None else ["--model", model]),
            *(
                argument
                for override in overrides
                for argument in ["-c", override.argument()]
            ),
        ],
        env={}
        if settings.home is None
        else {"CODEX_HOME": str(settings.home.directory)},
        files={launch.requirements: written, **settings.bridges(), **homed.files},
        directories=homed.directories,
        copies=homed.copies,
        mounts=[
            *([] if settings.home is None else [Mount(source=settings.home.directory)]),
            cli.mount,
            Mount(
                source=launch.requirements,
                target=MANAGED_REQUIREMENTS,
                read_only=True,
            ),
            *(Mount(source=path, read_only=True) for path in settings.bridges()),
            *homed.mounts,
        ],
        home=None if settings.home is None else settings.home.directory,
        left_out=homed.left,
        preferences=None if home is None else home.preferences,
    )
