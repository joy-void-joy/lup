"""Where Claude Code keeps what a terminal session reads, and where a launch writes its own.

The operator's directory, `~/.claude` (or `CLAUDE_CONFIG_DIR`), holds their login,
settings and history; their state file, `~/.claude.json` (or `.claude.json` inside
`CLAUDE_CONFIG_DIR`), holds onboarding and folder trust. A launched session uses
neither: it runs in a directory of the launch's own on a home of the rooms'
own (`ClaudeHome`), its configuration copied from theirs.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from lup.sessions.configuration import Item
from lup.sessions.errors import RuntimeMissingError
from lup.sessions.terminal import Preference, Why
from lup.types import Model

if TYPE_CHECKING:
    from lup.adapters.claude.settings import ClaudeSettings


class ClaudeLayout(Model):
    """The operator's Claude Code directory and state file, and the CLI the SDK bundles."""

    home: Path
    """The operator's home."""
    configured: Path | None = None
    """Where `CLAUDE_CONFIG_DIR` moves Claude Code's directory; none for the default."""

    @classmethod
    def of(cls, settings: ClaudeSettings) -> ClaudeLayout:
        """Place the operator's directory where the settings say, or at its default."""
        configured = settings.claude_config_dir
        return cls(
            home=Path.home(),
            configured=None if configured is None else configured.absolute(),
        )

    @property
    def directory(self) -> Path:
        """The operator's Claude Code directory: their login, settings and history."""
        return self.home / ".claude" if self.configured is None else self.configured

    @property
    def settings(self) -> Path:
        """The operator's own settings: the model their `/model` saved, the theme, and the like."""
        return self.directory / "settings.json"

    @property
    def credentials(self) -> Path:
        """The login, as Claude Code's sign-in keeps it in a file in the directory."""
        return self.directory / ".credentials.json"

    @property
    def state(self) -> Path:
        """The operator's state file: onboarding, folder trust, and the like."""
        return (
            self.home if self.configured is None else self.configured
        ) / ".claude.json"

    @property
    def bundled(self) -> Path:
        """The Claude Code CLI the Agent SDK bundles, where `claude_agent_sdk` keeps it."""
        found = find_spec("claude_agent_sdk")
        origin = None if found is None else found.origin
        cli = None if origin is None else Path(origin).parent / "_bundled" / "claude"
        if cli is None or not cli.is_file():
            message = (
                "the Claude Code CLI the Agent SDK bundles isn't there: reinstall the "
                "`lup[claude]` extra, or give the CLI's path"
            )
            raise RuntimeMissingError(message)
        return cli


class ClaudeHome(Model):
    """What Claude Code keeps in its directory, as a launch lays it out on a home of the rooms' own (`lup.sessions.terminal.RuntimeHome`).

    The directory is the launch's own: every file Claude Code reads there as
    configuration or state is the launch's, `.config.json` among them, which
    the 2.1.311 binary prefers over `.claude.json` and whose `env` it applies.
    Only `shared` is linked into the home the rooms share. Read in the
    `claude-directory` docs (2026-10-27) and the 2.1.311 binary.
    """

    directory: Path
    configuration: list[Item] = [
        Item(name="CLAUDE.md", directory=False),
        Item(name="rules"),
        Item(name="skills"),
        Item(name="commands"),
        Item(name="agents"),
        Item(name="output-styles"),
        Item(name="workflows"),
        Item(name="plugins", leaving=["data"]),
        Item(name="keybindings.json", directory=False),
        Item(name="themes"),
    ]
    """Each item of configuration copied in from the layers. Plugins' `data/`
    is theirs, not configuration, and may hold their tokens; `agent-memory/`
    is left out, since the operator's subagents' memories hold what they
    learnt in every project."""
    shared: list[Item] = [
        Item(name="projects"),
        Item(name="file-history"),
        Item(name="tasks"),
        Item(name="todos"),
        Item(name="plans"),
        Item(name="paste-cache"),
        Item(name="history.jsonl", directory=False),
    ]
    """The history the rooms given the home share: the conversations' records,
    what `/rewind` restores, task lists and plans, and the prompts typed, which
    a resumed conversation reads. Auto memory, which Claude Code keeps beside
    the records by default, is the launch's own (`memory`)."""
    blocked: dict[str, Why] = {
        "env": "credential",
        "apiKeyHelper": "command",
        "awsAuthRefresh": "command",
        "awsCredentialExport": "command",
        "otelHeadersHelper": "command",
        "hooks": "command",
        "statusLine": "command",
    }
    """Settings left out of the copy, beside any named like a credential and
    any table holding a `command`: the variables Claude Code sets at start;
    the commands it runs to fetch a credential; and the operator's hooks and
    status line, commands set up for the host, where rooms run lup's own."""
    preferences: list[Preference] = [
        Preference(keys=["model"]),
        Preference(keys=["effortLevel"]),
        Preference(keys=["modelSettings"]),
        Preference(keys=["outputStyle"]),
        Preference(keys=["theme"]),
        Preference(keys=["editorMode"]),
        Preference(keys=["alwaysThinkingEnabled"]),
    ]
    """What a session saves in its settings that a launch carries back:
    `/model`, `/effort`, `/output-style`, `/theme` and the like."""

    @property
    def settings(self) -> Path:
        """Where Claude Code reads its user settings and saves its preferences."""
        return self.directory / "settings.json"

    @property
    def state(self) -> Path:
        """Where Claude Code keeps its state file with its directory moved."""
        return self.directory / ".claude.json"

    @property
    def credentials(self) -> Path:
        """Where Claude Code reads its login: the account's file, mounted there."""
        return self.directory / ".credentials.json"

    @property
    def memory(self) -> Path:
        """Where Claude Code keeps its auto memory, as the launch's settings place it (`autoMemoryDirectory`): in the launch's own directory, gone with it.

        By default it's `projects/<folder>/memory/`, inside the history the
        rooms share, and where auto memory is on Claude Code loads its
        `MEMORY.md` into every new session of the project: one room's notes
        there would steer every later room unseen, on any profile and
        account, where history is read only when a conversation is resumed.
        """
        return self.directory / "memory"


class ClaudeLaunch(Model):
    """The files a launch writes for Claude Code, in its own directory."""

    directory: Path

    @property
    def settings(self) -> Path:
        """The settings lup adds to the session, passed with `--settings`."""
        return self.directory / "settings.json"

    @property
    def state(self) -> Path:
        """The room's own state file, mounted where the operator's would be."""
        return self.directory / "claude.json"

    @property
    def servers(self) -> Path:
        """The MCP servers lup gives the session, passed with `--mcp-config`."""
        return self.directory / "mcp.json"

    @property
    def system_prompt(self) -> Path:
        """The declaration's system prompt, which replaces Claude Code's own."""
        return self.directory / "system-prompt.md"

    @property
    def guidance(self) -> Path:
        """The guidance, appended to Claude Code's system prompt."""
        return self.directory / "guidance.md"
