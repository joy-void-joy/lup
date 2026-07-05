"""Claude account profiles: config dirs selected via ``CLAUDE_CONFIG_DIR``.

The Claude runner reads its whole home — login/credentials, settings,
history, plugin registry — from ``CLAUDE_CONFIG_DIR``, defaulting to
``~/.claude``. This module supplies those two facts to the neutral
profile registry; it imports no SDK.
"""

from pathlib import Path

from lup.adapters.profiles.Profiles import ProfileSupport

DEFAULT_CONFIG_DIR = Path.home() / ".claude"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


class ClaudeProfileSupport(ProfileSupport):
    """Profile support for the Claude runner.

    The runner points at a resolved dir by setting ``CONFIG_DIR_ENV`` in
    its environment.
    """

    @property
    def default_config_dir(self) -> Path:
        return DEFAULT_CONFIG_DIR
