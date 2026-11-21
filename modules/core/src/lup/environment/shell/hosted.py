"""The dashboard as the machine serves it, beside the machine's socket, from the commit the operator approved.

`hosted()` starts it once its parts run, before the operator's socket listens,
so `lup` alone, once the machine answers, finds its address. Its calls go
through the operator's socket, as a terminal's do, so `Carrying` routes them and
vouches they're the operator's: the server itself can't run in a container,
since only that socket, which no container mounts, says a call is theirs. Its
page is built by `Pages` in the background, the server saying why there's none
until it's there. Whether it serves and on which port is the core's
(`Core.dashboard`), read from the home repository's declaration with the
machine's layer over it; its token and draft are kept in the machine's state
across restarts, so an open page reconnects, and its address while it serves
in the machine's runtime place, each readable by the operator alone.

The server is lup-core's `dashboard` extra, which the command line never
imports: where it isn't installed, the machine runs without a dashboard, its
log saying so.
"""

import asyncio
import importlib.util
import logging
import secrets
import socket
import webbrowser
from urllib.parse import urldefrag
lazy from pathlib import Path

from lup.core import Core
from lup.declaration.grammar import applied, set_fields
from lup.doors.door import Accepted
from lup.doors.parties import Machine
from lup.environment.declaration import Resolved, load, resolve
from lup.environment.running.calling import Calling
from lup.environment.shell.layout import DashboardPlaces, ShellLayout
from lup.inbox.said import PartiesOf
from lup.running.plan import CORE
from lup.shell.blocks import Viewing
from lup.shell.pages import BuiltPage, PageSource
from lup.types import MutableModel
lazy from lup.declaration.layout import MachineLayout
lazy from lup.environment.doors import Running
lazy from lup.environment.shell.server import (
    Dashboard,
    Keeping,
    Serving,
    described,
    serve,
)
lazy from lup.inbox.part import Inboxes
lazy from lup.running.wire import Host

log = logging.getLogger(__name__)


class Served(MutableModel, arbitrary_types_allowed=True):
    """The dashboard as the machine serves it: the task serving it, what stops it, and its page's build."""

    serving: asyncio.Task[None]
    stopping: asyncio.Event
    building: asyncio.Task[None]
    places: DashboardPlaces

    async def stopped(self) -> None:
        """Take its address away, stop its page's build where it's still running, and stop serving.

        Raise what the build raised, where it failed rather than refused.
        """
        self.places.address().unlink(missing_ok=True)
        self.building.cancel()
        self.stopping.set()
        await self.serving
        await asyncio.wait([self.building])
        if not self.building.cancelled():
            failed = self.building.exception()
            if failed is not None:
                raise failed


def kept(path: Path, text: str) -> None:
    """Write `text` to `path`, readable and writable by the operator alone, its directory made first, theirs alone too."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text(text)


def token_at(path: Path) -> str:
    """Return the token kept at `path`, a new one kept there first where there's none."""
    if not path.is_file():
        kept(path, secrets.token_urlsafe(32))
    return path.read_text()


def declared(host: Host, machine: MachineLayout) -> Resolved:
    """Return the home repository's declaration at the commit `host` runs, resolved, with the machine's layer over it where there's one."""
    project = load(host.root / host.declaration)
    if machine.layer.is_file():
        layer = load(machine.layer)
        project = applied(layer, project, set_fields(layer))
    return resolve(project)


async def built(running: Running, serving: Serving) -> None:
    """Have `Pages` build the page from the source of the commit the machine runs, and serve it once it's there, or say why it isn't."""
    asked = PageSource(source=ShellLayout().source, described=described())
    answer = await running.serve("page", asked.model_dump(mode="json"), Machine())
    serving.building = False
    if isinstance(answer, Accepted):
        serving.page = BuiltPage.model_validate(answer.output).path
        serving.why = ""
        return
    serving.why = answer.rejection.reason
    log.warning("lup's dashboard has no page: %s", serving.why)


async def started(
    host: Host, running: Running, calling: Path, machine: MachineLayout
) -> Served | None:
    """Start serving the dashboard of the machine `host` says, its calls through the operator's socket at `calling`, and its page's build.

    None where the core says not to serve it, its server isn't installed, or
    its port can't be listened on, the machine's log saying which.
    """
    resolved = declared(host, machine)
    core = next(each for each in resolved.modules if isinstance(each, Core))
    if not core.dashboard.serve:
        return None
    if importlib.util.find_spec("uvicorn") is None:
        log.warning(
            "lup's dashboard isn't served: its server, lup-core's `dashboard` "
            "extra, isn't installed"
        )
        return None
    port = core.dashboard.port
    listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listening.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listening.bind(("127.0.0.1", port))
    except OSError as taken:
        listening.close()
        log.warning("lup's dashboard can't listen on port %d: %s", port, taken)
        return None
    places = DashboardPlaces.of(host.state, host.runtime)
    places.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    serving = Serving(page=None, why="it's being built", building=True)
    dashboard = Dashboard(
        answerer=Calling(socket=calling, repository=host.repository),
        looks=resolved.looks,
        root=core.document
        or Viewing.of(
            Inboxes.parties, PartiesOf(repository=host.repository), module=CORE
        ),
        kept=Keeping.at(places.draft()),
        token=token_at(places.token()),
        serving=serving,
        repository=host.repository,
    )
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    serves = loop.create_task(serve(dashboard, listening, stopping))
    kept(places.address(), f"http://127.0.0.1:{port}/#{dashboard.token}")
    building = loop.create_task(built(running, serving))
    return Served(serving=serves, stopping=stopping, building=building, places=places)


def opened(places: DashboardPlaces) -> str | None:
    """Open the dashboard the machine serves in the operator's browser, and say what to tell them; none where it serves none."""
    address = places.address()
    if not address.is_file():
        return None
    told = address.read_text()
    if webbrowser.open(told):
        return f"the dashboard is open in your browser, at {urldefrag(told).url}"
    return f"open the dashboard at {told}"
