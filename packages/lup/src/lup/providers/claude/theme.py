"""The themes Claude Code draws its interface in, and whose theme an account keeps.

Claude Code ships its colorblind palette itself, so this side needs no theme
built — only the vocabulary a person's configuration is checked against, and
the one place a launch touches an account's theme: filling one in where the
account has none, or putting the one the person's lup config names in place.
Everything else about the theme is the account's, which is why a launch hands
it through the account's own files rather than as a launch-wide override: an
override would outrank a session's ``/theme`` for as long as the session ran,
and a theme chosen in a session belongs to the account it was chosen in.
"""

from typing import Annotated, Literal

from pydantic import StringConstraints

from lup.providers.claude.config_home import (
    WORKSPACE_SETTINGS,
    ClaudeConfigHome,
    load_document,
    save_document,
)

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


def settle_claude_theme(
    home: ClaudeConfigHome,
    named: ClaudeTheme | None,
    fallback: ClaudeTheme = "dark-daltonized",
) -> ClaudeTheme | None:
    """Have an account draw the theme it should, writing only what it lacks.

    Claude Code reads an account's theme from its settings ahead of its
    configuration document, so the theme is held by whichever of the two
    names one, and written there. ``named`` is the person's lup config naming
    one outright, which wins over the account's; unnamed, an account keeping
    a theme is left as it is, and one keeping none is given ``fallback``,
    lup's own. Answers the theme written, or ``None`` where nothing was.
    """
    settings_path = home.directory / WORKSPACE_SETTINGS
    settings = load_document(settings_path)
    holder, held = (
        (settings_path, settings)
        if "theme" in settings
        else (home.document, load_document(home.document))
    )
    if named is None and "theme" in held:
        return None
    wanted = named or fallback
    if "theme" in held and held["theme"] == wanted:
        return None
    save_document(holder, {**held, "theme": wanted})
    return wanted
