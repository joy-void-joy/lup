"""A launch's terminal settings: what lup adds to the session its room opens.

`docs/launch.md`, *The command*. A launch reads the declaration at the commit the
operator approved, with the person's own layer approved beside it, as the judge
does (`approved_declaration`), so neither a branch nor an edit made in a room can
change the room a launch runs in or the guidance its session reads. From it, and the
worktree launched, come the library's `TerminalSettings` (`terminal_settings`):
- the hooks, each runtime's own (its adapter's `hooks`), every one running the
  room's pipe to the host service (`piped`), and waiting as long as a hold may;
- lup's tool server, on the launch's `mcp.sock` in the room, which the host
  service serves (`served`; `docs/host.md`, *How a room reaches it*), a call to it
  waiting as long as a hold may;
- the session's own messaging socket, put in the launch's socket directory, so
  the host service reaches it to start a turn of the idle session where its
  runtime has one (`docs/inbox.md`, *How an agent is told*);
- `Core`'s session settings, in the library's terms: the fields the declaration
  set, imposed over the person's own runtime settings, and the rest as lup's
  defaults, which theirs outrank (`session_settings`);
- the guidance, rendered from lup's sections in the installed package, the
  project's own read at the approved commit, and the person's own,
  `AGENTS.local.md`, from the worktree launched, with lup's tools and the other
  repositories named for its sessions listed, and lup's code rules the
  declaration runs for a section to list (`launch/guidance.py`);
- the paths trusted: the worktree, and its repository's main worktree, which the
  runtimes ask about for a linked one;
- the launch's own directory, where the compiled files are written.

The hook in the room is one command for every runtime, and one for each event:
`socat` pipes the runtime's payload unchanged to the launch's socket,
`/run/lup/hook.sock`, and prints the answer, so nothing in the room parses a
payload. Where it can't reach the host service, having waited a minute for it as
across a restart (`piped`), the command ends with status 1 and says why on
standard error: an error each runtime shows, the call going on, rather than the
silence a runtime reads as no decision. Where it reached the service and the
connection ended before an answer, it fails as its event needs (`lost`): status
2, which on both runtimes blocks the call, tells the agent beside its result or
holds a turn's end, and 1 at a session's or a turn's start (each adapter says
what its runtime does).

At a worktree asked for, the answer is the worktree the judge names, which the
room's hook makes with the room's own git and names to the runtime, or why the
judge makes none, which fails the making; at a call's start, a worktree the
answer names first is made the same way before the rest is printed
(`worktree.sh`, `printing`).
"""

import io
import shlex
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionEvent,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    WorktreeAsked,
)
from lup.sessions.bridge import Bridge
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
from lup_dev.layout import CheckoutLayout, LaunchSockets, RoomPaths

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from lup.tools.tool import ToolSpec
    from lup_dev.codescan.contract import Rule
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


class Lost(Model):
    """What a room's hook does where its connection to the host service is lost before an answer: the status it ends with, and the line it says."""

    status: int
    said: str


def lost(event: type[SessionEvent]) -> Lost:
    """Return what the room's hook at `event` does where the host service goes away after the payload is sent, before it answers.

    Status 2, at a call's start, its finish and a conversation's turn's end, does
    on both runtimes what keeps a write from landing unreviewed and tells the
    agent the line: it blocks the call, or tells the agent beside the call's
    result, or holds the turn's end once (`docs/host.md`, *The one hook*). At a
    session's start or a turn's start, status 2 would drop the operator's
    prompt, and no write is judged there, so the hook ends with status 1, an
    error each runtime shows the operator. At a worktree asked for, any status
    but 0 fails the making, so it's 1 too.
    """
    gone = (
        "lup: the host service went away before it answered this hook, as it does "
        "when it restarts,"
    )
    held = (
        "A write lup held for the operator's review stays held, and their answer "
        "reaches you at a later call."
    )
    dropped = Lost(status=1, said=f"{gone} so its answer was lost.")
    unjudged = Lost(
        status=2,
        said=f"{gone} so what was written is judged at your next call. {held}",
    )
    losses: dict[type[SessionEvent], Lost] = {
        SessionStarted: dropped,
        TurnStarted: dropped,
        CallStarted: Lost(
            status=2, said=f"{gone} so this call didn't run: make it again. {held}"
        ),
        WorktreeAsked: dropped,
        CallFinished: unjudged,
        TurnEnded: unjudged,
        ConversationEnded: unjudged,
    }
    return losses[event]


