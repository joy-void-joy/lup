"""The runtimes lup knows how to hold sessions on, by their names: what `Core` offers a project, and what the machine holds a session on."""

from lup.runtimes.claude import ClaudeCode
from lup.runtimes.codex import Codex
lazy from lup.runtimes.runtime import Runtime


def known() -> list[Runtime]:
    """Return every runtime lup holds sessions on, Claude Code first."""
    return [ClaudeCode(), Codex()]


def named(name: str) -> Runtime:
    """Return the runtime lup names `name`.

    Raise `ValueError` where lup knows none by that name.

    >>> named("codex").name
    'codex'
    """
    found = next((each for each in known() if each.name == name), None)
    if found is None:
        names = ", ".join(each.name for each in known())
        message = f"lup holds no runtime named `{name}`: it knows {names}"
        raise ValueError(message)
    return found
