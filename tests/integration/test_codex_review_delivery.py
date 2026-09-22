"""An inert Responses server proves hook delivery and one-use native retries."""

import asyncio
import json
import shlex
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import sh
from pydantic import BaseModel

from lup.policy.relay import QuestionRelay
from lup.providers.codex.app_server import CodexAppServer, RpcNotification
from lup.providers.codex.home import seed_hook_trust
from lup.providers.codex.trust import CodexHookReport
from lup.types import JsonObject

pytestmark = pytest.mark.integration


class StartedThread(BaseModel):
    class Thread(BaseModel):
        id: str

    thread: Thread


class HookEntry(BaseModel):
    kind: str
    text: str


class CompletedHook(BaseModel):
    class Run(BaseModel):
        status: str
        entries: list[HookEntry]

    run: Run


async def test_review_warning_blocks_then_exact_operator_answer_resumes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    root = tmp_path / "checkout"
    root.mkdir()
    sh.Command("git")("init", "--quiet", str(root))
    source = root / "proposal.md"
    target = root / "DESIGN.md"
    source.write_text("# Agreed design\n")
    target.write_text("# Previous design\n")
    command = "# lup: escalate[decision]: install the reviewed design\ncp proposal.md DESIGN.md"
    requests: list[JsonObject] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            requests.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            item: JsonObject = (
                {
                    "type": "function_call",
                    "id": "fc_review",
                    "call_id": f"call_{len(requests)}",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": command}),
                }
                if len(requests) % 2
                else {
                    "id": "msg_review",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "review attempt complete",
                            "annotations": [],
                        }
                    ],
                }
            )
            response: JsonObject = {
                "id": "resp_review",
                "object": "response",
                "status": "completed",
                "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            events: list[JsonObject] = [
                {"type": "response.output_item.added", "output_index": 0, "item": item},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            body = "".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                for event in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """The captured request bodies are this fixture's evidence."""

    endpoint = HTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=endpoint.serve_forever, daemon=True)
    serving.start()
    dispatcher = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    (home / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": shlex.join([str(dispatcher)]),
                                }
                            ],
                        }
                    ]
                    for event in ("PreToolUse", "PostToolUse")
                }
            }
        )
    )
    config: JsonObject = {
        "model": "gpt-6-astra",
        "model_provider": "lup_inert_review",
        "model_providers.lup_inert_review.name": "Inert local review fixture",
        "model_providers.lup_inert_review.base_url": f"http://127.0.0.1:{endpoint.server_port}/v1",
        "model_providers.lup_inert_review.wire_api": "responses",
        "model_providers.lup_inert_review.requires_openai_auth": False,
        "model_providers.lup_inert_review.supports_websockets": False,
        "features.enable_request_compression": False,
        "features.hooks": True,
        "features.code_mode": False,
        "features.code_mode_host": False,
        "features.code_mode_only": False,
        "approval_policy": "never",
        "sandbox_mode": "danger-full-access",
        "notify": [],
    }
    server = CodexAppServer(
        Path("codex"),
        arguments=[
            part
            for key, value in config.items()
            for part in ("-c", f"{key}={json.dumps(value)}")
        ],
        environment={"CODEX_HOME": str(home)},
    )
    completed = asyncio.Event()
    observed: list[CompletedHook] = []

    def notice(event: RpcNotification) -> None:
        if event.method == "hook/completed":
            observed.append(CompletedHook.model_validate(event.params))
        if event.method == "turn/completed":
            completed.set()

    server.notification_handler = notice
    try:
        async with asyncio.timeout(45):
            await server.start()
            listing = CodexHookReport.model_validate(
                await server.request("hooks/list", {"cwds": [str(root)]})
            )
            seed_hook_trust(home, listing.resolved())
            started = StartedThread.model_validate(
                await server.request(
                    "thread/start",
                    {
                        "model": "gpt-6-astra",
                        "modelProvider": "lup_inert_review",
                        "cwd": str(root),
                        "approvalPolicy": "never",
                        "sandbox": "danger-full-access",
                        "ephemeral": True,
                    },
                )
            )

            async def attempt() -> None:
                completed.clear()
                await server.request(
                    "turn/start",
                    {
                        "threadId": started.thread.id,
                        "input": [
                            {"type": "text", "text": "Run the proposed copy once."}
                        ],
                    },
                )
                await completed.wait()

            await attempt()
            assert target.read_text() == "# Previous design\n"
            store = QuestionRelay(root / ".lup/questions.jsonl")
            (question,) = store.pending()
            assert any(
                entry.kind == "warning" and question.id in entry.text
                for hook in observed
                if hook.run.status == "blocked"
                for entry in hook.run.entries
            )
            store.answer(question.id, "operator", True)
            await attempt()
            assert target.read_text() == "# Agreed design\n"
            consumed = store.find(question.id)
            assert consumed is not None and consumed.state == "dispatched"
            await attempt()
            assert len(store.pending()) == 1
    finally:
        try:
            await server.close()
        finally:
            endpoint.shutdown()
            endpoint.server_close()
            serving.join()
