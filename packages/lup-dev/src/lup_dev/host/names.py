"""The launches' names: unique among those served, changeable while they run, and taken back by a session resumed.

A launch is filed under its id, which never changes: its sockets, its record, its
inbox items' whereabouts. Its name is for people and commands to call it by, and
is looked up each time it's used, so renaming it moves nothing (`docs/launch.md`,
*Names*). The first lup's sessions met each other's stale sockets because names
were keys there.
- **At registration** a launch takes the name it asks for: `--name` exactly, or
  refused where another holds it; otherwise its worktree's branch, `-2`, `-3`
  added until it's free (`claimed`).
- **A rename** is refused where another launch holds the name, saying which
  (`held`).
- **A session's name** is kept by the runtime's id for it each time its launch
  is named or renamed, in lup's state (`SessionNames`), so a later launch
  resuming it takes the name back where it's free.
"""

from itertools import count, groupby
from pathlib import Path

from lup.types import Model
from lup_dev.host.protocol import HostError, Name, Register, handle
from lup_dev.stored import read_model, write_model


class SessionNames(Model):
    """The name each session's launch last had, by the runtime's id for the session."""

    names: dict[str, Name] = {}


def shaped(title: str) -> str | None:
    """Return a runtime's title for a session as a launch's name: lowercase, each run of what a name can't hold a `-`; none where nothing's left, or it's too long.

    >>> shaped("Naming Review")
    'naming-review'
    >>> shaped("gate-on-push")
    'gate-on-push'
    >>> shaped("!!") is None
    True
    """
    runs = groupby(title.lower(), key=lambda each: each.isalnum() or each in "_.")
    name = "-".join("".join(chars) for kept, chars in runs if kept)
    try:
        return handle(name)
    except ValueError:
        return None


def held(name: str, launches: list[Register], asking: str) -> Register | None:
    """Return the launch other than `asking` that holds `name` among `launches`, or none."""
    return next(
        (each for each in launches if each.name == name and each.launch != asking),
        None,
    )


def taken(holder: Register) -> str:
    """Say which launch holds a name, for a refusal."""
    return (
        f"`{holder.name}` is launch {holder.launch}'s, {holder.runtime} in "
        f"{holder.worktree}: pick another name"
    )


def claimed(request: Register, launches: list[Register]) -> str:
    """Return the name `request` takes among `launches`: as asked where it's exact, else the first of it, `-2`, `-3`… that's free.

    A record from before launches had names asks its worktree's. Raise
    `HostError` where an exact name is held.
    """
    asked = request.name or request.worktree.name
    holder = held(asked, launches, request.launch)
    if holder is None:
        return asked
    if request.exact:
        raise HostError(taken(holder))
    candidates = (f"{asked}-{number}" for number in count(2))
    return next(
        each for each in candidates if held(each, launches, request.launch) is None
    )


class Names(Model):
    """The names sessions last had, kept in a file of lup's state."""

    path: Path

    def last(self, session: str) -> str | None:
        """Return the name `session`'s launch last had, or none where it was never heard."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        return kept.names.get(session)

    def keep(self, session: str, name: str) -> None:
        """Keep `name` as `session`'s."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        write_model(
            self.path, kept.model_copy(update={"names": {**kept.names, session: name}})
        )

    def all(self) -> dict[str, str]:
        """Return every session's last name, by the runtime's id for it."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        return kept.names
