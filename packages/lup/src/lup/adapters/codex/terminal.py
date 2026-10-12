"""Codex in a terminal: the command line and requirements a launched session starts with.

lup's settings reach the session as flags, `-c` overrides on the operator's own
home, and a requirements file of the launch's own, never written into the
operator's home or the repository (`docs/launch.md`, *The settings compiled for
each runtime*):
- `--no-daemon`, apart from the host's daemon on the same home, and
  `--dangerously-bypass-approvals-and-sandbox`: the room is the wall;
- the model with `--model`, the effort as `model_reasoning_effort`, and the
  declaration's system prompt as `instructions`, which replaces Codex's own;
- each trusted path in `projects`, as an inline table, since `-c` splits a dotted
  key at every `.`, which breaks a path like `lup.git`;
- auto memory as `features.memories`; `check_for_update_on_startup = false`;
  `features.plugins = false`, which also stops a sync from GitHub at each start;
  each of the operator's own MCP servers, read from their `config.toml`, off by
  name, since they're set up for the host;
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

**Declared gaps.** Codex 0.162.1 has no setting for the prompt cache's lifetime,
and can't remove a built-in tool by name, only whole feature groups, so a
session's `subagent_cache` and `removed_tools` have nothing to compile to here.

**TOML.** Each `-c` value and the requirements file are TOML. The standard library
reads TOML but doesn't write it, so until a TOML writer is one of lup's
dependencies, each value is written here: its strings as JSON, which TOML's basic
strings read the same way, its tables inline, and every text read back with
`tomllib` and compared with the value, so a value TOML would read otherwise
raises instead of reaching Codex.

What this relies on, read in Codex's source at `rust-v0.162.1` (paths under
`codex-rs/`):
- `-c key=value` parses the value as TOML, and takes it as a plain string when it
  doesn't parse (`utils/cli/src/config_override.rs`); the overrides are one layer,
  merged into the operator's configuration table by table (`config/src/merge.rs`),
  so `mcp_servers = {name = {enabled = false}}` keeps each server's command;
- the requirements file is `/etc/codex/requirements.toml` on Unix
  (`config/src/loader/mod.rs`); its `hooks` table holds the events' matcher
  groups as a `hooks.json` does, and `allow_managed_hooks_only` there skips every
  hook that isn't managed (`hooks/src/engine/discovery.rs`);
- `instructions` becomes the base instructions when nothing else sets them
  (`core/src/config/mod.rs`); `features.memories` is the memories feature's
  switch (`features/src/lib.rs`).
"""

import json
import tomllib
from shlex import join
from typing import TYPE_CHECKING

from pydantic import JsonValue

from lup.adapters.codex.layout import MANAGED_REQUIREMENTS, CodexLaunch, CodexLayout
from lup.rooms.container import Mount
from lup.sessions.terminal import Terminal, TerminalError
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from pathlib import Path

    from lup.adapters.codex.runtime import Effort
    from lup.sessions.terminal import Event, Hook, TerminalSettings


class Parsed(Model):
    """A TOML value, read back."""

    value: JsonValue


def toml(value: JsonValue) -> str:
    """Return `value` as TOML on one line, checked by reading it back.

    >>> toml({"/srv/lup.git": {"trust_level": "trusted"}})
    '{"/srv/lup.git" = {"trust_level" = "trusted"}}'
    """

    def written(each: JsonValue) -> str:
        match each:
            case bool() | int():
                return json.dumps(each)
            case str():
                return json.dumps(each, ensure_ascii=False)
            case list():
                return "[" + ", ".join(written(item) for item in each) + "]"
            case dict():
                pairs = [
                    f"{json.dumps(key, ensure_ascii=False)} = {written(item)}"
                    for key, item in each.items()
                ]
                return "{" + ", ".join(pairs) + "}"
            case float() | None:
                message = f"lup writes no {type(each).__name__} as TOML: {each!r}"
                raise TerminalError(message)

    text = written(value)
    try:
        parsed = Parsed.model_validate(tomllib.loads(f"value = {text}"))
    except tomllib.TOMLDecodeError as failed:
        message = f"{value!r} doesn't write as TOML: {failed}"
        raise TerminalError(message) from failed
    if parsed.value != value:
        message = f"{value!r} reads back from TOML as {parsed.value!r}"
        raise TerminalError(message)
    return text


class OperatorConfig(Model):
    """The part of the operator's Codex configuration a room turns off."""

    mcp_servers: dict[str, JsonObject] = {}


def operator_servers(config: Path) -> list[str]:
    """Return the names of the MCP servers in the operator's Codex configuration, if they have one."""
    if not config.is_file():
        return []
    try:
        read = tomllib.loads(config.read_text())
    except tomllib.TOMLDecodeError as failed:
        message = (
            f"the operator's Codex configuration, {config}, isn't valid TOML: {failed}"
        )
        raise TerminalError(message) from failed
    return list(OperatorConfig.model_validate(read).mcp_servers)


class Override(Model):
    """One `-c` override: a dotted key, and its value."""

    key: str
    value: JsonValue

    def argument(self) -> str:
        """Return the override as `-c` takes it."""
        return f"{self.key}={toml(self.value)}"


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
    model: str,
    system_prompt: str | None,
    effort: Effort | None,
    settings: TerminalSettings,
    layout: CodexLayout,
) -> Terminal:
    """Return the terminal session of Codex for a declaration's fields, with lup's settings."""
    launch = CodexLaunch(directory=settings.directory)
    session = settings.session
    cli = Mount(
        source=layout.bundled if settings.cli is None else settings.cli,
        read_only=True,
    )
    program = layout.bundled_cli if settings.cli is None else settings.cli
    servers = operator_servers(layout.operator_config)

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
    written = requirements.model_dump(mode="json", exclude_none=True)
    lines = [f"{json.dumps(key)} = {toml(value)}\n" for key, value in written.items()]
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
        *(
            []
            if session.auto_memory is None
            else [Override(key="features.memories", value=session.auto_memory)]
        ),
        Override(key="check_for_update_on_startup", value=False),
        Override(key="features.plugins", value=False),
        *(
            [
                Override(
                    key="mcp_servers",
                    value={name: {"enabled": False} for name in servers},
                )
            ]
            if servers
            else []
        ),
        *(
            []
            if settings.guidance is None
            else [Override(key="developer_instructions", value=settings.guidance)]
        ),
        Override(key="project_doc_max_bytes", value=0),
    ]
    return Terminal(
        command=[
            str(program),
            "--no-daemon",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model",
            model,
            *(
                argument
                for override in overrides
                for argument in ["-c", override.argument()]
            ),
        ],
        env={"CODEX_HOME": str(layout.operator_home)},
        files={launch.requirements: "".join(lines)},
        mounts=[
            Mount(source=layout.operator_home),
            cli,
            Mount(
                source=launch.requirements,
                target=MANAGED_REQUIREMENTS,
                read_only=True,
            ),
        ],
    )
