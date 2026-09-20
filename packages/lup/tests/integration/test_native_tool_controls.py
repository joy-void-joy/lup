"""Installed Codex controls, exercised against an inert loopback Responses server."""

import asyncio
import json
import shutil
import shlex
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import tomlkit
from pydantic import BaseModel

from lup.providers.codex.runtime import (
    CodexSchemaRebindingError,
    CodexMcpServerConfig,
    CodexSessionConfig,
    create_codex,
)
from lup.providers.codex.home import CodexWorktreeHomeStore
from lup.providers.codex.app_server import CodexAppServer
from lup.sessions.events import SessionId, turn_request
from lup.sessions.recursion import MAX_RECURSIVE_AGENT_ENV, recursive_agent_allowance
from lup.tools.mcp import lup_tool
from lup.tools.native import NativeTools, NativeToolGroup
from lup.types import JsonObject, JsonValue

pytestmark = pytest.mark.integration


class InertResponses:
    """Record complete request inventories and return a scripted tool call once."""

    def __init__(self) -> None:
        self.requests: list[JsonObject] = []
        self.call: JsonObject | None = None
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"models": []}')

            def do_POST(self) -> None:
                request: JsonObject = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                recorder.requests.append(request)
                output: list[JsonValue] = []
                if recorder.call is not None:
                    output.append(recorder.call)
                    recorder.call = None
                else:
                    output.append(
                        {
                            "id": "msg_probe",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "probe complete",
                                    "annotations": [],
                                }
                            ],
                        }
                    )
                response: JsonObject = {
                    "id": "resp_probe",
                    "object": "response",
                    "status": "completed",
                    "output": output,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                }
                events: list[JsonObject] = [
                    {
                        "type": "response.output_item.done",
                        "output_index": index,
                        "item": item,
                    }
                    for index, item in enumerate(output)
                ]
                events.append({"type": "response.completed", "response": response})
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
        return f"http://127.0.0.1:{self.server.server_port}/v1"


@pytest.fixture
def endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[InertResponses]:
    if shutil.which("codex") is None:
        pytest.skip("installed Codex is required")
    endpoint = InertResponses()
    close = CodexAppServer.close
    stderr: list[str] = []

    async def capture_stderr(server: CodexAppServer) -> None:
        await close(server)
        stderr.append("".join(server.stderr))
        (tmp_path / "app-server-stderr.json").write_text(json.dumps(stderr))

    monkeypatch.setattr(CodexAppServer, "close", capture_stderr)
    endpoint.thread.start()
    try:
        yield endpoint
    finally:
        (tmp_path / "requests.json").write_text(json.dumps(endpoint.requests, indent=2))
        endpoint.server.shutdown()
        endpoint.server.server_close()
        endpoint.thread.join()


def configuration(
    root: Path, endpoint: InertResponses, native_tools: NativeTools = None
) -> CodexSessionConfig:
    """No credentials, public network endpoints, or user home enter this process."""
    home = root / "home"
    home.mkdir(exist_ok=True)
    marker = root / "ambient-mcp-started"
    config = {
        "model": "gpt-6-astra",
        "model_provider": "lup_probe",
        "model_providers": {
            "lup_probe": {
                "name": "Loopback probe",
                "base_url": endpoint.url,
                "wire_api": "responses",
                "requires_openai_auth": False,
                "supports_websockets": False,
                "request_max_retries": 0,
                "stream_max_retries": 0,
                "supports_standalone_web_search": True,
            }
        },
        "features": {"enable_request_compression": False},
        "mcp_servers": {"ambient": {"command": "touch", "args": [str(marker)]}},
    }
    (home / "config.toml").write_text(tomlkit.dumps(config))
    return CodexSessionConfig(
        cwd=root,
        model="gpt-6-astra",
        model_provider="lup_probe",
        environment={"CODEX_HOME": str(home)},
        native_tools=native_tools,
    )


def inventory(request: JsonObject) -> list[str]:
    def names_in(value: JsonValue) -> list[str]:
        if isinstance(value, list):
            return [name for item in value for name in names_in(item)]
        if isinstance(value, dict):
            if "tools" in value:
                children = names_in(value["tools"])
                if "name" in value:
                    return [f"{value['name']}.{name}" for name in children]
                return children
            if "name" in value and isinstance(value["name"], str):
                return [value["name"]]
            if "type" in value and isinstance(value["type"], str):
                return [value["type"]]
        return []

    names: list[str] = []
    for tool in (
        request["tools"]
        if "tools" in request and isinstance(request["tools"], list)
        else []
    ):
        if isinstance(tool, dict):
            if "name" in tool and isinstance(tool["name"], str):
                names.append(tool["name"])
            elif "type" in tool and isinstance(tool["type"], str):
                names.append(tool["type"])
    for item in (
        request["input"]
        if "input" in request and isinstance(request["input"], list)
        else []
    ):
        if (
            isinstance(item, dict)
            and "type" in item
            and item["type"] == "additional_tools"
        ):
            names.extend(names_in(item))
    return names


