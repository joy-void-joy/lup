"""Codex in a terminal: the command line and requirements a launched session starts with.

lup's settings reach the session as flags, `-c` overrides on the operator's own
home, and a requirements file of the launch's own, never written into the
operator's home or the repository (`docs/launch.md`, *The settings compiled for
each runtime*):
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
  each of the operator's own MCP servers, read from their `config.toml`, off by
  name, since they're set up for the host;
- lup's tool servers, in the same `mcp_servers` table that turns theirs off
  (below);
- the guidance as `developer_instructions`, with `project_doc_max_bytes = 0`, so
  the repository's `AGENTS.md` isn't loaded beside it;
- lup's hooks as managed hooks, in a requirements file mounted at
  `/etc/codex/requirements.toml`, with `allow_managed_hooks_only` so no other hook
  runs **(leaning)**: managed hooks need no review, where hooks from any other
  source run only once trusted;
- `CODEX_HOME`, the operator's home, mounted read-write at its path for their
  login, settings and history.

| lup's event | Codex's hook event |
|---|---|
| `session-started` | `SessionStart` |
| `call-started` | `PreToolUse` |
| `call-finished` | `PostToolUse` |
| `turn-ended` | `Stop` |
| `conversation-ended` | `SubagentStop` |

**The session settings** are `-c` overrides, which outrank the operator's
`config.toml`: each one the settings impose (`TerminalSettings.session`), and
each of lup's defaults their configuration doesn't set (`OperatorConfig.sets`,
read once at launch), so theirs outrank lup's defaults. Auto memory switches
the `memories` feature, and the account's connectors the `apps` feature, which
is what Codex calls them. Each is spelled `features.<key>`, and also by each
older key their `[features]` table sets for it (`memory_tool`, `connectors`):
Codex applies the table's entries in the order of their keys, an older key
switching the same feature, so their `connectors = true` would apply after
lup's `apps = false` alone. Theirs count as set by either key.

**lup's tool servers** are stdio servers, each `socat STDIO UNIX-CONNECT:<socket>`,
a bridge from its standard input and output to the server's socket (socat is in
every room, for the hooks), with the server's timeout as `tool_timeout_sec`
where it gives one (Codex's own is 300 s) and `default_tools_approval_mode =
"approve"`, so no call asks. They go in one `mcp_servers` table with the
operator's turned off, since a later `-c` of the same key replaces an earlier
one. Codex merges that table into theirs key by key, so a server of theirs
named as one of lup's would lend lup's its other keys (`enabled_tools`, `env`,
`url`, which Codex then refuses beside `command`): such a configuration is
refused, naming the server. Their tools stay behind Codex's tool search where
the model has it: no `omit_tools_from`.

**Declared gaps.** Codex 0.162.1 has no setting for the prompt cache's lifetime,
and can't remove a built-in tool by name, only whole feature groups, so a
session's `subagent_cache` and `removed_tools` have nothing to compile to here.
Nor does it compact while a session is idle, so `idle_compaction` has nothing
to turn off: its compaction runs when the context passes
`model_auto_compact_token_limit`, and at a turn's end past
`model_post_turn_compact_threshold_percent`, off unless set
(`config/src/config_toml.rs`; the 0.162.1 binary names no other setting for
it), both left to the operator. And nothing reaches a session idle between its
turns, so `messages` has nothing to compile to: what a server sends unprompted
is only logged (`rmcp-client/src/logging_client_handler.rs`), and the
app-server that could start a turn (`turn/start`) runs inside the terminal's own
process under `--no-daemon`, out of reach. A message waits for the session's
next call; the operator typing in its terminal starts one.

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
- `instructions` becomes the base instructions when nothing else sets them
  (`core/src/config/mod.rs`); `features.memories` is the memories feature's
  switch, off by default, and `features.apps` the apps', on by default
  (`features/src/lib.rs`);
- the `[features]` table's switches are a `BTreeMap`, applied in the order of
  their keys (`features/src/lib.rs`, `apply_map`), and `memory_tool` and
  `connectors` are older keys for `memories` and `apps` (`features/src/legacy.rs`);
- a `profile` key in `config.toml` is refused, and a profile's own file is read
  only with `--profile` (`core/src/config/mod.rs`), which a launch doesn't pass,
  so their `config.toml` is all of the operator's configuration a launch reads.
"""

import tomllib
from datetime import timedelta
from shlex import join
from typing import TYPE_CHECKING

import tomlkit
from pydantic import JsonValue, ValidationError
from tomlkit.exceptions import ConvertError

