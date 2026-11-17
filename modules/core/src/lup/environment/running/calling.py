"""The command line's calls carried through lup's program on the operator's machine, over its socket, as a room's command line and the operator's call it.

Who calls is the program's word, from the socket the calls come in on, so the
command line names nobody (`lup/command_line/README.md`), and nothing of the
project's code runs where the command line does: it lists and parses what the
program offers, the plan of the project asked about (`Offering`), and sends
each call it makes there, one connection each (`lup/running/README.md`, *What
crosses*).
"""

from pathlib import Path
from typing import Annotated, override

from pydantic import Field, TypeAdapter, ValidationError

from lup.command_line.answering import Answerer, Offered
from lup.doors.door import RefusedError
from lup.environment.running.container import REPLIES, asked
from lup.errors import LupError
from lup.running.wire import Call, Declined, Offer, Offering, Reply, read
from lup.types import Model

type OfferReply = Annotated[Offer | Declined, Field(discriminator="kind")]
"""What the program answers a question of what the caller may call: an offer,
or why it refuses."""

OFFERS = TypeAdapter[OfferReply](OfferReply)


class Calling(Model, Answerer):
    """The command line's calls carried through lup's program on the operator's machine, over its socket: who they're by is the socket's word, and what they may call is the plan of the project asked about."""

    socket: Path
    repository: str | None = None
    """The project the calls are for, where they're the operator's: the one
    whose repository the command line runs in. A container's or a room's is
    its own, whatever this says."""

    @override
    async def offered(self) -> Offered:
        """Ask the program who the calls are by and what they may call.

        Raise `RefusedError` where it can't be reached, or refuses.
        """
        asking = Offering(repository=self.repository)
        try:
            reply = read(
                await asked(self.socket, asking.model_dump_json().encode()), OFFERS
            )
        except (OSError, ValueError, LupError, ValidationError) as lost:
            message = f"lup's program on the operator's machine can't be reached at {self.socket}: {lost}"
            raise RefusedError(message) from lost
        match reply:
            case Offer(by=by, plan=plan):
                return Offered(by=by, plan=plan)
            case Declined(rejection=rejection):
                raise RefusedError(rejection.reason)

    @override
    async def answered(self, call: Call) -> Reply:
        """Send `call` to the program, which says who it's by and carries it where it's answered, and return its reply.

        Raise `RefusedError` where the program can't be reached.
        """
        try:
            return read(
                await asked(self.socket, call.model_dump_json().encode()), REPLIES
            )
        except (OSError, ValueError, LupError, ValidationError) as lost:
            message = f"lup's program on the operator's machine can't be reached at {self.socket}: {lost}"
            raise RefusedError(message) from lost

    @override
    async def stopped(self) -> None:
        """Stop nothing: what answers the calls runs on, on the operator's machine."""