async def test_codex_none_has_no_inventory_or_ambient_server(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    factory = create_codex(configuration(tmp_path, endpoint))
    async with asyncio.timeout(40), factory.open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert endpoint.requests
    assert all(inventory(request) == [] for request in endpoint.requests)
    assert not (tmp_path / "ambient-mcp-started").exists()


class ProbeInput(BaseModel):
    value: str


async def test_codex_explicit_native_grant_keeps_declared_policy(
    tmp_path: Path, endpoint: InertResponses, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configuration(tmp_path, endpoint, [NativeToolGroup.SHELL])
    source = tmp_path / ".codex" / "plugins" / "probe"
    manifest = source / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"name": "probe", "version": "0.0.1", "hooks": "./hooks.json"})
    )
    marker = tmp_path / "policy-called"
    script = source / "deny.sh"
    script.write_text(
        f'#!/bin/sh\nprintf called > {shlex.quote(str(marker))}\nprintf \'%s\' \'{{"hookSpecificOutput":{{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"inert policy refused native call"}}}}\'\n'
    )
    (source / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'sh "${PLUGIN_ROOT}/deny.sh"',
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "probe-marketplace",
                "plugins": [
                    {
                        "name": "probe",
                        "source": {"source": "local", "path": "./.codex/plugins/probe"},
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(CodexWorktreeHomeStore, "derived", lambda self, home: True)
    endpoint.call = {
        "id": "fc_probe",
        "type": "function_call",
        "call_id": "call_probe",
        "name": "exec_command",
        "arguments": '{"cmd":"printf forbidden-native-output"}',
    }
    async with asyncio.timeout(60), create_codex(config).open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert marker.read_text() == "called"
    assert "inert policy refused native call" in json.dumps(endpoint.requests)
    assert not (tmp_path / "ambient-mcp-started").exists()


async def test_codex_explicit_app_tool_executes_under_none(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    marker = tmp_path / "explicit-effect"

    @lup_tool("Write a probe marker.")
    async def record(params: ProbeInput) -> ProbeInput:
        assert recursive_agent_allowance().remaining == 0
        marker.write_text(params.value)
        return params

    endpoint.call = {
        "id": "fc_probe",
        "type": "function_call",
        "call_id": "call_probe",
        "name": "lup_app_record",
        "arguments": '{"value":"authorized"}',
    }
    config = configuration(tmp_path, endpoint)
    config = config.model_copy(
        update={"environment": {**config.environment, MAX_RECURSIVE_AGENT_ENV: "1"}}
    )
    factory = create_codex(config, tools=[record])
    async with asyncio.timeout(40), factory.open() as handle:
        turn = await handle.session.start(
            turn_request("Call the declared marker tool.")
        )
        await turn.turn.result()
    assert marker.read_text() == "authorized"
    assert all(
        inventory(request) == ["functions.lup_app_record"]
        for request in endpoint.requests
    )
    assert not (tmp_path / "ambient-mcp-started").exists()


async def test_codex_fork_preserves_explicit_app_tools_under_none(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    marker = tmp_path / "fork-effect"

    @lup_tool("Write the fork probe marker.")
    async def record(params: ProbeInput) -> ProbeInput:
        marker.write_text(params.value)
        return params

    async with (
        asyncio.timeout(40),
        create_codex(
            configuration(tmp_path, endpoint), tools=[record]
        ).open() as handle,
    ):
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
        assert handle.fork is not None
        async with handle.fork.fork() as fork:
            endpoint.call = {
                "id": "fc_probe",
                "type": "function_call",
                "call_id": "call_probe",
                "name": "lup_app_record",
                "arguments": '{"value":"forked"}',
            }
            turn = await fork.session.start(
                turn_request("Call the declared marker tool.")
            )
            await turn.turn.result()
    assert marker.read_text() == "forked"
    assert all(
        inventory(request) == ["functions.lup_app_record"]
        for request in endpoint.requests
    )


async def test_codex_typed_submission_remains_available_under_none(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    endpoint.call = {
        "id": "fc_probe",
        "type": "function_call",
        "call_id": "call_probe",
        "name": "submit_output",
        "arguments": '{"value":"typed"}',
    }
    async with (
        asyncio.timeout(40),
        create_codex(configuration(tmp_path, endpoint)).open() as handle,
    ):
        turn = await handle.session.start(
            turn_request("Submit the typed value.", ProbeInput)
        )
        result = await turn.turn.result()
    assert result.output == ProbeInput(value="typed")
    assert all(
        inventory(request) == ["functions.submit_output"]
        for request in endpoint.requests
    )


async def test_codex_fabricated_shell_does_not_execute(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    marker = tmp_path / "forbidden-effect"
    endpoint.call = {
        "id": "fc_probe",
        "type": "function_call",
        "call_id": "call_probe",
        "name": "exec_command",
        "arguments": json.dumps({"cmd": f"touch {marker}"}),
    }
    factory = create_codex(configuration(tmp_path, endpoint))
    async with asyncio.timeout(40), factory.open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert not marker.exists()
    assert all(inventory(request) == [] for request in endpoint.requests)


async def test_codex_resume_refuses_stale_dynamic_tools(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    @lup_tool("Echo a probe value.")
    async def echo(params: ProbeInput) -> ProbeInput:
        return params

    config = configuration(tmp_path, endpoint)
    async with asyncio.timeout(40), create_codex(config, tools=[echo]).open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        result = await turn.turn.result()
        session_id = (
            result.identifiers.session if result.identifiers is not None else None
        )
    assert isinstance(session_id, SessionId)
    assert inventory(endpoint.requests[-1]) == ["functions.lup_app_echo"]
    async with asyncio.timeout(40), create_codex(config).open(session_id) as handle:
        with pytest.raises(
            CodexSchemaRebindingError, match="persisted application/output"
        ):
            await handle.session.start(turn_request("Return probe complete."))
    assert len(endpoint.requests) == 1


async def test_codex_native_grants_can_be_narrowed_on_resume(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    config = configuration(tmp_path, endpoint, [NativeToolGroup.SHELL])
    async with asyncio.timeout(40), create_codex(config).open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        result = await turn.turn.result()
        assert result.identifiers is not None
        session = result.identifiers.session
    marker = tmp_path / "forbidden-effect"
    endpoint.call = {
        "id": "fc_probe",
        "type": "function_call",
        "call_id": "call_probe",
        "name": "exec_command",
        "arguments": json.dumps({"cmd": f"touch {marker}"}),
    }
    async with (
        asyncio.timeout(40),
        create_codex(config, native_tools=None).open(session) as handle,
    ):
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert "functions.exec_command" in inventory(endpoint.requests[0])
    assert all(inventory(request) == [] for request in endpoint.requests[1:])
    assert not marker.exists()


async def test_codex_resume_drops_previous_explicit_mcp_server(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    marker = tmp_path / "explicit-mcp-started"
    config = configuration(tmp_path, endpoint)
    configured = config.model_copy(
        update={
            "mcp_servers": {
                "probe": CodexMcpServerConfig(
                    command=sys.executable,
                    args=[
                        str(
                            Path(__file__).parents[1]
                            / "fixtures"
                            / "native_mcp_probe.py"
                        ),
                        str(marker),
                    ],
                )
            }
        }
    )
    async with asyncio.timeout(40), create_codex(configured).open() as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        result = await turn.turn.result()
        assert result.identifiers is not None
        session = result.identifiers.session
    assert marker.read_text() == "started"
    marker.unlink()
    async with asyncio.timeout(40), create_codex(config).open(session) as handle:
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert not marker.exists()
    assert "tool_search" in inventory(endpoint.requests[0])
    assert all(inventory(request) == [] for request in endpoint.requests[1:])


async def test_codex_fabricated_patch_does_not_write(
    tmp_path: Path, endpoint: InertResponses
) -> None:
    marker = tmp_path / "forbidden-patch"
    endpoint.call = {
        "id": "fc_probe",
        "type": "custom_tool_call",
        "call_id": "call_probe",
        "name": "apply_patch",
        "input": f"*** Begin Patch\n*** Add File: {marker}\n+unauthorized\n*** End Patch",
    }
    async with (
        asyncio.timeout(40),
        create_codex(configuration(tmp_path, endpoint)).open() as handle,
    ):
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert not marker.exists()
    assert all(inventory(request) == [] for request in endpoint.requests)


@pytest.mark.parametrize(
    "grants,expected",
    [
        ([NativeToolGroup.SHELL], "functions.exec_command"),
        ([NativeToolGroup.WEB], "web.run"),
        ([NativeToolGroup.WRITE], "functions.apply_patch"),
    ],
)
async def test_codex_explicit_native_facility_is_advertised(
    tmp_path: Path,
    endpoint: InertResponses,
    grants: NativeTools,
    expected: str,
) -> None:
    async with (
        asyncio.timeout(40),
        create_codex(configuration(tmp_path, endpoint, grants)).open() as handle,
    ):
        turn = await handle.session.start(turn_request("Return probe complete."))
        await turn.turn.result()
    assert expected in inventory(endpoint.requests[0])
    assert not (tmp_path / "ambient-mcp-started").exists()
