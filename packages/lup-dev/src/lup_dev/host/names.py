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
- **A launch's container** is named after its repository and its name
  (`container_name`), so `podman ps` says which session each runs, and renamed
  with it. A name whose container another launch's holds is held too: `lup`'s
  `dashboard-dev` and `lup-dashboard`'s `dev` would name one container.
- **A session's name** is kept by the runtime's id for them each time their
  launch is named or renamed, in lup's state (`SessionNames`), so a later launch
  resuming them takes the name back where it's free.
- **A session's title in their runtime, as lup last left it,** is kept beside
  their name: the one lup gave them, once the answer giving it was written, else
  the one lup found there. A title the runtime reports other than that one is the
  operator's, which becomes the session's name; that one is lup's own, which
  the session's name outranks: a resume carries the title lup gave at an
  earlier start, and an answer that never reached its hook leaves the runtime
  with the title found before.
"""

import string
from itertools import count, groupby
from pathlib import Path

from lup.types import Model
from lup_dev.host.protocol import HostError, Name, Register, handle
from lup_dev.stored import read_model, write_model

CONTAINED = string.ascii_letters + string.digits + "_."
"""The characters a container's name holds beside `-` and its first, as podman allows them."""


class SessionNames(Model):
    """The name each session's launch last had, and their title in their runtime as lup last left it, each by the runtime's id for the session."""

    names: dict[str, Name] = {}
    titles: dict[str, str] = {}


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


def container_name(repository: Path, name: str) -> str:
    """Return the name of the container of a launch named `name`, of the repository whose git directory is `repository`: `lup-<repository>-<name>`.

    The repository is named by its directory, as the dashboard names it: a
    bare one by its own (`lup.git` is `lup`), a clone by the one holding its
    `.git`. Each run of `-` and of characters a container's name can't hold is
    one `-`.

    >>> container_name(Path("/src/lup.git"), "dev")
    'lup-lup-dev'
    >>> container_name(Path("/src/my atlas/.git"), "feat-x")
    'lup-my-atlas-feat-x'
    """
    directory = repository.parent if repository.name == ".git" else repository
    wanted = f"lup-{directory.name.removesuffix('.git')}-{name}"
    runs = groupby(wanted, key=lambda each: each in CONTAINED)
    return "-".join("".join(chars) for kept, chars in runs if kept)


def held(name: str, launches: list[Register], asking: Register) -> Register | None:
    """Return the launch among `launches`, other than `asking`, that holds `name`, or the container `asking` would take by it (`container_name`); none where neither is held."""
    container = container_name(asking.repository, name)
    return next(
        (
            each
            for each in launches
            if each.launch != asking.launch
            and (each.name == name or each.container == container)
        ),
        None,
    )


def taken(holder: Register, name: str) -> str:
    """Say which launch holds `name`, or the container it would give, for a refusal."""
    whose = f"launch {holder.launch}'s, {holder.runtime} in {holder.worktree}"
    if holder.name == name:
        return f"`{name}` is {whose}: pick another name"
    return (
        f"`{name}` would name its container `{holder.container}`, which is "
        f"{whose} (`{holder.name}`): pick another name"
    )


def claimed(request: Register, launches: list[Register]) -> str:
    """Return the name `request` takes among `launches`: as asked where it's exact, else the first of it, `-2`, `-3`… that's free.

    A record from before launches had names asks its worktree's. Raise
    `HostError` where an exact name is held.
    """
    asked = request.name or request.worktree.name
    holder = held(asked, launches, request)
    if holder is None:
        return asked
    if request.exact:
        raise HostError(taken(holder, asked))
    candidates = (f"{asked}-{number}" for number in count(2))
    return next(each for each in candidates if held(each, launches, request) is None)


class Names(Model):
    """The names sessions last had, and their titles in their runtime as lup last left them, kept in a file of lup's state."""

    path: Path

    def last(self, session: str) -> str | None:
        """Return the name `session`'s launch last had, or none where they were never heard."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        return kept.names.get(session)

    def keep(self, session: str, name: str) -> None:
        """Keep `name` as `session`'s; the file is left as it is where it was already."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        if kept.names.get(session) == name:
            return
        write_model(
            self.path, kept.model_copy(update={"names": {**kept.names, session: name}})
        )

    def title(self, session: str) -> str | None:
        """Return `session`'s title in their runtime as lup last left it; none where lup never gave or found one."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        return kept.titles.get(session)

    def titled(self, session: str, title: str) -> None:
        """Keep `title` as `session`'s title in their runtime as lup leaves it; the file is left as it is where it was already."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        if kept.titles.get(session) == title:
            return
        write_model(
            self.path,
            kept.model_copy(update={"titles": {**kept.titles, session: title}}),
        )

    def all(self) -> dict[str, str]:
        """Return every session's last name, by the runtime's id for them."""
        kept = read_model(self.path, SessionNames) or SessionNames()
        return kept.names
