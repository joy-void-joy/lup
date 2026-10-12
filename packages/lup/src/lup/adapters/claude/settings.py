"""The environment variables Claude Code's adapter reads, as one settings model.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables the adapter reads. Where each
points by default is `layout.py`'s.
"""

from pathlib import Path

from lup.types import Settings


class ClaudeSettings(Settings):
    """The environment variables Claude Code's adapter reads, one field per variable."""

    claude_config_dir: Path | None = None
    """`CLAUDE_CONFIG_DIR`, where the operator keeps Claude Code's directory, if not `~/.claude`."""
