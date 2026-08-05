"""Codex app-server JSON-RPC routing under a live reader, no process attached.

Every Codex turn — and every native approval request the policy layer
answers — rides this transport. These tests drive the wire queues
directly: responses must resolve exactly their pending request, error
envelopes must surface as :class:`AppServerError`, server-initiated
requests must always receive a reply (success, failure, or
no-handler-installed), notifications must reach the installed handler,
and a disconnect must fail every pending future rather than hang them.
"""

import asyncio
import json

from pathlib import Path

import pytest

from lup.adapters.codex.app_server import (
    AppServerError,
    CodexAppServer,
    RpcMessage,
    RpcNotification,
)
from lup.types import JsonObject


def sent_lines(server: CodexAppServer) -> list[JsonObject]:
    """Decode every JSON-RPC line the server wrote to its stdin queue."""
    lines: list[JsonObject] = []  # lup: ignore[empty-collection] — queue drain
    while not server.input.empty():
        line = server.input.get_nowait()
        if line is not None:
            lines.append(json.loads(line))
    return lines


async def test_response_resolves_exactly_its_pending_request() -> None:
    server = CodexAppServer(Path("codex"))
    reader = asyncio.create_task(server.read_messages())
    first = asyncio.create_task(server.request("thread/start", {}))
    second = asyncio.create_task(server.request("thread/resume", {}))
    await asyncio.sleep(0)

    server.output.put_nowait(json.dumps({"id": 2, "result": {"thread": "resumed"}}))
    server.output.put_nowait(json.dumps({"id": 1, "result": {"thread": "started"}}))

    assert await first == {"thread": "started"}
    assert await second == {"thread": "resumed"}
    assert server.pending == {}
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_error_envelope_surfaces_as_typed_app_server_error() -> None:
    server = CodexAppServer(Path("codex"))
    reader = asyncio.create_task(server.read_messages())
    request = asyncio.create_task(server.request("turn/start", {}))
    await asyncio.sleep(0)

    server.output.put_nowait(
        json.dumps({"id": 1, "error": {"code": -32600, "message": "bad turn"}})
    )

    with pytest.raises(AppServerError) as raised:
        await request
    assert raised.value.error.code == -32600
    assert "bad turn" in str(raised.value)
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_server_request_round_trips_through_the_installed_handler() -> None:
    server = CodexAppServer(Path("codex"))
    seen: list[JsonObject] = []

    async def approve(message: RpcMessage) -> str:
        seen.append(message.params)
        return "approved"

    server.server_request_handler = approve
    reader = asyncio.create_task(server.read_messages())
    server.output.put_nowait(
        json.dumps(
            {"id": 9, "method": "execCommandApproval", "params": {"command": "ls"}}
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert seen == [{"command": "ls"}]
    assert sent_lines(server) == [{"id": 9, "result": "approved"}]
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_server_request_without_handler_is_refused_not_dropped() -> None:
    server = CodexAppServer(Path("codex"))
    reader = asyncio.create_task(server.read_messages())
    server.output.put_nowait(
        json.dumps({"id": 4, "method": "applyPatchApproval", "params": {}})
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    replies = sent_lines(server)
    assert [reply["id"] for reply in replies] == [4]
    error = replies[0]["error"]
    assert isinstance(error, dict) and error["code"] == -32601
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_raising_handler_returns_failure_so_the_native_side_never_hangs() -> None:
    server = CodexAppServer(Path("codex"))

    async def explode(message: RpcMessage) -> str:
        del message
        raise RuntimeError("policy backend offline")

    server.server_request_handler = explode
    reader = asyncio.create_task(server.read_messages())
    server.output.put_nowait(
        json.dumps({"id": 5, "method": "execCommandApproval", "params": {}})
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    replies = sent_lines(server)
    assert [reply["id"] for reply in replies] == [5]
    error = replies[0]["error"]
    assert isinstance(error, dict) and error["code"] == -32000
    assert error["message"] == "policy backend offline"
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_notifications_reach_the_installed_handler_in_order() -> None:
    server = CodexAppServer(Path("codex"))
    received: list[RpcNotification] = []
    server.notification_handler = received.append
    reader = asyncio.create_task(server.read_messages())

    server.output.put_nowait(
        json.dumps({"method": "turn/started", "params": {"turn": "t1"}})
    )
    server.output.put_nowait(
        json.dumps({"method": "turn/completed", "params": {"turn": "t1"}})
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert [item.method for item in received] == ["turn/started", "turn/completed"]
    assert received[0].params == {"turn": "t1"}
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader


async def test_disconnect_fails_pending_requests_and_notifies_the_handler() -> None:
    server = CodexAppServer(Path("codex"))
    disconnects: list[Exception] = []
    server.disconnect_handler = disconnects.append
    reader = asyncio.create_task(server.read_messages())
    request = asyncio.create_task(server.request("turn/start", {}))
    await asyncio.sleep(0)

    server.output.put_nowait(None)

    with pytest.raises(RuntimeError, match="exited before completing"):
        await request
    with pytest.raises(RuntimeError):
        await reader
    assert server.pending == {}
    assert len(disconnects) == 1


async def test_request_after_idle_disconnect_fails_fast_instead_of_hanging() -> None:
    """A death with no request in flight must still fail the next request.

    The resolver sits idle between turns; if the app-server dies there, a
    later ``request`` would otherwise enqueue into a dead stdin queue and
    await a future nobody resolves.
    """
    server = CodexAppServer(Path("codex"))
    server.exit_error = RuntimeError("Codex app-server exited with status 1: boom")
    reader = asyncio.create_task(server.read_messages())
    await asyncio.sleep(0)

    server.output.put_nowait(None)

    with pytest.raises(RuntimeError, match="boom"):
        await reader
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(server.request("thread/start", {}), timeout=1)
