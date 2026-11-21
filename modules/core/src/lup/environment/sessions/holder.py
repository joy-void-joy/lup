"""The holder: the process holding one session over its runtime's input and output, and the commands the machine tells it what to do through, each run as `python -I -m lup.environment.sessions.holder <command>` with the machine's own Python.

The machine runs each through its part's `Program` field, so its promises
script them (`lup.sessions.part`):
- `start`, given how to hold a session (`Holds`) on its input, starts
  the holder in a session of its own, which outlives the machine, and answers
  once it listens, where its session stands (`Standing`);
- `serve` is the holder itself: it waits for the room's first program
  to connect on the room's socket, then speaks the runtime's protocol over that
  one connection, closing the socket so nothing else connects, and does what
  it's told on its control socket, which only the machine reaches;
- `order <control>`, given an `Order` on its input, tells a holder to
  start a turn, interrupt one, end its session, or say where it stands, and
  prints where it stands after.

A holder ends once its runtime closes the connection: told to end, it closes the
runtime's input, which a runtime ends on once its turn is through.
"""

import asyncio
import sys
from datetime import timedelta
from typing import Annotated
lazy from pathlib import Path

import typer
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_delay,
    wait_fixed,
)

from lup.environment.running.container import asked, listening
from lup.programs import detached
from lup.runtimes.known import named
from lup.runtimes.runtime import Holding
from lup.sessions.held import Holds, Order, Standing
from lup.types import MutableModel

app = typer.Typer(add_completion=False, no_args_is_help=True)


class Connection(MutableModel, arbitrary_types_allowed=True):
    """The room's connection, which the runtime reads its input from and writes its output to."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


class Holder(MutableModel, arbitrary_types_allowed=True):
    """One session held: how it's held, the runtime's protocol, and its connection once the room has connected."""

    holds: Holds
    holding: Holding
    writer: asyncio.StreamWriter | None = None
    ending: bool = False

    def standing(self) -> Standing:
        """Return where the session stands."""
        return Standing(
            connected=self.writer is not None,
            up=self.holding.up,
            busy=self.holding.busy,
            known_as=self.holding.known_as,
            failed=self.holding.failed,
            ending=self.ending,
        )

    async def wrote(self, lines: list[str]) -> None:
        """Write `lines` on the runtime's input, each with its newline; nothing before the room has connected or once the session is ending."""
        if self.writer is None or self.ending or not lines:
            return
        self.writer.write("".join(f"{line}\n" for line in lines).encode())
        await self.writer.drain()

    async def ordered(self, text: bytes) -> bytes:
        """Do what one message on the control socket says, and answer where the session stands after."""
        order = Order.model_validate_json(text)
        match order.order:
            case "turn":
                await self.wrote(self.holding.turn(order.text))
            case "interrupt":
                await self.wrote(self.holding.interrupt())
            case "end":
                self.ending = True
                if self.writer is not None and self.writer.can_write_eof():
                    self.writer.write_eof()
            case "standing":
                pass
        return self.standing().model_dump_json().encode()


async def held(
    holds: Holds,
    *,
    connecting: timedelta = timedelta(minutes=1),
    limit: int = 64 * 2**20,
) -> int:
    """Hold the session `holds` says until its runtime closes the connection, and return the status to end with: 1 where the room never connected within `connecting`.

    A line past `limit` bytes from the runtime ends the hold, as a runtime gone
    wrong.
    """
    holding = named(holds.runtime).holder.holding(holds.begin, holds.worktree)
    holder = Holder(holds=holds, holding=holding)
    connected: asyncio.Future[Connection] = asyncio.get_running_loop().create_future()

    async def room(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if connected.done():
            writer.close()
            return
        connected.set_result(Connection(reader=reader, writer=writer))

    holds.room.unlink(missing_ok=True)
    waiting = await asyncio.start_unix_server(room, path=holds.room, limit=limit)
    control = await listening(holds.control, holder.ordered, limit=limit)
    try:
        try:
            connection = await asyncio.wait_for(connected, connecting.total_seconds())
        except TimeoutError:
            return 1
        finally:
            waiting.close()
            holds.room.unlink(missing_ok=True)
        holder.writer = connection.writer
        await holder.wrote(holding.opening)
        while True:
            try:
                line = await connection.reader.readline()
            except ValueError:
                return 1
            if not line:
                return 0
            await holder.wrote(holding.read(line.decode(errors="replace")))
    finally:
        control.close()
        holds.control.unlink(missing_ok=True)


@app.command()
def serve(
    holds: Annotated[str, typer.Argument(help="How to hold it, as JSON.")],
) -> None:
    """Hold one session, until its runtime ends."""
    status = asyncio.run(held(Holds.model_validate_json(holds)))
    raise typer.Exit(status)


async def standing_at(control: Path, order: Order) -> Standing:
    """Tell the holder listening on `control` `order`, and return where its session stands after."""
    answer = await asked(control, order.model_dump_json().encode())
    return Standing.model_validate_json(answer)


@app.command()
def start(
    log: Annotated[Path, typer.Option(help="Where the holder writes what it says.")],
    within: Annotated[int, typer.Option(help="Seconds to wait for it to listen.")] = 30,
) -> None:
    """Start a holder, as its input says, in a session of its own, and print where its session stands once it listens."""
    holds = Holds.model_validate_json(sys.stdin.buffer.read())
    detached(
        sys.executable,
        "-I",
        "-m",
        "lup.environment.sessions.holder",
        "serve",
        holds.model_dump_json(),
        log=log,
    )

    async def listened() -> Standing:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(OSError),
            stop=stop_after_delay(within),
            wait=wait_fixed(0.1),
            reraise=True,
        ):
            with attempt:
                return await standing_at(holds.control, Order(order="standing"))
        message = f"no holder listened on {holds.control}"
        raise OSError(message)

    sys.stdout.write(asyncio.run(listened()).model_dump_json() + "\n")


@app.command()
def order(
    control: Annotated[Path, typer.Argument(help="The holder's control socket.")],
) -> None:
    """Tell a holder what its input says to do, and print where its session stands after."""
    told = Order.model_validate_json(sys.stdin.buffer.read())
    sys.stdout.write(asyncio.run(standing_at(control, told)).model_dump_json() + "\n")


def main() -> None:
    """Run the holder's command line."""
    app()


if __name__ == "__main__":
    main()
