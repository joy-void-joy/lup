"""lup's tool server, as a session's runtime starts it in the room: MCP over its standard input and output, each tool a call through the room's socket.

Run as `python -I -m lup.environment.sessions.tools`. It lists the tools the
machine offers the room's session (`Offering`), and carries each call to the
machine (`ToolCalled`), which says who it's by from the room's socket. A call a
subagent makes carries lup's stamp, which the session's hook put in what it's
given (`lup.runtimes.runtime.Stamp`): it's taken out, and sent as the call's
conversation, which the machine vouches for within the room's own session.

It speaks the protocol's older handshake, `initialize`, which both runtimes
open with once a newer one's probe is answered "method not found". Each
request is answered as a task of its own, so a call held a long time, as
`wait_inbox` is, holds no other.
"""

import asyncio
import json
import sys

from pydantic import Field, JsonValue, ValidationError

from lup.doors.door import RefusedError
from lup.environment.running.calling import Calling
from lup.environment.settings import LupSettings
from lup.running.wire import Answered, Declined, ToolCalled
from lup.runtimes.runtime import Stamp
from lup.types import Model, MutableModel


class Request(Model):
    """A JSON-RPC message the runtime sends: a request where it carries an `id`, a notification where it doesn't."""

    id: int | str | None = None
    method: str
    params: JsonValue = None


class Initializing(Model):
    """What the runtime opens the connection with, of which the server reads the protocol's version it asks for."""

    version: str | None = Field(default=None, alias="protocolVersion")


class ToolCall(Model):
    """What a tool's call is given: the tool, by its name, and its arguments."""

    name: str
    arguments: dict[str, JsonValue] = {}


class Server(MutableModel, arbitrary_types_allowed=True):
    """lup's tool server, answering one runtime over MCP: the room's socket it calls through, and what it writes on."""

    answerer: Calling
    stamp: str = Field(default_factory=lambda: Stamp(conversation="").field)
    """The field a subagent's call carries its conversation in, as the
    session's hook stamps it."""
    version: str = "2025-06-18"
    """The protocol's version it answers a runtime that asks for none."""
    writing: asyncio.Lock

    async def wrote(self, message: dict[str, JsonValue]) -> None:
        """Write one message, a line, never two at once."""
        async with self.writing:
            sys.stdout.write(json.dumps(message) + "\n")
            sys.stdout.flush()

    async def answered(self, request: Request) -> None:
        """Answer one request, as a task of its own; a notification gets none."""
        if request.id is None:
            return
        try:
            result = await self.result(request)
        except LookupError as unknown:
            await self.wrote(
                {
                    "jsonrpc": "2.0",
                    "id": request.id,
                    "error": {"code": -32601, "message": str(unknown)},
                }
            )
            return
        await self.wrote({"jsonrpc": "2.0", "id": request.id, "result": result})

    async def result(self, request: Request) -> JsonValue:
        """Return the result of `request`.

        Raise `LookupError` for a method the server doesn't answer.
        """
        match request.method:
            case "initialize":
                try:
                    asked = Initializing.model_validate(request.params).version
                except ValidationError:
                    asked = None
                return {
                    "protocolVersion": asked or self.version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "lup", "version": "0"},
                }
            case "ping":
                return {}
            case "tools/list":
                return {"tools": await self.listed()}
            case "tools/call":
                return await self.called(request.params)
            case method:
                message = f"lup's tool server doesn't answer `{method}`"
                raise LookupError(message)

    async def listed(self) -> list[JsonValue]:
        """List the tools the machine offers the room's session, as MCP describes a tool."""
        offered = await self.answerer.offered()
        return [
            {
                "name": each.name,
                "description": each.description,
                "inputSchema": each.input_schema,
                "annotations": {
                    "readOnlyHint": each.reads,
                    "idempotentHint": each.idempotent,
                },
            }
            for each in offered.plan.tools
        ]

    async def called(self, params: JsonValue) -> JsonValue:
        """Carry one call to the machine, and return its result as MCP's: the answer as text, or the refusal, marked an error."""
        try:
            call = ToolCall.model_validate(params)
        except ValidationError as wrong:
            return said(f"lup can't read this call: {wrong}", failed=True)
        arguments = dict(call.arguments)
        conversation = arguments.pop(self.stamp, None)
        tool = ToolCalled(
            tool=call.name,
            given=arguments,
            conversation=conversation if isinstance(conversation, str) else None,
        )
        try:
            reply = await self.answerer.answered(tool)
        except RefusedError as lost:
            return said(str(lost), failed=True)
        match reply:
            case Answered(output=str() as text):
                return said(text)
            case Answered(output=output):
                return said(json.dumps(output))
            case Declined(rejection=rejection):
                return said(rejection.reason, failed=True)


def said(text: str, *, failed: bool = False) -> JsonValue:
    """Return `text` as a tool's result, marked an error where it `failed`."""
    return {"content": [{"type": "text", "text": text}], "isError": failed}


class Reading(MutableModel, arbitrary_types_allowed=True):
    """The requests under way, kept so none is collected before it's answered."""

    tasks: list[asyncio.Task[None]] = []

    def kept(self, task: asyncio.Task[None]) -> None:
        """Keep `task` until it's done."""
        self.tasks = [*[each for each in self.tasks if not each.done()], task]


async def served() -> None:
    """Answer the runtime on this program's input and output until it closes the input."""
    calling = LupSettings().lup_calling
    if calling is None:
        message = "lup's tool server runs in a session's room, whose socket `LUP_CALLING` names"
        raise RefusedError(message)
    server = Server(answerer=Calling(socket=calling), writing=asyncio.Lock())
    reading = Reading()
    loop = asyncio.get_running_loop()
    while line := await loop.run_in_executor(None, sys.stdin.buffer.readline):
        try:
            request = Request.model_validate_json(line)
        except ValidationError:
            continue
        reading.kept(asyncio.create_task(server.answered(request)))
    await asyncio.gather(*reading.tasks)


if __name__ == "__main__":
    asyncio.run(served())
