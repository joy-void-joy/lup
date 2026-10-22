"""Serving tools over MCP: what's served, an MCP server over it, and one connection served.

What a server serves is a `Toolset`: the specs of its tools, and where each call
goes. One turn's `Toolbox` is one; the tools a launch gives its session are
another. Each is served the same way:
- `tool_server(toolset)` is an MCP server over a toolset, built on `mcp`'s
  low-level `Server` rather than on a helper that checks a call's arguments
  against the schema before its handler runs and answers the refusal itself.
  Every call reaches the toolset with its arguments as the model sent them, so
  lup validates, refuses, counts and records a malformed call like any other.
- `serve(toolset, reader, writer)` serves one MCP session over one connection's
  streams, until the connection closes: newline-delimited JSON-RPC, one message
  a line, as a server's standard input and output carry it, each line read with
  `mcp`'s own message model. So a stdio server that only bridges its standard
  input and output to a socket reaches a toolset served there.

**Results are `content` only,** one text block, never `structuredContent`: a
runtime that shows the model a result's structured content where there is one
drops its content blocks, so a result with both would read differently from one
runtime to the next.

**What a server sends unasked** goes through the connection's `Outbox`: each
`Notice` put is written as a JSON-RPC notification, in order, beside the
session's own messages. A runtime that takes such a notice as a message for its
session says so through the capability it reads, which `serve` declares as
it's given (`experimental`); the host's adapters say which.

**The handshake revisions only.** A client probing for MCP's 2026-07-28
revision first sends `server/discover`, which `serve` answers "method not
found" before `mcp` reads it, so the client falls back to `initialize`. On that
revision a server can't send anything unasked (a runtime's MCP client "doesn't
register a channel server that negotiates protocol revision 2026-07-28":
`docs/field-notes.md`, *Channels*), and `mcp` settles a connection's revision
once, on its first request (`serve_dual_era_loop`), so a handler of its own
couldn't refuse it: an `initialize` after it would be refused in turn. The
bridge's own `initialize` replayed after a restart (`lup.sessions.bridge`) is
on the handshake too.

**`mcp` is imported when a server is first made,** not with this module. A
toolset is named wherever a turn's tools are, the judge's process for each hook
among them, and importing `mcp`'s server took `lup_dev.cli`'s imports from about
0.43 s to 0.89 s (measured with `python -X importtime`).
"""

import asyncio
from abc import ABC, abstractmethod
from importlib.metadata import version
from typing import TYPE_CHECKING

from pydantic import Field, JsonValue, ValidationError

from lup.types import JsonObject, Model, MutableModel

if TYPE_CHECKING:
    from mcp.server import Server, ServerRequestContext
    from mcp.shared._stream_protocols import ReadStream, WriteStream
    from mcp.shared.message import SessionMessage
    from mcp.types import (
        CallToolRequestParams,
        CallToolResult,
        ListToolsResult,
        PaginatedRequestParams,
    )

    from lup.tools.tool import ToolSpec


class Answer(Model):
    """What a tool call returns to the model."""

    text: str
    error: bool = False


class Notice(Model):
    """A notification a server sends unasked: its JSON-RPC method and params."""

    method: str
    params: JsonObject


class Outbox(MutableModel, arbitrary_types_allowed=True):
    """What a server sends unasked on one connection, each notice in the order it's put."""

    notices: asyncio.Queue[Notice] = Field(default_factory=asyncio.Queue[Notice])

    def put(self, notice: Notice) -> None:
        """Send `notice` on the connection, after those put before it."""
        self.notices.put_nowait(notice)


class Toolset(ABC):
    """The tools a server serves, and where each call to them goes."""

    @abstractmethod
    def specs(self) -> list[ToolSpec]:
        """Return what the session is told about each tool."""

    @abstractmethod
    async def call(self, name: str, arguments: JsonValue) -> Answer:
        """Run the model's call to the tool `name`, its arguments as sent, and return what it reads."""


