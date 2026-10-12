"""Where Claude Code keeps what a terminal session reads, and where a launch writes its own.

The operator's directory, `~/.claude` (or `CLAUDE_CONFIG_DIR`), holds their login,
settings and history; their state file, `~/.claude.json` (or `.claude.json` inside
`CLAUDE_CONFIG_DIR`), holds onboarding and folder trust. A launched session uses
the directory as it is, and a state file of the launch's own in place of theirs.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from lup.sessions.errors import RuntimeMissingError
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
    def system_prompt(self) -> Path:
        """The declaration's system prompt, which replaces Claude Code's own."""
        return self.directory / "system-prompt.md"

    @property
    def guidance(self) -> Path:
        """The guidance, appended to Claude Code's system prompt."""
        return self.directory / "guidance.md"
