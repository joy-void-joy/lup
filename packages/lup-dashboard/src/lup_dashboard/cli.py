"""`lup-dashboard`: the dashboard's server, which the host service runs as its child, and the API's description.

`docs/dashboard.md`. The operator opens the dashboard with `lup-dev dashboard`;
this command is the host service's to run (`lup_dev/host/dashboard.py`).
"""

import asyncio
import json
import secrets
import socket
import sys
import tempfile
from datetime import timedelta
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
import uvicorn

from lup_dashboard.copied import Asking, taken
from lup_dashboard.demo import Demo
from lup_dashboard.errors import CopyError
from lup_dashboard.host import Host, Sockets
from lup_dashboard.layout import DashboardLayout, DemoLayout, checkout
from lup_dashboard.server import Access, OfCopy, application
from lup_dev.cli import adapters
from lup_dev.host.protocol import HostError
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from lup_dev.settings import Address

app = typer.Typer(
    no_args_is_help=True, help="lup's dashboard, which lup's host service runs."
)


@app.command()
def serve(
    port: int,
    address: Annotated[
        list[str] | None,
        typer.Option(
            help=(
                "An address of this machine's to listen on beside localhost, as the "
                "host service passes each of `LUP_DASHBOARD_ADDRESSES`; given again "
                "for each."
            )
        ),
    ] = None,
) -> None:
    """Serve the dashboard on localhost and each `--address`, on `port`, until its input closes, printing its localhost address once it listens.

    The host service runs it, writing the token every call to the API carries
    as its input's first line and reading the address it prints, and keeps its
    input open while it serves. Port 0 takes one that's free, which every
    address then listens on. An address the machine doesn't hold yet, as a
    tunnel's before the tunnel is up, is bound all the same (`freely`), and
    answers once the machine has it.
    """
    token = sys.stdin.readline().strip()
    listening = socket.create_server(("127.0.0.1", port))
    access = Access(
        token=token,
        port=listening.getsockname()[1],
        addresses=[ip_address(each) for each in address or []],
    )
    sockets = [listening, *(freely(each, access.port) for each in access.addresses)]
    served = application(
        Sockets(layout=Layout.of(LupDevSettings()).host), access, DashboardLayout().page
    )
    typer.echo(f"http://127.0.0.1:{access.port}")
    server = uvicorn.Server(uvicorn.Config(served, log_level="warning"))
    asyncio.run(until_closed(server, sockets))


def freely(address: Address, port: int) -> socket.socket:
    """Return a socket listening on `address` and `port`, bound whether or not the machine holds the address yet.

    Linux's `IP_FREEBIND`, which binds an address no interface has, so a
    WireGuard address is served from the moment the tunnel is up, and a
    dashboard started before it loses nothing; without it, the bind fails and
    the dashboard with it, on localhost too.
    """
    family = socket.AF_INET6 if isinstance(address, IPv6Address) else socket.AF_INET
    opened = socket.socket(family, socket.SOCK_STREAM)
    opened.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    opened.setsockopt(socket.IPPROTO_IP, socket.IP_FREEBIND, 1)
    opened.bind((str(address), port))
    opened.listen()
    return opened


async def until_closed(server: uvicorn.Server, sockets: list[socket.socket]) -> None:
    """Serve on `sockets` until the input closes, as the host service's end closes it."""
    serving = asyncio.create_task(server.serve(sockets=sockets))
    closed = asyncio.create_task(asyncio.to_thread(sys.stdin.read))
    await asyncio.wait([serving, closed], return_when=asyncio.FIRST_COMPLETED)
    server.should_exit = True
    await serving