from lup.adapters.codex.layout import MANAGED_REQUIREMENTS, CodexLaunch, CodexLayout
from lup.rooms.container import Mount
from lup.sessions.terminal import Cli, Terminal, TerminalError
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from pathlib import Path

    from lup.adapters.codex import Effort
    from lup.sessions.terminal import Event, Hook, TerminalSettings, ToolServer


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
    """The part of the operator's Codex configuration a terminal session reads: the features they switch, the servers a room turns off."""

    features: dict[str, JsonValue] = {}
    mcp_servers: dict[str, JsonObject] = {}

    def keys(self, feature: Feature) -> list[str]:
        """Return the keys their `[features]` table switches `feature` by."""
        return [key for key in [feature.key, *feature.older] if key in self.features]

    def sets(self) -> list[str]:
        """List the session settings their configuration sets, by lup's names."""
        switched = {"auto_memory": MEMORIES, "account_connectors": APPS}
        return [field for field, feature in switched.items() if self.keys(feature)]


def operator(config: Path) -> OperatorConfig:
    """Read the operator's Codex configuration at `config`; an empty one where they have none."""
    if not config.is_file():
        return OperatorConfig()
    try:
        read = tomllib.loads(config.read_text())
    except tomllib.TOMLDecodeError as failed:
        message = (
            f"the operator's Codex configuration, {config}, isn't valid TOML: {failed}"
        )
        raise TerminalError(message) from failed
    try:
        return OperatorConfig.model_validate(read)
    except ValidationError as failed:
        message = (
            f"the operator's Codex configuration, {config}, doesn't read: {failed}"
        )
        raise TerminalError(message) from failed


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


class Requirements(Model):
    """The launch's managed requirements: lup's hooks, and no others."""

    allow_managed_hooks_only: bool = True
    hooks: dict[str, list[HookGroup]]


class StdioServer(Model):
    """An MCP server Codex runs as a program speaking on its standard input and output."""

    command: str
    args: list[str]
    tool_timeout_sec: int | None = None
    """In seconds; none keeps Codex's own limit, 300 s."""
    default_tools_approval_mode: str = "approve"
    """Every call to the server's tools approved without asking."""


def bridged(server: ToolServer) -> StdioServer:
    """Return the entry for one of lup's tool servers: `socat` bridging standard input and output to its socket."""
    return StdioServer(
        command="socat",
        args=["STDIO", f"UNIX-CONNECT:{server.socket}"],
        tool_timeout_sec=None
        if server.timeout is None
        else server.timeout // timedelta(seconds=1),
    )


def served(
    settings: TerminalSettings, theirs: OperatorConfig, config: Path
) -> JsonObject:
    """Return the `mcp_servers` table: each of the operator's servers turned off, and lup's.

    Raise `TerminalError` where a server of theirs, in `config`, is named as one
    of lup's, which Codex would merge into lup's rather than replace.
    """
    shared = [
        server.name for server in settings.servers if server.name in theirs.mcp_servers
    ]
    if shared:
        message = (
            f"the operator's Codex configuration, {config}, names an MCP server "
            f"{', '.join(shared)}, as lup's own is: Codex would merge lup's server "
            "into theirs key by key rather than replace it, so rename theirs"
        )
        raise TerminalError(message)
    off: JsonObject = {name: {"enabled": False} for name in theirs.mcp_servers}
    lups: JsonObject = {
        server.name: bridged(server).model_dump(mode="json", exclude_none=True)
        for server in settings.servers
    }
    return {**off, **lups}


def spelled(event: Event) -> str:
    """Return Codex's hook event for one of lup's."""
    match event:
        case "session-started":
            return "SessionStart"
        case "call-started":
            return "PreToolUse"
        case "call-finished":
            return "PostToolUse"
        case "turn-ended":
            return "Stop"
        case "conversation-ended":
            return "SubagentStop"


def compiled(
    model: str | None,
    system_prompt: str | None,
    effort: Effort | None,
    settings: TerminalSettings,
    layout: CodexLayout,
) -> Terminal:
    """Return the terminal session of Codex for a declaration's fields, with lup's settings."""
    launch = CodexLaunch(directory=settings.directory)
    theirs = operator(layout.operator_config)
    session = settings.passed(theirs.sets())
    cli = (
        Cli(program=layout.bundled_cli, directory=layout.bundled)
        if settings.cli is None
        else settings.cli
    )
    servers = served(settings, theirs, layout.operator_config)

    def group(hook: Hook) -> HookGroup:
        timeout = None if hook.timeout is None else int(hook.timeout.total_seconds())
        command = CommandHook(command=join(hook.command), timeout=timeout)
        return HookGroup(matcher=hook.matcher, hooks=[command])

    events = dict.fromkeys(spelled(hook.event) for hook in settings.hooks)
    requirements = Requirements(
        hooks={
            name: [
                group(hook) for hook in settings.hooks if spelled(hook.event) == name
            ]
            for name in events
        }
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
        *(
            []
            if settings.guidance is None
            else [Override(key="developer_instructions", value=settings.guidance)]
        ),
        Override(key="project_doc_max_bytes", value=0),
    ]
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
        env={"CODEX_HOME": str(layout.operator_home)},
        files={launch.requirements: written},
        mounts=[
            Mount(source=layout.operator_home),
            cli.mount,
            Mount(
                source=launch.requirements,
                target=MANAGED_REQUIREMENTS,
                read_only=True,
            ),
        ],
    )
