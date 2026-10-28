"""Where each launched session's record is, and what the host reads of a path a room names: the home of the rooms' own its launch ran on (`docs/launch.md`, *A home of the rooms' own*).

The host service keeps a session's home from the launch it first hears the
session from (`kept`), as each launch registers its home (`Register.home`),
and the host reads a launched session's record there alone (`home_of`); a
session no launch was heard on is read from the operator's own directory
alone. So a room naming another room's session in its hooks, or one of the
operator's, can't have the host read a record it planted in its own home
under that name.

A hook's payload names its conversation's record by the path the runtime has
for it, inside the launch's own runtime directory, which the room writes,
links into the shared home among it. The host never follows those links: a
path under the own directory of the launch whose room ran the hook is read as
the same path in the home that launch registered, confined there
(`translated`, `Found`), and any other path a room names isn't read at all,
one under another launch's own directory among them. Reading a record it
keeps, rather than answering a hook, the host takes a path a line of it names
as any served launch's (`served`), and reads it only inside the record's own
session folder.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from lup.rooms.homes import plain
from lup.types import Model
from lup_dev.host.protocol import Register

if TYPE_CHECKING:
    from lup_dev.host.records import Records
    from lup_dev.layout import HostLayout, Layout


class Found(Model):
    """A record found in a directory a room may write, and that directory, which every read of the record and of what's beside it must stay inside (`lup.rooms.homes.opened`)."""

    record: Path
    root: Path


def kept(
    layout: HostLayout,
    runtime: str,
    session: str,
    home: Path,
    operators: Records | None = None,
) -> None:
    """Keep `home` as where the record of session `session` of `runtime` is, where nothing is kept for it yet and the operator's own directory holds none of it (`operators`, the runtime's records): the first launch the host service hears it from holds it, so a room naming another's session later, or the operator's own, reads nothing of theirs.

    An id that isn't a plain name is kept nowhere: a hook's payload, which a
    room writes, gives it. A session the operator ran on the host is kept
    nowhere either, so its record stays read from their directory, though a
    room's hook names it first. Where lup itself moves or copies a session's
    record into a home, on the host, it keeps that home without `operators`,
    since it knows where the record went.
    """
    if not plain(session) or not plain(runtime):
        return
    place = layout.home_of(runtime, session)
    if place.exists():
        return
    if operators is not None and operators.held(session):
        return
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(str(home))


def home_of(layout: HostLayout, runtime: str, session: str) -> Path | None:
    """Return where the record of session `session` of `runtime` is kept, as the launch the host service first heard it from has it; none for a session no launch was heard on, as one from before launches had homes, or an id that isn't a plain name."""
    if not plain(session) or not plain(runtime):
        return None
    place = layout.home_of(runtime, session)
    return Path(place.read_text()) if place.is_file() else None


def translated(launch: Register | None, path: Path) -> Found | None:
    """Return where `path`, a path a hook's payload names inside the own runtime directory of `launch`, the launch whose room ran the hook, is in the home it registered, with that home to read it in; none for any other path, one under another launch's own directory among them, for a launch registering no home, or for no launch.

    `launch` is the one the host service heard the hook on, by its socket,
    never one the payload names, so a room naming a path under another
    launch's own directory has nothing of that launch's home read. Its own
    directory (`Register.own`) is the room's to write, links into the home
    among it, so nothing of it is read or followed on the host: only the
    path's place inside it is taken, laid on the home.
    """
    if launch is None or launch.own is None or launch.home is None:
        return None
    try:
        rest = path.relative_to(launch.own)
    except ValueError:
        return None
    if not rest.parts or ".." in rest.parts:
        return None
    return Found(record=launch.home / rest, root=launch.home)


def served(layout: Layout) -> list[Register]:
    """Return every launch the host service serves, as its record has it, a record that can't be read passed over: for the host reading a record it keeps, whose lines a session resumed across launches wrote in each one's own runtime directory, never for a room's request, which reads its own launch's alone (`translated`)."""
    launches = layout.host.launches
    found = sorted(launches.glob("*.json")) if launches.is_dir() else []
    return [launch for each in found if (launch := registration(each)) is not None]


def registration(record: Path) -> Register | None:
    """Return the launch recorded at `record`; none where it can't be read, or isn't a launch's record, as the conversations kept beside it aren't."""
    try:
        return Register.model_validate_json(record.read_text())
    except OSError, ValidationError:
        return None
