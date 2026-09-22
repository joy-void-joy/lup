"""Inspect native Responses requests using only a disposable home and localhost."""

import asyncio
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from pydantic import BaseModel, Field

from lup.providers.codex.app_server import CodexAppServer
from lup.providers.codex.output import codex_output_contract
from lup.providers.codex.runtime import CodexThreadResponse
from lup.types import JsonObject


class NativeFormat(BaseModel):
    strict: bool
    schema_value: JsonObject = Field(alias="schema")


class NativeText(BaseModel):
    format: NativeFormat


class NativeRequest(BaseModel):
    text: NativeText


@pytest.mark.skipif(
    shutil.which("codex") is None, reason="native Codex is not installed"
)
@pytest.mark.parametrize("optional", [False, True])
async def test_installed_codex_sends_a_valid_strict_output_contract(
    tmp_path: Path, optional: bool
) -> None:
    schema: JsonObject = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": [] if optional else ["answer"],
    }
    contract = codex_output_contract(schema)
    loop = asyncio.get_running_loop()
    captured: asyncio.Future[NativeRequest] = loop.create_future()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                assert self.path == "/v1/responses"
                assert "Authorization" not in self.headers
                body = self.rfile.read(int(self.headers["Content-Length"]))
                request = NativeRequest.model_validate_json(body)
            except Exception as error:
                loop.call_soon_threadsafe(captured.set_exception, error)
            else:
                loop.call_soon_threadsafe(captured.set_result, request)
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"Local capture complete","type":"invalid_request_error"}}'
            )

        def log_message(self, format: str, *args: object) -> None:
            return None

    endpoint = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=endpoint.serve_forever, daemon=True)
    worker.start()
    (tmp_path / "config.toml").write_text(
        'model = "gpt-5.4"\nmodel_provider = "local_fixture"\n'
        '[model_providers.local_fixture]\nname = "Local fixture"\n'
        f'base_url = "http://127.0.0.1:{endpoint.server_port}/v1"\n'
        'wire_api = "responses"\nrequires_openai_auth = false\n'
    )
    executable = shutil.which("codex")
    assert executable is not None
    server = CodexAppServer(
        Path(executable),
        environment={
            "CODEX_HOME": str(tmp_path),
            "OPENAI_API_KEY": "",
            "CODEX_API_KEY": "",
        },
    )
    try:
        async with asyncio.timeout(30):
            await server.start()
            started = CodexThreadResponse.model_validate(
                await server.request(
                    "thread/start",
                    {
                        "cwd": str(tmp_path),
                        "model": "gpt-5.4",
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                    },
                )
            )
            await server.request(
                "turn/start",
                {
                    "threadId": started.thread.id,
                    "input": [
                        {"type": "text", "text": contract.prompt("Return an answer.")}
                    ],
                    "outputSchema": contract.native,
                },
            )
            request = await captured
            assert request.text.format.strict is True
            assert request.text.format.schema_value == contract.native
            assert contract.native["additionalProperties"] is False
            assert contract.native["required"] == (
                ["output_json"] if optional else ["answer"]
            )
    finally:
        await server.close()
        await asyncio.to_thread(endpoint.shutdown)
        worker.join()
        endpoint.server_close()
