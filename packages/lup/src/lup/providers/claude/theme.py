"""The themes Claude Code draws its interface in, in its own words.

A leaf beside :mod:`lup.providers.codex.theme`, which builds the theme Codex
lacks. Claude Code ships its colorblind palette itself, so all this side needs
is the vocabulary a person's configuration is checked against before a launch
hands it on.
"""

from typing import Annotated, Literal

from pydantic import StringConstraints

type ClaudeBuiltinTheme = Literal[
    "auto",
    "dark",
    "light",
    "dark-daltonized",
    "light-daltonized",
    "dark-ansi",
    "light-ansi",
]
"""A theme Claude Code ships, as its settings schema lists them (read from 2.1.282)."""

type ClaudeTheme = (
    ClaudeBuiltinTheme | Annotated[str, StringConstraints(pattern=r"^custom:.+$")]
)
"""A theme Claude Code's ``theme`` setting takes: a shipped one, or ``custom:<name>``."""
