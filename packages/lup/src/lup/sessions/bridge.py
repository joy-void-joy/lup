#!/usr/bin/env python3
"""lup's MCP bridge: a runtime's stdio MCP server, carrying each message to lup's server on a Unix socket, across that server's restarts.

`docs/host-tools.md`, *The server*. A runtime runs this as one of its MCP
servers, `python3 -I <launch>/mcp-bridge.py <socket>`, and speaks MCP to it on
its standard input and output: newline-delimited JSON-RPC, one message a line,
which is what lup's server reads on its socket too (`lup.tools.serving.serve`).
Each line goes across as it is, both ways.

When the server goes, as when lup's host service restarts, the runtime's side
stays open, where a plain pipe would end and the runtime mark the server failed
for good, since no runtime starts a stdio server again.
- A request the server was answering is answered with an error saying so: its
  answer is lost, and it may have been carried out.
- The bridge tries to reach the server again every half second (`retry`). A
  request arriving meanwhile waits for it, and is answered with an error after
  a minute without it (`patience`).
- Once it's reached again, the bridge introduces the runtime to it as the
  runtime introduced itself the first time: its `initialize` request, under an
  id of the bridge's whose answer it keeps to itself. Only the answer makes
  the server back: a server going away can still take a connection it never
  answers, its socket listening a moment longer, and a connection that closes
  before the answer is tried again with nothing sent but the introduction.
  Then `notifications/initialized` and what waited go across, and the runtime
  is told the server's tools changed (`notifications/tools/list_changed`), so
  it lists them again and finds what the restarted copy serves.

It runs on the room's Python with the standard library alone (an import contract
keeps it so), as git's remote helper does.
"""

import json
import socket
import sys
import threading
import time
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
"""A JSON value, as a message is written."""

OURS = "lup-bridge"
"""What the ids of the bridge's own requests start with."""


def line(message: dict[str, Json]) -> str:
    """Write `message` as one line of JSON-RPC."""
    return json.dumps(message, separators=(",", ":")) + "\n"


def failure(ident: Json, reason: str) -> str:
    """Return the error answering the request `ident`, saying `reason`."""
    return line(
        {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": -32000, "message": f"lup: {reason}"},
        }
    )


def read(text: str) -> Json:
    """Read one line as JSON, or none where it isn't."""
    try:
        parsed: Json = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed


def requested(message: Json) -> str | int | None:
    """Return the id of `message` where it's a request, which expects an answer."""
    match message:
        case {"method": str(), "id": str() | int() as ident}:
            return ident
        case _:
            return None


def answered(message: Json) -> str | int | None:
    """Return the id of the request `message` answers, where it's an answer."""
    match message:
        case {"method": _}:
            return None
        case {"id": str() | int() as ident}:
            return ident
        case _:
            return None


class Waiting:
    """A line the runtime sent while the server was away: the request it holds, where it's one, and when it arrived."""

    def __init__(self, text: str, ident: str | int | None, since: float) -> None:
        """Keep `text`, the id of the request it holds, and the monotonic time it arrived."""
        self.text = text
        self.ident = ident
        self.since = since


class Replay:
    """The runtime's introduction, for a server reached again: the bridge's own `initialize`, its id, and what follows once it's answered."""

    def __init__(self, ident: str, initialize: str, after: list[str]) -> None:
        """Keep the `initialize` line under `ident`, and the lines `after` it: `notifications/initialized`, where the runtime sent it."""
        self.ident = ident
        self.initialize = initialize
        self.after = after


