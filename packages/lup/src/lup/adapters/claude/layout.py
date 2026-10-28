"""Where Claude Code keeps what a terminal session reads, and where a launch writes its own.

The operator's directory, `~/.claude` (or `CLAUDE_CONFIG_DIR`), holds their login,
settings and history; their state file, `~/.claude.json` (or `.claude.json` inside
`CLAUDE_CONFIG_DIR`), holds onboarding and folder trust. A launched session uses
neither: it runs on a home of the rooms' own (`ClaudeHome`), its configuration
copied from theirs, and a state file of the launch's own.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from lup.sessions.configuration import HomeLaunch, Item
from lup.sessions.errors import RuntimeMissingError
from lup.sessions.terminal import Preference
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
    """What Claude Code keeps in its directory, as a home of the rooms' own lays it out (`lup.sessions.terminal.RuntimeHome`).

    Read in the `claude-directory` docs (2026-10-27) and Claude Code's 2.1.311
    binary; what isn't named here is history and state, which every room given
    the home shares.
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
        Item(name="agent-memory"),
        Item(name="plugins", leaving=["data"]),
        Item(name="keybindings.json", directory=False),
        Item(name="themes"),
    ]
    """Each item of configuration, read-only in the home: the launch's copy of
    the layers holding it, or empty. Plugins' `data/` is theirs, not
    configuration, and may hold their tokens."""
    own: list[str] = ["shell-snapshots", "session-env"]
    """What each launch's session writes for itself alone: a Bash command runs
    its session's snapshot from `shell-snapshots/` first, so a room writing
    another's would run in it (the 2.1.311 binary)."""
    blocked: list[str] = [
        "env",
        "apiKeyHelper",
        "awsAuthRefresh",
        "awsCredentialExport",
        "otelHeadersHelper",
    ]
    """Settings left out of the copy, beside any named like a credential: the
    variables Claude Code sets at start, and the commands it runs to fetch a
    credential."""
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
        """Where Claude Code reads its user settings and saves its preferences: the launch's own, mounted there."""
        return self.directory / "settings.json"

    @property
    def state(self) -> Path:
        """Where Claude Code keeps its state file with its directory moved: the launch's own, mounted there."""
        return self.directory / ".claude.json"

    @property
    def credentials(self) -> Path:
        """Where Claude Code reads its login: the account's file, mounted there."""
        return self.directory / ".credentials.json"


class ClaudeLaunch(Model):
    """The files a launch writes for Claude Code, in its own directory."""

    directory: Path

    @property
    def home(self) -> HomeLaunch:
        """What the launch keeps of its own for Claude Code's home of the rooms' own: its copies, its empties, and what the session writes for itself."""
        return HomeLaunch(directory=self.directory / "runtime")

    @property
    def home_settings(self) -> Path:
        """The settings the session reads as its user settings and saves its preferences in, the operator's and the profile's layered: the launch's own, writable."""
        return self.home.own("settings.json")

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
