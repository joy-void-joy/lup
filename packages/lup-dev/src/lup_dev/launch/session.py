"""A launch's terminal settings: what lup adds to the session its room opens.

`docs/launch.md`, *The command*. A launch reads the declaration at the commit the
operator approved, with the person's own layer approved beside it, as the judge
does (`approved_declaration`), so neither a branch nor an edit made in a room can
change the room a launch runs in or the guidance its session reads. From it, and the
worktree launched, come the library's `TerminalSettings` (`terminal_settings`):
- the hooks, each runtime's own (its adapter's `hooks`), every one running the
  room's pipe to the host service (`piped`), and waiting as long as a hold may;
- lup's tool server, on the launch's `mcp.sock` in the room, which the host
  service serves (`served`; `docs/host-tools.md`, *The server*), a call to it
  waiting as long as a hold may;
- the session's own messaging socket, put in the launch's socket directory, so
  the host service reaches it to start a turn of the idle session where its
  runtime has one (`docs/host-tools.md`, *How an agent is told*);
- `Core`'s session settings, in the library's terms: the fields the declaration
  set, imposed over the person's own runtime settings, and the rest as lup's
  defaults, which theirs outrank (`session_settings`);
- the guidance, rendered from lup's sections in the installed package, the
  project's own read at the approved commit, and the person's own,
  `AGENTS.local.md`, from the worktree launched, with lup's tools and the other
  repositories named for its sessions listed (`launch/guidance.py`);
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

from lup.sessions.terminal import (
    Cli,
    Hook,
    SessionSettings,
    TerminalSettings,
    ToolServer,
)
from lup.types import Model
from lup_dev.declaration.load import load, read_by_import
from lup_dev.declaration.resolve import Resolved, SessionChoices, resolve
from lup_dev.errors import LupDevError
from lup_dev.git import Git
from lup_dev.host.rooms import SERVER
from lup_dev.launch.guidance import render
from lup_dev.launch.room import repository
from lup_dev.layout import ROOM_SOCKETS, CheckoutLayout, LaunchSockets

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from lup.tools.tool import ToolSpec
    from lup_dev.launch.room import Lent, RelatedRepository


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
def approved_declaration(
    worktree: Path, commit: str, *, local: str | None
) -> Generator[Approved]:
    """Read the declaration at `commit` in the repository of `worktree`, with `local` on top, and resolve it.

    The commit's Python modules and project files are exported from git's
    objects into a scratch directory, `local`, the person's own layer approved
    with it, written beside them where there's one, and the declaration
    imported there, as the judge reads it; then the files of the project's own
    guidance sections. The directory is removed when the context ends. Raise
    `ProjectError` where the declaration doesn't load or resolve.
    """
    git = Git(cwd=worktree)
    with tempfile.TemporaryDirectory(prefix="lup-launch-") as scratch:
        root = Path(scratch)
        git.export(commit, root, read_by_import)
        if local is not None:
            CheckoutLayout(root=root).local_declaration.write_text(local)
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


def served(hold: timedelta = timedelta(hours=25)) -> list[ToolServer]:
    """Return the tool servers a launched session loads: lup's, on the launch's `mcp.sock` in the room.

    A call to it may wait for the operator, so the runtime waits on one as long as
    the hook does: `hold`, above a hold's day.
    """
    socket = LaunchSockets(directory=ROOM_SOCKETS).mcp
    return [ToolServer(name=SERVER, socket=socket, timeout=hold)]


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
    approved: Approved,
    worktree: Path,
    directory: Path,
    cli: Cli,
    hooks: list[Hook],
    *,
    tools: list[ToolSpec],
    neighbours: list[RelatedRepository],
    shared: dict[str, Path],
    lent: list[Lent] | None = None,
) -> TerminalSettings:
    """Return what lup adds to the session launched in `worktree`, its files compiled into `directory`.

    `tools` are lup's tools the host service serves it, `neighbours` the other
    repositories named for it, as the launch found them, and `lent` the
    directories lent to this launch, which its guidance lists, and `shared`
    where each module whose data the room mounts has it. Raise `GuidanceError`
    naming a section of guidance that can't be read, or doesn't render.
    """
    resolved = approved.resolved
    session = session_settings(resolved.session)
    return TerminalSettings(
        directory=directory,
        cli=cli,
        hooks=hooks,
        servers=served(),
        messages=LaunchSockets(directory=ROOM_SOCKETS).messages,
        guidance=render(
            resolved,
            approved.root,
            worktree,
            tools,
            neighbours,
            shared=shared,
            lent=lent,
        ),
        session=session.declared,
        defaults=session.defaults,
        trusted=trusted(worktree),
    )