class Bridge:
    """One runtime's bridge to lup's server on one socket."""

    def __init__(
        self,
        path: Path,
        output: TextIO,
        *,
        retry: float = 0.5,
        patience: float = 60.0,
    ) -> None:
        """Bridge to the server listening at `path`, writing the runtime's side to `output`.

        `retry` is how many seconds pass between attempts to reach the server
        while it's away; `patience`, how many a request waits for it before
        it's answered with an error.
        """
        self.path = path
        self.output = output
        self.retry = retry
        self.patience = patience
        self.lock = threading.Lock()
        """Guards the connection and what's kept about the session."""
        self.connection: socket.socket | None = None
        self.initialize: str | None = None
        """The runtime's `initialize` request, as it sent it."""
        self.initialized: str | None = None
        """The runtime's `notifications/initialized`, as it sent it."""
        self.introduced = False
        """A server heard the runtime's `initialize`, so the next one hears it
        from the bridge."""
        self.answering: list[str | int] = []
        """The requests the server has and hasn't answered yet."""
        self.waiting: list[Waiting] = []
        self.ids = count(1)

    def run(self, lines: Iterator[str]) -> None:
        """Carry each line the runtime sends until it closes its side, the server's lines carried back meanwhile."""
        threading.Thread(target=self.serving, daemon=True).start()
        for text in lines:
            self.sent(text if text.endswith("\n") else f"{text}\n")
        with self.lock:
            if self.connection is not None:
                self.connection.close()

    def sent(self, text: str) -> None:
        """Carry one line from the runtime to the server, or keep it until the server is back."""
        message = read(text)
        match message:
            case {"method": "initialize"}:
                self.initialize = text
            case {"method": "notifications/initialized"}:
                self.initialized = text
            case _:
                pass
        ident = requested(message)
        with self.lock:
            if self.connection is not None:
                try:
                    self.connection.sendall(text.encode())
                except OSError:
                    self.connection = None
                else:
                    self.introduced = self.introduced or text == self.initialize
                    if ident is not None:
                        self.answering = [*self.answering, ident]
                    return
            self.waiting = [*self.waiting, Waiting(text, ident, time.monotonic())]

    def serving(self) -> None:
        """Keep a connection to the server, carrying its lines to the runtime, and reach it again whenever it goes."""
        while True:
            connection = self.reached()
            with connection.makefile("r", encoding="utf-8", newline="\n") as lines:
                try:
                    if self.joined(connection, lines):
                        for text in lines:
                            self.received(text)
                except OSError:
                    pass
            self.lost(connection)

    def reached(self) -> socket.socket:
        """Return a connection to the server's socket once one is taken, trying again every `retry` seconds meanwhile."""
        while True:
            self.expired()
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                connection.connect(str(self.path))
            except OSError:
                connection.close()
                time.sleep(self.retry)
                continue
            return connection

    def joined(self, connection: socket.socket, lines: Iterator[str]) -> bool:
        """Join the server on `connection`, and say whether it answered: the runtime introduced to it again where it was before, then what waited sent.

        A server reached again is introduced to the runtime with the bridge's own
        `initialize` first, and is joined only once it answers it; one that
        closes the connection first isn't, and nothing else was sent to it.
        """
        with self.lock:
            again = self.introduced
            replay = self.replayed() if again else None
        if replay is not None:
            connection.sendall(replay.initialize.encode())
            heard = next(
                (each for each in lines if answered(read(each)) == replay.ident),
                None,
            )
            if heard is None:
                return False
        with self.lock:
            waited = self.waiting
            sending = [
                *([] if replay is None else replay.after),
                *(each.text for each in waited),
            ]
            connection.sendall("".join(sending).encode())
            self.waiting = []
            self.answering = [
                *self.answering,
                *(each.ident for each in waited if each.ident is not None),
            ]
            self.introduced = again or any(
                each.text == self.initialize for each in waited
            )
            self.connection = connection
        if again:
            self.told(
                line({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            )
        return True

    def replayed(self) -> Replay | None:
        """Return the runtime's introduction for a server reached again, its `initialize` under an id of the bridge's; none where the runtime gave none."""
        match read(self.initialize or ""):
            case {"method": "initialize", **rest}:
                ident = f"{OURS}-{next(self.ids)}"
                return Replay(
                    ident=ident,
                    initialize=line({**rest, "method": "initialize", "id": ident}),
                    after=[] if self.initialized is None else [self.initialized],
                )
            case _:
                return None

    def received(self, text: str) -> None:
        """Carry one line from the server to the runtime, but the answer to the bridge's own request."""
        ident = answered(read(text))
        if isinstance(ident, str) and ident.startswith(OURS):
            return
        if ident is not None:
            with self.lock:
                self.answering = [each for each in self.answering if each != ident]
        self.told(text)

    def lost(self, connection: socket.socket) -> None:
        """Forget a connection the server closed, answering each request it hadn't with an error."""
        connection.close()
        with self.lock:
            self.connection = None
            lost = self.answering
            self.answering = []
        reason = (
            "lup's host service went away while answering this call, so its answer "
            "is lost and it may have been carried out: check before calling it again"
        )
        for ident in lost:
            self.told(failure(ident, reason))

    def expired(self) -> None:
        """Answer with an error each request that waited longer than `patience` for the server."""
        now = time.monotonic()
        with self.lock:
            late = [each for each in self.waiting if now - each.since > self.patience]
            self.waiting = [each for each in self.waiting if each not in late]
        reason = (
            f"lup's host service hasn't answered on {self.path} for "
            f"{self.patience:g} seconds: on the host, `lup-dev host` serves this "
            "room again"
        )
        for each in late:
            if each.ident is not None:
                self.told(failure(each.ident, reason))

    def told(self, text: str) -> None:
        """Write one line to the runtime, at once."""
        self.output.write(text if text.endswith("\n") else f"{text}\n")
        self.output.flush()


def main() -> None:
    """Bridge the runtime on standard input and output to the socket named first."""
    if len(sys.argv) != 2:
        message = "lup's MCP bridge takes one argument: the server's socket"
        raise SystemExit(message)
    Bridge(Path(sys.argv[1]), sys.stdout).run(iter(sys.stdin))


if __name__ == "__main__":
    main()
