#!/usr/bin/env python3
"""`wl-paste` and `wl-copy` in a room: the operator's clipboard, through lup's host service.

`docs/launch.md`, *The clipboard*. A room has no display; the room sets
`WAYLAND_DISPLAY`, so its programs reach for Wayland's clipboard programs, and
finds these first on its `PATH`, one program under both names, each acting as
the one it's run as. Each sends one request on the launch's request socket
(`clipboard/protocol.py`) and does what the real program does with the answer:
- `wl-paste` prints what the clipboard holds: as text, or as the type
  `--type` names; `--list-types` lists its types, one a line; `--primary`
  reads the primary selection; text ends with a newline unless
  `--no-newline`;
- `wl-copy` puts its arguments, or its input where it has none, on the
  clipboard, or the primary selection with `--primary`.

A refusal is said on the standard error, ending with status 1, as the real
program ends when nothing is copied. The room's Python runs it, with the
standard library alone (an import contract keeps it so).
"""

# lup: ignore("argparse", why="the room's Python runs the shim on the standard library alone, where typer isn't")
import argparse
import base64
import json
import socket
import sys
from pathlib import Path

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
"""A JSON value, as the host's requests and replies are written."""


def failed(reason: str) -> SystemExit:
    """Return the exit that ends the program, saying `reason` on its standard error."""
    return SystemExit(f"lup: {reason}")


def asked(request: dict[str, Json], requests: Path) -> Json:
    """Send one request to the host on the launch's request socket, and return its reply; a refusal ends the program."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        try:
            connection.connect(str(requests))
        except OSError as gone:
            message = (
                f"lup's host service doesn't answer on {requests} ({gone}): on the "
                "host, `lup-dev host` serves this room again"
            )
            raise failed(message) from gone
        connection.sendall(json.dumps(request).encode())
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as stream:
            answer = stream.read()
    if not answer:
        message = "lup's host service closed the connection without answering"
        raise failed(message)
    reply = json.loads(answer)
    match reply:
        case {"kind": "refused", "error": str() as error}:
            raise failed(error)
        case _:
            return reply


def pasted(arguments: list[str], requests: Path) -> None:
    """Act as `wl-paste`: print the clipboard's types, or what it holds."""
    parser = argparse.ArgumentParser(
        prog="wl-paste", description="Print the operator's clipboard, through lup."
    )
    parser.add_argument("-l", "--list-types", action="store_true")
    parser.add_argument("-t", "--type")
    parser.add_argument("-n", "--no-newline", action="store_true")
    parser.add_argument("-p", "--primary", action="store_true")
    parser.add_argument("-s", "--seat", help="accepted, and left to the host")
    given = parser.parse_args(arguments)
    if given.list_types:
        listing: dict[str, Json] = {"kind": "clipboard-types", "primary": given.primary}
        match asked(listing, requests):
            case {"kind": "clipboard-types-listed", "types": list() as types}:
                sys.stdout.write("".join(f"{each}\n" for each in types))
                return
            case reply:
                message = f"lup's host service answered {reply!r} to listing types"
                raise failed(message)
    request: dict[str, Json] = {
        "kind": "clipboard-read",
        "type": given.type,
        "primary": given.primary,
    }
    match asked(request, requests):
        case {"kind": "clipboard-held", "data": str() as data}:
            held = base64.b64decode(data)
        case reply:
            message = f"lup's host service answered {reply!r} to a read"
            raise failed(message)
    textual = given.type is None or given.type.startswith("text/")
    ended = held.endswith(b"\n") or given.no_newline or not textual
    sys.stdout.buffer.write(held if ended else held + b"\n")


def copied(arguments: list[str], requests: Path) -> None:
    """Act as `wl-copy`: put its arguments, or its input, on the clipboard."""
    parser = argparse.ArgumentParser(
        prog="wl-copy", description="Put text on the operator's clipboard, through lup."
    )
    parser.add_argument("text", nargs="*")
    parser.add_argument("-p", "--primary", action="store_true")
    parser.add_argument("-t", "--type", help="accepted: what's copied is text")
    parser.add_argument("-o", "--paste-once", action="store_true", help="accepted")
    parser.add_argument("-f", "--foreground", action="store_true", help="accepted")
    parser.add_argument("-n", "--trim-newline", action="store_true")
    parser.add_argument("-s", "--seat", help="accepted, and left to the host")
    given = parser.parse_args(arguments)
    text = " ".join(given.text) if given.text else sys.stdin.read()
    if given.trim_newline and text.endswith("\n"):
        text = text.removesuffix("\n")
    request: dict[str, Json] = {
        "kind": "clipboard-write",
        "text": text,
        "primary": given.primary,
    }
    match asked(request, requests):
        case {"kind": "done"}:
            return
        case reply:
            message = f"lup's host service answered {reply!r} to a copy"
            raise failed(message)


def main(requests: Path = Path("/run/lup/request.sock")) -> None:
    """Act as the program it's run as, `wl-copy` or `wl-paste`, asking the host on `requests`: the launch's request socket, where every room mounts it."""
    name = Path(sys.argv[0]).name
    arguments = sys.argv[1:]
    if name == "wl-copy":
        copied(arguments, requests)
        return
    pasted(arguments, requests)


if __name__ == "__main__":
    main()