def piped(
    event: type[SessionEvent], timeout: timedelta = timedelta(hours=25)
) -> list[str]:
    """Return the command a room's hook at `event` runs: the payload piped to the host service, its answer printed.

    Where the service is away, as while it restarts, `socat` waits for it as
    lup's bridge waits for the tool server, read from a bridge built with its
    defaults and never run (`Bridge`'s `retry` and `patience`): it tries again
    to connect every half second, for up to a minute. It reads the payload only
    once connected, and never connects again, so no payload is sent twice: a
    connection lost once made isn't tried again. Its `-t` is how long it waits
    for the answer once the payload is sent: `timeout`, above a hold's day. A
    failure, to reach the service in that minute or any other, ends the command
    with status 1 and a line on standard error.

    The service answers every hook with something, an empty JSON object where
    it decides nothing (`UNDECIDED`, `host/service.py`), so a connection that
    ends with no answer was lost: the service stopped, or its process ended or
    was killed, each of which `socat` ends with status 0 and nothing printed.
    The command then does what `lost` says for `event`, never ending as the
    no decision the runtime would read in silence. The answer is kept whole,
    trailing newlines too, with a mark after it that the shell's capture can't
    strip. At a worktree asked for, the hook makes the worktree the answer
    names, and at a call's start, any the answer names first, in the room, so
    its checkout runs the room's own git, never the host's (`printing`).
    """
    socket = LaunchSockets(directory=RoomPaths().sockets).hook
    seconds = str(int(timeout.total_seconds()))
    bridge = Bridge(socket, io.StringIO())
    tries = round(bridge.patience / bridge.retry)
    address = f"UNIX-CONNECT:{socket},retry={tries},interval={bridge.retry:g}"
    pipe = shlex.join(["socat", "-t", seconds, "-", address])
    unreached = shlex.quote(
        f"lup: this hook couldn't reach lup's host service on {socket}, so it "
        "wasn't judged. On the host, `lup-dev host` serves this session again."
    )
    gone = lost(event)
    script = "\n".join(
        [
            f"answer=$({pipe} && echo .) || {{ echo {unreached} >&2; exit 1; }}",
            (
                f'[ "$answer" != . ] || {{ echo {shlex.quote(gone.said)} >&2; '
                f"exit {gone.status}; }}"
            ),
            printing(event),
        ]
    )
    return ["sh", "-c", script]


WORKTREE = files("lup_dev.launch").joinpath("worktree.sh")
"""The room's hook's last step where an answer may name a worktree for the room
to make with its own git, a shell script of its own (`printing`)."""


def printing(event: type[SessionEvent]) -> str:
    """Return what the room's hook at `event` does with the service's answer, kept in `$answer` with its mark: at a worktree asked for and at a call's start, it's piped to `worktree.sh`, which makes the worktree it names first and prints the root or the rest; at every other event, it's printed as it is."""
    answer = 'printf %s "${answer%.}"'
    if event is WorktreeAsked:
        return f"{answer} | sh -c {shlex.quote(WORKTREE.read_text())} worktree asked"
    if event is CallStarted:
        return f"{answer} | sh -c {shlex.quote(WORKTREE.read_text())} worktree started"
    return answer


def hooked(
    spelled: Callable[
        [Callable[[type[SessionEvent]], list[str]], timedelta], list[Hook]
    ],
    hold: timedelta = timedelta(hours=25),
) -> list[Hook]:
    """Return a runtime's hooks, as its adapter spells them (`spelled`), each running the room's pipe for its event.

    The hook waits for its answer as long as the pipe does: `hold`, above a hold's
    day.
    """
    return spelled(partial(piped, timeout=hold), hold)


def served(hold: timedelta = timedelta(hours=25)) -> list[ToolServer]:
    """Return the tool servers a launched session loads: lup's, on the launch's `mcp.sock` in the room.

    A call to it may wait for the operator, so the runtime waits on one as long as
    the hook does: `hold`, above a hold's day. It pushes what waits for an idle
    session, starting its turn, where the runtime takes a push.
    """
    socket = LaunchSockets(directory=RoomPaths().sockets).mcp
    return [ToolServer(name=SERVER, socket=socket, timeout=hold, pushes=True)]


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
    rules: list[Rule],
    lent: list[Lent] | None = None,
) -> TerminalSettings:
    """Return what lup adds to the session launched in `worktree`, its files compiled into `directory`.

    `tools` are lup's tools the host service serves it, `neighbours` the other
    repositories named for it, as the launch found them, and `lent` the
    directories lent to this launch, which its guidance lists, and `shared`
    where each module whose data the room mounts has it. `rules` are lup's code
    rules the declaration's selection runs, which a section of its guidance
    lists with `rules()`. Raise `GuidanceError` naming a section of guidance
    that can't be read, or doesn't render.
    """
    resolved = approved.resolved
    session = session_settings(resolved.session)
    return TerminalSettings(
        directory=directory,
        cli=cli,
        hooks=hooks,
        servers=served(),
        messages=LaunchSockets(directory=RoomPaths().sockets).messages,
        guidance=render(
            resolved,
            approved.root,
            worktree,
            tools,
            neighbours,
            shared=shared,
            lent=lent,
            rules=rules,
        ),
        session=session.declared,
        defaults=session.defaults,
        trusted=trusted(worktree),
    )
