"""Claude Code in a terminal: the command line, settings and state a launched session starts with.

lup's settings reach the session as flags and files of the launch's own, never
written into the operator's directory or the repository (`docs/launch.md`, *The
settings compiled for each runtime*):
- `--settings <launch>/settings.json` with `--setting-sources user`: the operator's
  `~/.claude/settings.json` loads, and the repository's `.claude/settings.json`,
  `.mcp.json`, skills and `CLAUDE.md` don't. lup's file holds the hooks,
  `permissions.deny` (the removed tools, as bare names),
  `disableClaudeAiConnectors` unless the session asks for the account's
  connectors, so none of the claude.ai connectors arriving with the login is
  fetched, and `skipDangerousModePermissionPrompt`;
- `--permission-mode bypassPermissions`: the room is the wall;
- the model with `--model`, the effort with `--effort`, the declaration's system
  prompt with `--system-prompt-file`, and the guidance with
  `--append-system-prompt-file`. `--model` outranks the model the operator's
  settings choose, which `/model` saves there (`model-config`, *Setting your
  model*), so `Claude.chosen` reads their choice (`operator_model`) for a
  declaration that keeps it;
- the variables: auto memory on or off, the subagents' cache lifetime,
  `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` so a held call isn't moved to the
  background after two minutes, `DISABLE_AUTOUPDATER` since the CLI's file is
  read-only, and `CLAUDE_CONFIG_DIR` where the operator set it;
- the room's own state file, onboarding done and the trusted paths accepted,
  mounted read-write where the operator's would be, so concurrent starts can't
  race on theirs; and the operator's directory, mounted read-write at its path,
  for their login, settings and history.

| lup's event | Claude Code's hook events |
|---|---|
| `session-started` | `SessionStart` |
| `call-started` | `PreToolUse` |
| `call-finished` | `PostToolUse`, `PostToolUseFailure` |
| `turn-ended` | `Stop` |
| `conversation-ended` | `SubagentStop` |

What this relies on, from Claude Code's docs (code.claude.com, `cli-reference`,
`permissions`, `env-vars`, `settings`, `settings-reference`, `mcp`, `hooks`) and
its 2.1.294 binary:
- the system prompt flags work interactively; `--system-prompt-file` replaces the
  prompt, `--append-system-prompt-file` appends to it;
- `disableClaudeAiConnectors` turns off "the connectors it fetches itself", set
  "to `true` in any settings scope", with "any-source-true semantics: `true` in
  any settings source takes precedence"; `ENABLE_CLAUDEAI_MCP_SERVERS=false` "has
  the same effect for the current shell session" (`mcp`, *Disable claude.ai
  connectors*). Left out, the operator's own settings decide;
- `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` takes `5m` or `1h`, "the only values
  Claude Code accepts"; `CLAUDE_CODE_DISABLE_AUTO_MEMORY` takes `1` to turn auto
  memory off and `0` to force it on;
- with `CLAUDE_CONFIG_DIR` set, the state file is `.claude.json` inside it;
- a hook's `command` runs in a shell, and its `timeout` is in seconds;
- a single file mounted into the room can't be replaced by a rename ("Device or
  resource busy"), and Claude Code's writer falls back to writing in place
  ("in-place fallback write", in the binary), so the mounted state file stays
  writable.
"""

from datetime import timedelta
from shlex import join
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic.alias_generators import to_camel

from lup.adapters.claude.layout import ClaudeLaunch, ClaudeLayout
from lup.adapters.claude.runtime import AUTO_MEMORY_OFF, Effort
from lup.rooms.container import Mount
from lup.sessions.terminal import Cli, Terminal, TerminalError
from lup.types import Model

if TYPE_CHECKING:
    from pathlib import Path

    from lup.sessions.terminal import Event, Hook, TerminalSettings

SUBAGENT_CACHE = "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL"
"""The variable setting the prompt cache's lifetime outside the main conversation."""

KEEP_CALLS = "CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS"
"""The variable after which a running MCP call moves to the background; `0` never moves it."""

NO_UPDATES = "DISABLE_AUTOUPDATER"
"""The variable turning off the CLI's own updater."""

