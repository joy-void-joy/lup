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
path under the launch's own directory is read as the same path in the home the
launch registered, confined there (`translated`, `Found`), and any other path
a room names isn't read at all.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from lup.rooms.homes import plain
from lup.types import Model
from lup_dev.host.protocol import Register

if TYPE_CHECKING:
    from lup_dev.layout import HostLayout, Layout


class Found(Model):
    """A record found in a directory a room may write, and that directory, which every read of the record and of what's beside it must stay inside (`lup.rooms.homes.opened`)."""

    record: Path
    root: Path


def kept(layout: HostLayout, runtime: str, session: str, home: Path) -> None:
    """Keep `home` as where the record of session `session` of `runtime` is, where nothing is kept for it yet: the first launch the host service hears it from holds it, so a room naming another's session, or the operator's own, later reads nothing of theirs.

    An id that isn't a plain name is kept nowhere: a hook's payload, which a
    room writes, gives it.
    """
    if not plain(session) or not plain(runtime):
        return
    place = layout.home_of(runtime, session)
    if place.exists():
        return
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(str(home))


def home_of(layout: HostLayout, runtime: str, session: str) -> Path | None:
    """Return where the record of session `session` of `runtime` is kept, as the launch the host service first heard it from has it; none for a session no launch was heard on, as one from before launches had homes, or an id that isn't a plain name."""
    if not plain(session) or not plain(runtime):
        return None
    place = layout.home_of(runtime, session)
    return Path(place.read_text()) if place.is_file() else None


def translated(layout: Layout, path: Path) -> Found | None:
    """Return where `path`, a path a hook's payload names inside a launch's own runtime directory, is in the home that launch registered, with that home to read it in; none for any other path, or a launch registering no home.

    The launch is found among those the host service serves by the own
    directory its registration names (`Register.own`). That directory is the
    room's to write, links into the home among it, so nothing of it is read or
    followed on the host: only the path's place inside it is taken, laid on
    the home.
    """
    launches = layout.host.launches
    found = sorted(launches.glob("*.json")) if launches.is_dir() else []
    for each in found:
        try:
            registered = Register.model_validate_json(each.read_text())
        except (OSError, ValidationError):
            continue
        if registered.own is None or registered.home is None:
            continue
        try:
            rest = path.relative_to(registered.own)
        except ValueError:
            continue
        if not rest.parts or ".." in rest.parts:
            return None
        return Found(record=registered.home / rest, root=registered.home)
    return None
