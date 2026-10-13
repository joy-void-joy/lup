"""Serving a toolset over MCP: one connection over a socket pair, to `mcp`'s own client.

The client's end is carried as a stdio bridge would carry it: newline-delimited
JSON-RPC, one message a line. No process, no network, no clock: each wait is on
an event the toolset sets.
"""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from mcp import Client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import TextContent, jsonrpc_message_adapter
from pydantic import BaseModel, JsonValue

from lup.sessions.submission import Toolbox
from lup.tools import lup_tool
from lup.tools.serving import Answer, Toolset, serve
from lup.tools.tool import ToolSpec

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from mcp.client._transport import TransportStreams

ECHO = ToolSpec(
    name="echo",
    description="Say back what you're given.\n\nWord for word, as JSON.",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
)


class Recording(Toolset):
    """Answers each call with what it was given, and keeps it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, JsonValue]] = []

    def specs(self) -> list[ToolSpec]:
        return [ECHO]

    async def call(self, name: str, arguments: JsonValue) -> Answer:
        self.calls.append((name, arguments))
        return Answer(text=f"{name}: {json.dumps(arguments)}")


class Holding(Toolset):
    """Holds every call until it's cancelled, saying when it started and when it was cancelled."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = False

    def specs(self) -> list[ToolSpec]:
        return [ECHO]

    async def call(self, name: str, arguments: JsonValue) -> Answer:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return Answer(text="never")


@asynccontextmanager
async def bridged(end: socket.socket) -> AsyncGenerator[TransportStreams]:
    """Carry a client's messages over its end of the socket pair, one JSON-RPC message a line."""
    reader, writer = await asyncio.open_unix_connection(sock=end)
    async with create_client_server_memory_streams() as (client, ours):
        sent, received = ours

        async def reading() -> None:
            async with received:
                while line := await reader.readline():
                    message = jsonrpc_message_adapter.validate_json(line, by_name=False)
                    await received.send(SessionMessage(message))

        async def writing() -> None:
            async with sent:
                async for item in sent:
                    assert isinstance(item, SessionMessage)
                    line = item.message.model_dump_json(
                        by_alias=True, exclude_unset=True
                    )
                    writer.write(f"{line}\n".encode())
                    await writer.drain()

        tasks = [asyncio.create_task(reading()), asyncio.create_task(writing())]
        try:
            yield client
        finally:
            writer.close()
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)


async def through[T](
    toolset: Toolset, mode: str, use: Callable[[Client], Awaitable[T]]
) -> T:
    """Serve the toolset on one end of a socket pair, and use it through `mcp`'s client on the other."""
    served, client_end = socket.socketpair()
    reader, writer = await asyncio.open_unix_connection(sock=served)
    serving = asyncio.create_task(serve(toolset, reader, writer))
    async with Client(bridged(client_end), mode=mode) as client:
        result = await use(client)
    await serving
    writer.close()
    return result


ERAS = pytest.mark.parametrize("mode", ["legacy", "auto"])
"""The handshake era the runtimes speak, and the newer one a client may open with."""


@ERAS
def test_the_toolset_s_tools_are_listed(mode: str) -> None:
    async def listed(client: Client) -> Any:
        return (await client.list_tools()).tools

    [tool] = asyncio.run(through(Recording(), mode, listed))

    assert tool.name == "echo"
    assert tool.description == "Say back what you're given.\n\nWord for word, as JSON."
    assert tool.input_schema == ECHO.input_schema


@ERAS
def test_a_call_reaches_the_toolset_with_its_arguments_and_answers_as_content_only(
    mode: str,
) -> None:
    toolset = Recording()

    async def called(client: Client) -> Any:
        return await client.call_tool("echo", {"text": "hi"})

    result = asyncio.run(through(toolset, mode, called))

    assert toolset.calls == [("echo", {"text": "hi"})]
    assert result.content == [TextContent(text='echo: {"text": "hi"}')]
    assert result.structured_content is None
    assert not result.is_error


class Query(BaseModel):
    city: str


class Weather(BaseModel):
    summary: str


@lup_tool
async def weather(query: Query) -> Weather:
    """Look up today's weather in a city."""
    return Weather(summary=f"sunny in {query.city}")


def test_a_turn_s_toolbox_is_served_the_same_way_and_its_tool_refuses_an_invalid_call() -> (
    None
):
    toolbox = Toolbox(tools=[weather], attempts=3)

    async def called(client: Client) -> Any:
        refused = await client.call_tool("weather", {"town": "Paris"})
        accepted = await client.call_tool("weather", {"city": "Paris"})
        return refused, accepted

    refused, accepted = asyncio.run(through(toolbox, "legacy", called))

    assert refused.is_error
    [refusal] = refused.content
    assert isinstance(refusal, TextContent)
    assert refusal.text.startswith("Refused: 1 validation error")
    assert refused.structured_content is None
    assert accepted.content == [TextContent(text='{"summary":"sunny in Paris"}')]
    assert [call.tool for call in toolbox.calls] == ["weather", "weather"]


async def said(writer: asyncio.StreamWriter, message: dict[str, JsonValue]) -> None:
    writer.write(f"{json.dumps(message)}\n".encode())
    await writer.drain()


INITIALIZE: dict[str, JsonValue] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "bridge", "version": "0"},
    },
}


def test_each_answer_is_one_line_of_json_rpc_and_the_session_ends_with_the_connection() -> (
    None
):
    async def raw() -> tuple[JsonValue, bytes]:
        served, client_end = socket.socketpair()
        reader, writer = await asyncio.open_unix_connection(sock=served)
        serving = asyncio.create_task(serve(Recording(), reader, writer, name="tools"))
        theirs, ours = await asyncio.open_unix_connection(sock=client_end)
        await said(ours, INITIALIZE)
        answer = json.loads(await theirs.readline())
        ours.close()
        await serving
        writer.close()
        return answer, await theirs.read()

    answer, rest = asyncio.run(raw())

    assert isinstance(answer, dict)
    assert answer["id"] == 1
    result = answer["result"]
    assert isinstance(result, dict)
    server = result["serverInfo"]
    assert isinstance(server, dict)
    assert server["name"] == "tools"
    assert rest == b""


def test_a_line_that_isn_t_a_message_is_passed_over() -> None:
    async def raw() -> JsonValue:
        served, client_end = socket.socketpair()
        reader, writer = await asyncio.open_unix_connection(sock=served)
        serving = asyncio.create_task(serve(Recording(), reader, writer))
        theirs, ours = await asyncio.open_unix_connection(sock=client_end)
        ours.write(b"not json-rpc\n")
        await said(ours, INITIALIZE)
        answer = json.loads(await theirs.readline())
        ours.close()
        await serving
        writer.close()
        return answer

    answer = asyncio.run(raw())

    assert isinstance(answer, dict)
    assert answer["id"] == 1
    assert "result" in answer


def test_a_call_still_held_when_the_connection_closes_is_cancelled() -> None:
    toolset = Holding()

    async def held() -> None:
        served, client_end = socket.socketpair()
        reader, writer = await asyncio.open_unix_connection(sock=served)
        serving = asyncio.create_task(serve(toolset, reader, writer))
        theirs, ours = await asyncio.open_unix_connection(sock=client_end)
        await said(ours, INITIALIZE)
        await theirs.readline()
        await said(ours, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        call: dict[str, JsonValue] = {"name": "echo", "arguments": {}}
        await said(
            ours, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": call}
        )
        await toolset.entered.wait()
        ours.close()
        await serving
        writer.close()

    asyncio.run(held())

    assert toolset.cancelled
