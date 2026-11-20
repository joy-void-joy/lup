"""The program a session's room runs first: it connects to its holder's socket, puts that connection on its input and output, and runs the runtime in its place.

Run as `python -I -m lup.environment.sessions.connected <socket> -- <runtime…>`.
The runtime's input is then a socket only the holder holds: another process of
the operator's can reopen a pipe through `/proc/<pid>/fd/0` and write a turn as
the operator, but not a socket (`docs/field-notes.md`, *A session held with no
terminal*). It connects before it runs anything else, the room's first program
under podman's init, so nothing in the room can connect first; the holder takes
one connection and closes its socket.

With `--sync`, it first starts syncing the worktree's environment in the
background (`uv sync --frozen`), so the runtime starts at once and the project's
environment follows it. With `--serving`, it also starts the room's own parts
in the background, from the worktree's own code in that environment, answering
on the room's socket (`lup.environment.running`), as a project's container
answers on its own.
"""

import os
import socket
from typing import Annotated
lazy from pathlib import Path

import typer

from lup.programs import detached

app = typer.Typer(add_completion=False)


@app.command()
def connected(
    held: Annotated[Path, typer.Argument(help="The holder's socket.")],
    command: Annotated[list[str], typer.Argument(help="The runtime's command.")],
    sync: Annotated[
        Path | None, typer.Option(help="Sync the worktree's environment, logging here.")
    ] = None,
    serving: Annotated[
        str | None,
        typer.Option(help="Start the room's own parts, as this start says (JSON)."),
    ] = None,
) -> None:
    """Connect to the holder, then run the runtime on that connection, in this program's place."""
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(str(held))
    os.dup2(connection.fileno(), 0)
    os.dup2(connection.fileno(), 1)
    connection.close()
    if sync is not None:
        detached("uv", "sync", "--frozen", "--quiet", log=sync)
    if serving is not None and sync is not None:
        detached(
            "env",
            f"LUP_ASKED={serving}",
            "uv",
            "run",
            "--frozen",
            "python",
            "-m",
            "lup.environment.running",
            log=sync.with_name("parts.log"),
        )
    # lup: ignore("os-shell", why="the runtime takes this program's place, its input and output the holder's connection: no child process lup.programs could run")
    os.execvp(command[0], command)


if __name__ == "__main__":
    app()
