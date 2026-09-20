"""Installed Claude CLI tool enforcement against an inert Messages endpoint."""

import asyncio
import json
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from pydantic import BaseModel

from lup.providers.claude.runtime import ClaudeSessionConfig, create_claude
from lup.sessions.events import turn_request
from lup.sessions.recursion import MAX_RECURSIVE_AGENT_ENV, recursive_agent_allowance
from lup.tools.mcp import lup_tool
from lup.types import JsonObject

pytestmark = pytest.mark.integration


class InertMessages:
    """Record complete inventories and return one scripted native/app call."""

    def __init__(self) -> None:
        self.requests: list[JsonObject] = []
        self.call: JsonObject | None = None
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                request: JsonObject = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                recorder.requests.append(request)
                call = recorder.call
                recorder.call = None
                block: JsonObject = (
                    {**call, "input": {}} if call else {"type": "text", "text": ""}
                )
                delta: JsonObject = (
                    {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(call["input"]),
                    }
                    if call
                    else {"type": "text_delta", "text": "probe complete"}
                )
                events: list[JsonObject] = [
                    {
                        "type": "message_start",
                        "message": {
                            "id": "msg_probe",
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": "claude-opus-5",
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 1, "output_tokens": 0},
                        },
                    },
                    {"type": "content_block_start", "index": 0, "content_block": block},
                    {"type": "content_block_delta", "index": 0, "delta": delta},
                    {"type": "content_block_stop", "index": 0},
                    {
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": "tool_use" if call else "end_turn",
                            "stop_sequence": None,
                        },
                        "usage": {"output_tokens": 1},
                    },
                    {"type": "message_stop"},
                ]
                payload = "".join(
                    f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                    for event in events
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return None

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def endpoint(tmp_path: Path) -> Iterator[InertMessages]:
    if shutil.which("claude") is None:
        pytest.skip("installed Claude is required")
    endpoint = InertMessages()
    endpoint.thread.start()
    try:
        yield endpoint
    finally:
        (tmp_path / "requests.json").write_text(json.dumps(endpoint.requests, indent=2))
        endpoint.server.shutdown()
        endpoint.server.server_close()
        endpoint.thread.join()


def configuration(root: Path) -> ClaudeSessionConfig:
    home = root / "home"
    home.mkdir()
    marker = root / "ambient-mcp-started"
    (root / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"ambient": {"command": "touch", "args": [str(marker)]}}}
        )
    )
    return ClaudeSessionConfig(
        cwd=root,
        model="claude-opus-5",
        environment={"CLAUDE_CONFIG_DIR": str(home)},
        extra_args={"no-session-persistence": None},
    )


def inventory(request: JsonObject) -> list[str]:
    tools = request["tools"] if "tools" in request else []
    assert isinstance(tools, list)
    return [
        tool["name"]
        for tool in tools
        if isinstance(tool, dict) and "name" in tool and isinstance(tool["name"], str)
    ]


async def test_claude_none_isolates_native_and_inherited_tools(
    tmp_path: Path, endpoint: InertMessages
) -> None:
    client = create_claude(
        configuration(tmp_path), base_url=endpoint.url, api_key="inert-probe"
    )
    async with asyncio.timeout(40), client.open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert endpoint.requests
    assert all(inventory(request) == [] for request in endpoint.requests)
    assert not (tmp_path / "ambient-mcp-started").exists()


class ProbeInput(BaseModel):
    value: str


async def test_claude_explicit_effectful_app_tool_runs_under_none(
    tmp_path: Path, endpoint: InertMessages
) -> None:
    marker = tmp_path / "explicit-effect"

    @lup_tool("Write a probe marker.")
    async def record(params: ProbeInput) -> ProbeInput:
        assert recursive_agent_allowance().remaining == 0
        marker.write_text(params.value)
        return params

    endpoint.call = {
        "type": "tool_use",
        "id": "call_probe",
        "name": "mcp__lup-tools__record",
        "input": {"value": "authorized"},
    }
    config = configuration(tmp_path)
    config = config.model_copy(
        update={"environment": {**config.environment, MAX_RECURSIVE_AGENT_ENV: "1"}}
    )
    client = create_claude(
        config,
        base_url=endpoint.url,
        api_key="inert-probe",
        tools=[record],
    )
    async with asyncio.timeout(40), client.open() as handle:
        turn = await handle.session.start(
            turn_request("Call the declared marker tool.")
        )
        await turn.turn.result()
    assert marker.read_text() == "authorized"
    assert all(
        inventory(request) == ["mcp__lup-tools__record"]
        for request in endpoint.requests
    )
    assert not (tmp_path / "ambient-mcp-started").exists()


async def test_claude_typed_submission_remains_available_under_none(
    tmp_path: Path, endpoint: InertMessages
) -> None:
    endpoint.call = {
        "type": "tool_use",
        "id": "call_probe",
        "name": "mcp__lup-output__submit_output",
        "input": {"value": "typed"},
    }
    client = create_claude(
        configuration(tmp_path), base_url=endpoint.url, api_key="inert-probe"
    )
    async with asyncio.timeout(40), client.open() as handle:
        turn = await handle.session.start(
            turn_request("Submit the typed value.", ProbeInput)
        )
        result = await turn.turn.result()
    assert result.output == ProbeInput(value="typed")
    assert all(
        inventory(request) == ["mcp__lup-output__submit_output"]
        for request in endpoint.requests
    )


async def test_claude_fabricated_shell_call_has_no_effect(
    tmp_path: Path, endpoint: InertMessages
) -> None:
    marker = tmp_path / "forbidden-effect"
    endpoint.call = {
        "type": "tool_use",
        "id": "call_probe",
        "name": "Bash",
        "input": {"command": f"touch {marker}"},
    }
    client = create_claude(
        configuration(tmp_path), base_url=endpoint.url, api_key="inert-probe"
    )
    async with asyncio.timeout(40), client.open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert not marker.exists()
    assert all(inventory(request) == [] for request in endpoint.requests)


@pytest.mark.parametrize("tool", ["Read", "Write", "WebFetch", "Bash"])
async def test_claude_exact_native_grants_do_not_widen(
    tmp_path: Path, endpoint: InertMessages, tool: str
) -> None:
    client = create_claude(
        configuration(tmp_path),
        base_url=endpoint.url,
        api_key="inert-probe",
        native_tools=[tool],
    )
    async with asyncio.timeout(40), client.open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert endpoint.requests
    assert all(inventory(request) == [tool] for request in endpoint.requests)
    assert not (tmp_path / "ambient-mcp-started").exists()


async def test_claude_native_delegation_cannot_widen_parent_grant(
    tmp_path: Path, endpoint: InertMessages
) -> None:
    endpoint.call = {
        "type": "tool_use",
        "id": "call_probe",
        "name": "Agent",
        "input": {
            "description": "Inert authority probe",
            "subagent_type": "Explore",
            "prompt": "Return probe complete without tools.",
        },
    }
    client = create_claude(
        configuration(tmp_path),
        base_url=endpoint.url,
        api_key="inert-probe",
        native_tools=["Agent"],
    )
    async with asyncio.timeout(50), client.open() as handle:
        turn = await handle.session.start(
            turn_request("Delegate once to Explore, then report probe complete.")
        )
        await turn.turn.result()
    assert len(endpoint.requests) >= 3
    assert any(inventory(request) == [] for request in endpoint.requests)
    assert all(set(inventory(request)) <= {"Agent"} for request in endpoint.requests)
