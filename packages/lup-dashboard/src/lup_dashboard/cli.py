"""`lup-dashboard`: the dashboard's server, which the host service runs as its child, and the API's description.

`docs/dashboard.md`. The operator opens the dashboard with `lup-dev dashboard`;
this command is the host service's to run (`lup_dev/host/dashboard.py`).
"""

import asyncio
import json
import secrets
import socket
import sys

import typer
import uvicorn

from lup_dashboard.demo import Demo
from lup_dashboard.host import Sockets
from lup_dashboard.layout import DashboardLayout
from lup_dashboard.server import Access, application
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings

app = typer.Typer(
    no_args_is_help=True, help="lup's dashboard, which lup's host service runs."
)


@app.command()
def serve(port: int, address: str = "127.0.0.1") -> None:
    """Serve the dashboard on `address` and `port` until its input closes, printing its address once it listens.

    The host service runs it, writing the token every call to the API carries
    as its input's first line and reading the address it prints, and keeps its
    input open while it serves. Port 0 takes one that's free.
    """
    token = sys.stdin.readline().strip()
    listening = socket.create_server((address, port))
    bound = listening.getsockname()[1]
    served = application(
        Sockets(layout=Layout.of(LupDevSettings()).host),
        Access(token=token, port=bound),
        DashboardLayout().page,
    )
    typer.echo(f"http://{address}:{bound}")
    server = uvicorn.Server(uvicorn.Config(served, log_level="warning"))
    asyncio.run(until_closed(server, listening))


async def until_closed(server: uvicorn.Server, listening: socket.socket) -> None:
    """Serve on `listening` until the input closes, as the host service's end closes it."""
    serving = asyncio.create_task(server.serve(sockets=[listening]))
    closed = asyncio.create_task(asyncio.to_thread(sys.stdin.read))
    await asyncio.wait([serving, closed], return_when=asyncio.FIRST_COMPLETED)
    server.should_exit = True
    await serving


@app.command()
def demo(port: int = 8767, address: str = "127.0.0.1") -> None:
    """Serve the dashboard over stand-in data on `address` and `port`, until stopped, printing where to open it.

    The real page, every view populated, with no host service or session behind
    it (`lup_dashboard/demo.py`): for looking at a view while it's built, and
    trying one before it lands.
    """
    token = secrets.token_urlsafe(16)
    listening = socket.create_server((address, port))
    bound = listening.getsockname()[1]
    served = application(
        Demo(), Access(token=token, port=bound), DashboardLayout().page, demo=True
    )
    typer.echo(f"http://{address}:{bound}/#token={token}")
    server = uvicorn.Server(uvicorn.Config(served, log_level="warning"))
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