CONFIG_DIR = "CLAUDE_CONFIG_DIR"
"""The variable moving Claude Code's directory."""


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


class LaunchSettings(Wire):
    """lup's settings for a launched session, the file `--settings` names."""

    hooks: dict[str, list[HookGroup]]
    permissions: Permissions
    disable_claude_ai_connectors: bool | None = None
    """True keeps the account's claude.ai connectors from being fetched; none
    leaves it to the operator's own settings."""
    skip_dangerous_mode_permission_prompt: bool = True


class Trusted(Wire):
    """A folder whose trust question is answered."""

    has_trust_dialog_accepted: bool = True


class State(Wire):
    """The room's own state file: onboarding done, and its folders trusted."""

    has_completed_onboarding: bool = True
    projects: dict[str, Trusted]


class OperatorSettings(Wire):
    """The part of the operator's own Claude Code settings a terminal session keeps."""

    model: str | None = None
    """The model their `/model` saved, or they set; none where they chose none."""


def operator_model(settings: Path) -> str | None:
    """Return the model the operator's own settings file at `settings` chooses; none where it chooses none."""
    if not settings.is_file():
        return None
    try:
        return OperatorSettings.model_validate_json(settings.read_text()).model
    except ValidationError as failed:
        message = (
            f"the operator's Claude Code settings, {settings}, don't read: {failed}"
        )
        raise TerminalError(message) from failed


def spelled(event: Event) -> list[str]:
    """Return Claude Code's hook events for one of lup's."""
    match event:
        case "session-started":
            return ["SessionStart"]
        case "call-started":
            return ["PreToolUse"]
        case "call-finished":
            return ["PostToolUse", "PostToolUseFailure"]
        case "turn-ended":
            return ["Stop"]
        case "conversation-ended":
            return ["SubagentStop"]


def compiled(
    model: str,
    system_prompt: str | None,
    effort: Effort | None,
    settings: TerminalSettings,
    layout: ClaudeLayout,
) -> Terminal:
    """Return the terminal session of Claude Code for a declaration's fields, with lup's settings."""
    launch = ClaudeLaunch(directory=settings.directory)
    cli = Cli(program=layout.bundled) if settings.cli is None else settings.cli
    session = settings.session

    def group(hook: Hook) -> HookGroup:
        timeout = None if hook.timeout is None else int(hook.timeout.total_seconds())
        command = CommandHook(command=join(hook.command), timeout=timeout)
        return HookGroup(matcher=hook.matcher, hooks=[command])

    events = dict.fromkeys(
        name for hook in settings.hooks for name in spelled(hook.event)
    )
    lup_settings = LaunchSettings(
        hooks={
            name: [
                group(hook) for hook in settings.hooks if name in spelled(hook.event)
            ]
            for name in events
        },
        permissions=Permissions(deny=session.removed_tools),
        disable_claude_ai_connectors=None if session.account_connectors else True,
    )
    state = State(
        projects={str(path): Trusted() for path in settings.trusted},
    )
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
    moved = {} if layout.configured is None else {CONFIG_DIR: str(layout.configured)}
    prompt = {} if system_prompt is None else {launch.system_prompt: system_prompt}
    guidance = {} if settings.guidance is None else {launch.guidance: settings.guidance}
    files: dict[Path, str] = {
        launch.settings: lup_settings.model_dump_json(
            by_alias=True, exclude_none=True, indent=2
        ),
        launch.state: state.model_dump_json(by_alias=True, indent=2),
        **prompt,
        **guidance,
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
            "--model",
            model,
            *([] if effort is None else ["--effort", effort]),
            *(
                []
                if system_prompt is None
                else ["--system-prompt-file", str(launch.system_prompt)]
            ),
            *(
                []
                if settings.guidance is None
                else ["--append-system-prompt-file", str(launch.guidance)]
            ),
        ],
        env={KEEP_CALLS: "0", NO_UPDATES: "1", **memory, **cache, **moved},
        files=files,
        mounts=[
            Mount(source=layout.directory),
            cli.mount,
            Mount(source=settings.directory, read_only=True),
            Mount(source=launch.state, target=layout.state),
        ],
    )
