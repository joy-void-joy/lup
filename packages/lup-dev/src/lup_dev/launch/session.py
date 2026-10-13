"""A launch's terminal settings: what lup adds to the session its room opens.

`docs/launch.md`, *The command*. A launch reads the declaration at the commit the
operator approved, as the judge does (`approved_declaration`), so a branch can't
change the room it runs in or the guidance its session reads. From it, and the
worktree launched, come the library's `TerminalSettings` (`terminal_settings`):
- the hooks, each runtime's own (its adapter's `hooks`), every one running the
  room's pipe to the host service (`piped`), and waiting as long as a hold may;
- `Core`'s session settings, in the library's terms: the fields the declaration
  set, imposed over the person's own runtime settings, and the rest as lup's
  defaults, which theirs outrank (`session_settings`);
- the guidance, rendered from lup's sections in the installed package, the
  project's own read at the approved commit, and the person's own,
  `AGENTS.local.md`, from the worktree launched (`launch/guidance.py`);
- the paths trusted: the worktree, and its repository's main worktree, which the
  runtimes ask about for a linked one;
- the launch's own directory, where the compiled files are written.

The hook in the room is one command for every runtime and event: `socat` pipes
the runtime's payload unchanged to the launch's socket, `/run/lup/hook.sock`, and
prints the answer, so nothing in the room parses a payload. Where it can't reach
the host service, the command ends with status 1 and says why on standard error:
an error each runtime shows, the call going on, rather than the silence a
runtime reads as no decision. Status 2 would block the call on both runtimes, so
the command never ends with it (each adapter says what its runtime does).
"""

import shlex
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lup.sessions.terminal import Cli, Hook, SessionSettings, TerminalSettings
from lup.types import Model
from lup_dev.declaration.load import load, read_by_import
from lup_dev.declaration.resolve import Resolved, SessionChoices, resolve
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.launch.guidance import render
from lup_dev.launch.room import repository
from lup_dev.layout import ROOM_SOCKETS, LaunchSockets

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class LaunchError(LupDevError):
    """A launch that can't go on as it was asked."""


class Approved(Model):
    """The declaration at the commit the operator approved, resolved, with the files it was read from."""

    commit: str
    resolved: Resolved
    root: Path
    """A scratch directory holding the commit's files the declaration and the
    project's own guidance read, for the length of the launch."""


@contextmanager
def approved_declaration(worktree: Path, commit: str) -> Generator[Approved]:
    """Read the declaration at `commit` in the repository of `worktree`, and resolve it.

    The commit's Python modules and project files are exported from git's
    objects into a scratch directory and the declaration imported there, as the
    judge reads it; then the files of the project's own guidance sections. The
    directory is removed when the context ends. Raise `ProjectError` where the
    declaration doesn't load or resolve.
    """
    git = Git(cwd=worktree)
    with tempfile.TemporaryDirectory(prefix="lup-launch-") as scratch:
        root = Path(scratch)
        git.export(commit, root, read_by_import)
        resolved = resolve(load(root).project)
        own = [
            PurePosixPath(section.path)
            for section in resolved.guidance
            if section.package is None
        ]

        def guidance(path: PurePosixPath) -> bool:
            return path in own

        git.export(commit, root, guidance)
        yield Approved(commit=commit, resolved=resolved, root=root)


def piped(timeout: timedelta = timedelta(hours=25)) -> list[str]:
    """Return the command a room's hook runs: the payload piped to the host service, its answer printed.

    `socat`'s `-t` is how long it waits for the answer once the payload is sent:
    `timeout`, above a hold's day. A failure, to reach the service or any other,
    ends the command with status 1 and a line on standard error.
    """
    socket = LaunchSockets(directory=ROOM_SOCKETS).hook
    seconds = str(int(timeout.total_seconds()))
    pipe = shlex.join(["socat", "-t", seconds, "-", f"UNIX-CONNECT:{socket}"])
    said = shlex.quote(
        f"lup: this hook couldn't reach lup's host service on {socket}, so it "
        "wasn't judged. On the host, `lup-dev host` serves this session again."
    )
    return ["sh", "-c", f"{pipe} || {{ echo {said} >&2; exit 1; }}"]


def hooked(
    spelled: Callable[[list[str], timedelta], list[Hook]],
    hold: timedelta = timedelta(hours=25),
) -> list[Hook]:
    """Return a runtime's hooks, as its adapter spells them (`spelled`), each running the room's pipe.

    The hook waits for its answer as long as the pipe does: `hold`, above a hold's
    day.
    """
    return spelled(piped(hold), hold)


class SessionParts(Model):
    """`Core`'s session settings in the library's terms, split by who chose each."""

    declared: SessionSettings
    """The fields the declaration set, imposed over the person's own runtime settings."""
    defaults: SessionSettings
    """The rest, lup's defaults, which the person's own runtime settings outrank."""


def session_settings(choices: SessionChoices) -> SessionParts:
    """Return `Core`'s session settings, as the declaration resolves them, in the library's terms.

    Each field is the library's of the same name, so the fields a layer set go
    in `declared`, and the rest in `defaults`.
    """
    match choices.subagent_cache:
        case "5m":
            cache = timedelta(minutes=5)
        case "1h":
            cache = timedelta(hours=1)
    every = SessionSettings(
        subagent_cache=cache,
        auto_memory=choices.auto_memory,
        idle_compaction=choices.idle_compaction,
        removed_tools=choices.removed_tools,
        account_connectors=choices.account_connectors,
    ).model_dump()
    return SessionParts(
        declared=SessionSettings.model_validate(
            {field: every[field] for field in choices.declared}
        ),
        defaults=SessionSettings.model_validate(
            {
                field: value
                for field, value in every.items()
                if field not in choices.declared
            }
        ),
    )


def trusted(worktree: Path) -> list[Path]:
    """Return the paths a launch in `worktree` trusts: the worktree, and its repository's main worktree."""
    return list(dict.fromkeys([worktree, repository(worktree).main]))


def terminal_settings(
    approved: Approved, worktree: Path, directory: Path, cli: Cli, hooks: list[Hook]
) -> TerminalSettings:
    """Return what lup adds to the session launched in `worktree`, its files compiled into `directory`.

    Raise `GuidanceError` naming a section of guidance that can't be read, or
    doesn't render.
    """
    resolved = approved.resolved
    session = session_settings(resolved.session)
    return TerminalSettings(
        directory=directory,
        cli=cli,
        hooks=hooks,
        guidance=render(resolved, approved.root, worktree),
        session=session.declared,
        defaults=session.defaults,
        trusted=trusted(worktree),
    )
