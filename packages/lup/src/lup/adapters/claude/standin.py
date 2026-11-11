"""A stand-in for Claude Code held over its stream-json input and output, answered in-process, for tests: no process, no model.

    standin = await StandIn.connected(session="s-1", arguments=command, place=socket)
    contained: Contained = standin     # what a held run of the engine returns
    piped = await StandIn.paired(session="s-1")   # or held over a socket pair

It speaks the wire `lup.adapters.claude.held` does, as Claude Code 2.1.319 was
measured to (`docs/field-notes.md`, *A session held with no terminal*), on one
socket for its input and output, as a held room's first program gives it
(`lup.sessions.connected`): each user turn starts a turn, `system` `init` with
the session's id, its text kept in `prompts`, and ends it with a `result` at
once, or, with `lingering`, once an interrupt ends it, answered by its request's
id and ended `aborted_tools`. Its input's end ends it, a turn under way finished
first, what it writes after still read.
"""

import asyncio
import json
import socket
from typing import TYPE_CHECKING, Self, override

from pydantic import Field, JsonValue, TypeAdapter

from lup.adapters.claude.held import Asking, Kind, UserTurn
from lup.rooms.engine import Contained, Ending, Piped, Pipes
from lup.types import MutableModel

if TYPE_CHECKING:
    from pathlib import Path


class StandIn(MutableModel, Contained, arbitrary_types_allowed=True):
    """Claude Code's held wire, answered in-process."""

    session: str
    """The session's id, which each turn's start carries."""
    arguments: list[str] = []
    """The command it was started as."""
    lingering: bool = False
    """Whether each turn runs until an interrupt ends it, as a long call would."""
    prompts: list[str] = []
    """Each user turn's text, in order."""
    interrupts: int = 0
    """How many interrupts it answered."""
    status: int | None = None
    """How it ended; none while it runs."""
    task: asyncio.Task[None] | None = None
    turning: bool = False
    ended: asyncio.Event = Field(default_factory=asyncio.Event)

    @classmethod
    async def connected(
        cls, session: str, arguments: list[str], place: Path, *, lingering: bool = False
    ) -> Self:
        """Start it on the running event loop, as `arguments` were run, connected to the socket at `place` as a held room's first program connects."""
        heard, saying = await asyncio.open_unix_connection(str(place))
        standin = cls(session=session, arguments=arguments, lingering=lingering)
        standin.task = asyncio.create_task(standin.answering(heard, saying))
        return standin

    @classmethod
    async def paired(cls, session: str, *, lingering: bool = False) -> Piped:
        """Start it on the running event loop over one end of a socket pair, and return it held over the other, as a room's held session is."""
        ours, theirs = socket.socketpair()
        reading, writing = await asyncio.open_unix_connection(sock=ours)
        heard, saying = await asyncio.open_unix_connection(sock=theirs)
        standin = cls(session=session, lingering=lingering)
        standin.task = asyncio.create_task(standin.answering(heard, saying))
        return Piped(run=standin, pipes=Pipes(input=writing, output=reading))

    @override
    async def waited(self) -> int:
        await self.ended.wait()
        return self.status or 0

    @override
    def signalled(self, ending: Ending) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
        if self.status is None:
            self.status = 143 if ending == "asked" else 137
            self.ended.set()

    async def answering(
        self, heard: asyncio.StreamReader, saying: asyncio.StreamWriter
    ) -> None:
        """Answer each line on its input until it ends, then finish a turn under way and end."""

        async def said(line: dict[str, JsonValue]) -> None:
            saying.write(f"{json.dumps(line)}\n".encode())
            await saying.drain()

        async def ending(subtype: str, reason: str, *, error: bool) -> None:
            self.turning = False
            await said(
                {
                    "type": "result",
                    "subtype": subtype,
                    "is_error": error,
                    "terminal_reason": reason,
                    "session_id": self.session,
                }
            )

        try:
            while line := await heard.readline():
                raw = TypeAdapter[JsonValue](JsonValue).validate_json(line)
                match Kind.model_validate(raw).type:
                    case "user":
                        turn = UserTurn.model_validate(raw)
                        self.prompts.append(turn.message.content)
                        if not self.turning:
                            self.turning = True
                            await said(
                                {
                                    "type": "system",
                                    "subtype": "init",
                                    "session_id": self.session,
                                }
                            )
                        if not self.lingering:
                            await ending("success", "completed", error=False)
                    case "control_request":
                        asked = Asking.model_validate(raw)
                        self.interrupts += 1
                        await said(
                            {
                                "type": "control_response",
                                "response": {
                                    "subtype": "success",
                                    "request_id": asked.request_id,
                                    "response": {"still_queued": []},
                                },
                            }
                        )
                        if self.turning:
                            await ending(
                                "error_during_execution", "aborted_tools", error=True
                            )
                    case _:
                        pass
            if self.turning:
                await ending("success", "completed", error=False)
        finally:
            saying.close()
            if self.status is None:
                self.status = 0
            self.ended.set()
