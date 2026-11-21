"""The command a session's runtime runs at each of its hooks, in the room: it carries the hook to the machine and prints the machine's answer, as the runtime reads one.

Run as `python -I -m lup.environment.sessions.hook <hook>`, the hook's payload on
its input. It reads nothing of the payload: the machine reads it with the
session's runtime (`Held.hooked`), and answers what to print and the status to
end with. The room's socket says which session it's of (`LUP_CALLING`). Where
the machine can't be reached, as while it restarts, it tries again for a while,
then ends with status 1, which a runtime takes as a hook that failed, the call
going on.
"""

import asyncio
import sys
from datetime import timedelta
from typing import Annotated

import typer
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_delay,
    wait_fixed,
)

from lup.doors.door import RefusedError
from lup.environment.running.calling import Calling
from lup.environment.settings import LupSettings
from lup.running.wire import Answered, Declined, Reply, ServiceCalled
from lup.runtimes.runtime import Spoken
from lup.sessions.said import Hooked

app = typer.Typer(add_completion=False)


async def carried(call: ServiceCalled, within: timedelta) -> Reply:
    """Send `call` to the machine through the room's socket, trying again while it can't be reached, for `within` at most.

    Raise `RefusedError` where it still can't be reached.
    """
    calling = LupSettings().lup_calling
    if calling is None:
        message = "a session's hook runs in its room, whose socket `LUP_CALLING` names"
        raise RefusedError(message)
    answerer = Calling(socket=calling)
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(RefusedError),
        stop=stop_after_delay(within.total_seconds()),
        wait=wait_fixed(0.5),
        reraise=True,
    ):
        with attempt:
            return await answerer.answered(call)
    message = "the machine never answered"
    raise RefusedError(message)


@app.command()
def hook(
    name: Annotated[str, typer.Argument(help="The hook, as the runtime names it.")],
    within: Annotated[
        int, typer.Option(help="Seconds to keep trying the machine.")
    ] = 60,
) -> None:
    """Carry the hook on this program's input to the machine, and print its answer."""
    payload = sys.stdin.buffer.read().decode(errors="replace")
    call = ServiceCalled(
        service="hooked",
        given=Hooked(hook=name, payload=payload).model_dump(mode="json"),
    )
    try:
        reply = asyncio.run(carried(call, timedelta(seconds=within)))
    except RefusedError as lost:
        sys.stderr.write(f"lup: {lost}\n")
        raise typer.Exit(1) from lost
    match reply:
        case Answered(output=output):
            spoken = Spoken.model_validate(output)
            sys.stdout.write(spoken.output)
            raise typer.Exit(spoken.status)
        case Declined(rejection=rejection):
            sys.stderr.write(f"lup: {rejection.reason}\n")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