def tool_server(toolset: Toolset, name: str = "lup") -> Server:
    """Return an MCP server named `name`, listing the toolset's tools and handing each call to it.

    A call reaches the toolset with its arguments as the model sent them, valid
    or not: the toolset validates them. Its answer is the result's one text block.
    Each tool is listed with its marks as MCP's annotations, `readOnlyHint` and
    `idempotentHint` (`ToolSpec.reads`, `ToolSpec.idempotent`), both said
    whichever way they stand, which lup's bridge reads off the list to send a
    call again across a restart where the tool allows it.
    """
    from mcp.server import Server
    from mcp.types import (
        CallToolResult,
        ListToolsResult,
        TextContent,
        Tool,
        ToolAnnotations,
    )

    async def listed(
        context: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        del context, params
        tools = [
            Tool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                annotations=ToolAnnotations(
                    read_only_hint=spec.reads, idempotent_hint=spec.idempotent
                ),
            )
            for spec in toolset.specs()
        ]
        return ListToolsResult(tools=tools)

    async def called(
        context: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        del context
        answer = await toolset.call(params.name, params.arguments or {})
        return CallToolResult(
            content=[TextContent(text=answer.text)], is_error=answer.error
        )

    return Server(
        name, version=version("lup"), on_list_tools=listed, on_call_tool=called
    )


def received(line: bytes) -> SessionMessage | ValidationError:
    """Read one line off the connection as a JSON-RPC message, or the error saying why it isn't one.

    A line that isn't a message is handed to the session as the error it is, as
    `mcp`'s own stdio transport does; `mcp` logs it and goes on to the next line.
    """
    from mcp.shared.message import SessionMessage
    from mcp.types import jsonrpc_message_adapter

    try:
        message = jsonrpc_message_adapter.validate_json(line, by_name=False)
    except ValidationError as malformed:
        return malformed
    return SessionMessage(message)


async def listened(
    reader: asyncio.StreamReader,
    incoming: WriteStream[SessionMessage | Exception],
    writer: asyncio.StreamWriter,
) -> None:
    """Hand the session each message read off the connection, until its end; answer a probe for the 2026-07-28 revision "method not found" instead, so the client opens on the handshake."""
    from mcp.shared.message import SessionMessage
    from mcp.types import METHOD_NOT_FOUND, ErrorData, JSONRPCError, JSONRPCRequest

    async with incoming:
        while line := await reader.readline():
            message = received(line)
            match message:
                case SessionMessage(
                    message=JSONRPCRequest(method="server/discover", id=ident)
                ):
                    refusal = JSONRPCError(
                        jsonrpc="2.0",
                        id=ident,
                        error=ErrorData(
                            code=METHOD_NOT_FOUND,
                            message="lup's server speaks the handshake revisions",
                        ),
                    )
                    writer.write(
                        f"{refusal.model_dump_json(by_alias=True, exclude_none=True)}\n".encode()
                    )
                    await writer.drain()
                case _:
                    await incoming.send(message)


async def pushed(outbox: Outbox, writer: asyncio.StreamWriter) -> None:
    """Write each notice put in `outbox` to the connection, one a line, until the other side goes."""
    from mcp.types import JSONRPCNotification

    while True:
        notice = await outbox.notices.get()
        notified = JSONRPCNotification(
            jsonrpc="2.0", method=notice.method, params=notice.params
        )
        writer.write(
            f"{notified.model_dump_json(by_alias=True, exclude_none=True)}\n".encode()
        )
        try:
            await writer.drain()
        except ConnectionError:
            return


async def answered(
    outgoing: ReadStream[SessionMessage | Exception], writer: asyncio.StreamWriter
) -> None:
    """Write each message the session sends to the connection, one a line, until the session ends or the other side goes.

    Once the other side has gone, the session's later messages are dropped, as
    `mcp` drops a write onto a closed transport. One comes every time a call is
    still held when the connection closes: the "Connection closed" error `mcp`
    answers it with.
    """
    from mcp.shared.message import SessionMessage

    async with outgoing:
        async for sent in outgoing:
            match sent:
                case SessionMessage(message=message):
                    line = message.model_dump_json(by_alias=True, exclude_unset=True)
                    writer.write(f"{line}\n".encode())
                    try:
                        await writer.drain()
                    except ConnectionError:
                        return
                case Exception():
                    raise sent


async def serve(
    toolset: Toolset,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    name: str = "lup",
    *,
    experimental: dict[str, JsonObject] | None = None,
    outbox: Outbox | None = None,
) -> None:
    """Serve one MCP session of the toolset over a connection's streams, until the connection closes.

    The session ends when the reader reaches its end; a call still running then
    is cancelled, and what the session would still write to a side that has gone
    is dropped. Closing the connection is the caller's. A message is one line, so
    it must fit the reader's limit (`asyncio.start_unix_server`'s `limit`). Where
    reading breaks, the session ends there, and the reader's error is raised.

    The server says its tools may change (`listChanged`): the bridge a room
    reaches it through tells the runtime they did once it reaches a restarted
    server (`lup.sessions.bridge`), and a runtime acts on that only for a server
    that said so. It declares each of `experimental`'s capabilities, and writes
    each notice put in `outbox` as it comes.
    """
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.shared.memory import create_client_server_memory_streams

    server = tool_server(toolset, name)
    options = server.create_initialization_options(
        NotificationOptions(tools_changed=True), experimental_capabilities=experimental
    )
    async with create_client_server_memory_streams() as (ours, theirs):
        outgoing, incoming = ours
        requests, answers = theirs
        listening = asyncio.create_task(listened(reader, incoming, writer))
        answering = asyncio.create_task(answered(outgoing, writer))
        pushing = asyncio.create_task(pushed(outbox or Outbox(), writer))
        try:
            await server.run(requests, answers, options)
            await listening
            await answering
        finally:
            listening.cancel()
            answering.cancel()
            pushing.cancel()
            await asyncio.wait([listening, answering, pushing])