@app.command()
def demo(
    port: int = 8767,
    address: str = "127.0.0.1",
    *,
    size: Annotated[
        int | None,
        typer.Option(
            help=(
                "How many flagged writes of a busy day the review holds beside the "
                "demo's own items, each of a file of hundreds of lines, from six "
                "workers: a busy day's unless given, 0 for the demo's own items alone."
            )
        ),
    ] = None,
    hooks: Annotated[
        float,
        typer.Option(
            help=(
                "How many stand-in hook calls a minute the workers make, each "
                "answering every watch again, as the host service does at each hook."
            )
        ),
    ] = 0,
    approval_lines: Annotated[
        int,
        typer.Option(
            help=(
                "How many lines the approval's change holds beside its own files, "
                "as one of lup's own code may hold tens of thousands: half in "
                "production modules, every function changed, half in their tests."
            )
        ),
    ] = 0,
    timings: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Keep what the page measures of itself in this directory, laid out "
                "as the host keeps it, for `lup-dev dashboard timings --kept` to "
                "read; by default in the demo's own directory, gone as it stops."
            )
        ),
    ] = None,
    arrives: Annotated[
        float | None,
        typer.Option(
            help=(
                "How many seconds after the page first asks for the inbox a question "
                "of the parser subagent's arrives: long enough to watch, unless given."
            )
        ),
    ] = None,
    grows: Annotated[
        float | None,
        typer.Option(
            help=(
                "How many seconds after the page first asks what the parser "
                "subagent's branch changed two more writes come to it: long enough "
                "to watch, unless given."
            )
        ),
    ] = None,
    types_read: Annotated[
        float | None,
        typer.Option(
            help=(
                "How many seconds after the page first asks for the approval's files "
                "their types are read: long enough to watch, unless given."
            )
        ),
    ] = None,
    copy: Annotated[
        bool,
        typer.Option(
            "--copy",
            help=(
                "Serve a copy of the operator's dashboard state in place of the "
                "stand-ins, every repository's, taken from the host through the "
                "launch's request socket into a directory of the demo's own, removed "
                "as it stops, and answered by this checkout's code: what's done on "
                "the page changes the copy alone. In a launched session only."
            ),
        ),
    ] = False,
    token_file: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Keep the demo's token in this file, read back as it starts again, so "
                "its address stays the same and a page left open carries on across a "
                "restart, reconnecting, rather than being refused. A fresh token at "
                "each start, unless given."
            )
        ),
    ] = None,
) -> None:
    """Serve the dashboard over stand-in data on `address` and `port`, until stopped, printing where to open it.

    The real page, every view populated, each request answered by the host's own
    handler over stand-in state, with no host service or session behind it
    (`lup_dashboard/demo.py`): for looking at a view while it's built, and trying
    one before it lands, at a busy day's size (`--size`), with an approval of
    lup's own code at size (`--approval-lines`) and, with `--hooks`, under a busy
    day's watch answers. With `--copy`, over a copy of the operator's dashboard
    state instead (`lup_dashboard/copied.py`).
    """
    if copy:
        if (
            size is not None
            or hooks
            or approval_lines
            or arrives
            or grows
            or types_read
        ):
            message = (
                "--copy serves the operator's state as it is: it takes none of "
                "--size, --hooks, --approval-lines, --arrives, --grows or --types-read"
            )
            raise typer.BadParameter(message)
        copied(port, address, timings, token_file)
        return
    host = Demo(
        hooks=hooks,
        approval_lines=approval_lines,
        timings=timings,
        say=lambda line: typer.echo(f"demo: {line}", err=True),
    )
    if size is not None:
        host.size = size
    if arrives is not None:
        host.arrives = timedelta(seconds=arrives)
    if grows is not None:
        host.grows = timedelta(seconds=grows)
    if types_read is not None:
        host.types_read = timedelta(seconds=types_read)
    served(host, port, address, token_file=token_file)


def copied(port: int, address: str, timings: Path | None = None, token_file: Path | None = None) -> None:
    """Serve the dashboard over a copy of the operator's dashboard state, taken into a directory of its own removed as it stops, until stopped; what the page measures of itself kept in `timings`, where it's given.

    The checkout it runs in answers its repository's views by its own
    declaration (`checkout`). What the copy can't be taken or read for is said,
    and nothing is served.
    """
    root = checkout(Path.cwd())
    if root is None:
        message = (
            f"--copy runs in a checkout, whose declaration answers its repository's "
            f"views: {Path.cwd()} is in none"
        )
        raise typer.BadParameter(message)
    readers = {adapter.runtime.name(): adapter.reader for adapter in adapters()}
    with tempfile.TemporaryDirectory(prefix="lup-dashboard-copy-") as kept:
        try:
            host = taken(
                DemoLayout(home=Path(kept)),
                Asking(),
                root,
                readers,
                say=lambda line: typer.echo(f"copy: {line}", err=True),
                timings=timings,
            )
        except (CopyError, HostError) as failed:
            typer.echo(f"lup-dashboard: the copy can't be served: {failed}", err=True)
            raise typer.Exit(1) from failed
        served(host, port, address, OfCopy(defaults=host.views.by_defaults()), token_file)


def kept_token(path: Path | None) -> str:
    """Return the demo's token: the one kept in `path`, or a fresh one, kept there where it's given, only its owner reading it.

    >>> len(kept_token(None)) > 16
    True
    """
    if path is not None and path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(16)
    if path is not None:
        path.touch(mode=0o600)
        path.write_text(token)
    return token


def served(
    host: Host,
    port: int,
    address: str,
    copied: OfCopy | None = None,
    token_file: Path | None = None,
) -> None:
    """Serve the demo over `host` on `address` and `port`, until stopped, printing where to open it, its token in the fragment."""
    token = kept_token(token_file)
    listening = socket.create_server((address, port))
    bound = listening.getsockname()[1]
    app = application(
        host,
        Access(token=token, port=bound),
        DashboardLayout().page,
        demo=True,
        copied=copied,
    )
    typer.echo(f"http://{address}:{bound}/#token={token}")
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    asyncio.run(server.serve(sockets=[listening]))


@app.command()
def openapi() -> None:
    """Print the API's description as JSON, which the page's types are generated from."""
    described = application(
        Sockets(layout=Layout.of(LupDevSettings()).host),
        Access(token="", port=0),
        None,
    )
    typer.echo(json.dumps(described.openapi(), indent=2))


def main() -> None:
    """Run the command line."""
    app()


if __name__ == "__main__":
    main()
