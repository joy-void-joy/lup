"""Native app-server 0.155.1 turn contracts without authentication or model calls."""

import asyncio
import json
from collections import deque
from pathlib import Path

import pytest
from pydantic import BaseModel

from lup.providers.codex.app_server import CodexAppServer, RpcMessage, RpcNotification
from lup.providers.codex.runtime import (
    CodexConversationState,
    CodexMcpServerConfig,
    CodexSessionConfig,
    CodexTurnChannel,
    create_codex,
    decode_completed_item,
)
from lup.providers.codex.selection import codex_config
from lup.providers.selection import SessionRequest
from lup.sessions.errors import (
    StructuredOutputError,
    TurnInterruptedError,
    UnsupportedCapability,
)
from lup.sessions.events import SessionId, SubmissionDecision, TurnInput, turn_request
from lup.sessions.events import AnyTurnBlock, TurnNativeActivityBlock, TurnThinkingBlock
from lup.sessions.events import TurnResult
from pydantic import TypeAdapter
from lup.sessions.middleware import CorrectionConfig
from lup.types import JsonObject, JsonValue


class Answer(BaseModel):
    answer: str


class Score(BaseModel):
    score: int


class ScriptedCodex(CodexAppServer):
    """Record native requests and emit the documented per-turn notification shape."""

    def __init__(self, answers: list[str | None]) -> None:
        super().__init__(Path("codex"))
        self.answers = deque(answers)
        self.requests: list[tuple[str, JsonObject]] = []
        self.started: asyncio.Queue[str] = asyncio.Queue()
        self.turn_count = 0

    async def start(self) -> None:
        return None

    def emit(self, method: str, params: JsonObject) -> None:
        assert self.notification_handler is not None
        self.notification_handler(RpcNotification(method=method, params=params))

    async def request(self, method: str, params: JsonObject) -> JsonValue:
        self.requests.append((method, params))
        match method:
            case "thread/start" | "thread/resume":
                return {"thread": {"id": "thread-1"}}
            case "turn/start":
                self.turn_count += 1
                turn_id = f"turn-{self.turn_count}"
                self.emit(
                    "turn/started", {"threadId": "thread-1", "turn": {"id": turn_id}}
                )
                self.started.put_nowait(turn_id)
                answer = self.answers.popleft()
                if answer is not None:
                    self.emit(
                        "item/completed",
                        {
                            "threadId": "thread-1",
                            "turnId": turn_id,
                            "item": {
                                "id": f"message-{turn_id}",
                                "type": "agentMessage",
                                "text": answer,
                                "phase": "final_answer",
                            },
                        },
                    )
                    self.emit(
                        "thread/tokenUsage/updated",
                        {
                            "threadId": "thread-1",
                            "turnId": turn_id,
                            "tokenUsage": {
                                "last": {
                                    "inputTokens": 4,
                                    "outputTokens": 2,
                                    "cachedInputTokens": 0,
                                }
                            },
                        },
                    )
                    self.emit(
                        "turn/completed",
                        {
                            "threadId": "thread-1",
                            "turn": {
                                "id": turn_id,
                                "status": "completed",
                                "durationMs": 10,
                            },
                        },
                    )
                return {"turn": {"id": turn_id}}
            case "turn/interrupt":
                self.emit(
                    "turn/completed",
                    {
                        "threadId": "thread-1",
                        "turn": {"id": params["turnId"], "status": "interrupted"},
                    },
                )
                return {}
            case "turn/steer":
                assert "expectedTurnId" in params
                assert "turnId" not in params
                return {"turnId": params["expectedTurnId"]}
            case _:
                raise AssertionError(f"unexpected request {method}")


@pytest.fixture
def scripted_codex(monkeypatch: pytest.MonkeyPatch) -> ScriptedCodex:
    server = ScriptedCodex([])
    monkeypatch.setattr(
        "lup.providers.codex.runtime.CodexAppServer", lambda *args, **kwargs: server
    )
    return server


@pytest.mark.parametrize("resume", [None, SessionId(value="thread-1")])
async def test_output_schema_is_per_turn_across_untyped_and_changed_types(
    tmp_path: Path,
    scripted_codex: ScriptedCodex,
    resume: SessionId | None,
) -> None:
    server = scripted_codex
    server.answers.extend(['{"answer":"first"}', "untyped", '{"score":7}'])
    async with create_codex(CodexSessionConfig(cwd=tmp_path)).open(resume) as handle:
        first = await handle.session.start(turn_request("answer", Answer))
        assert (await first.turn.result()).output == Answer(answer="first")
        second = await handle.session.start(turn_request("continue"))
        assert (await second.turn.result()).output is None
        third = await handle.session.start(turn_request("score", Score))
        assert (await third.turn.result()).output == Score(score=7)
    thread_requests = [
        (method, params)
        for method, params in server.requests
        if method.startswith("thread/")
    ]
    assert len(thread_requests) == 1
    assert thread_requests[0][0] == (
        "thread/start" if resume is None else "thread/resume"
    )
    assert "dynamicTools" not in thread_requests[0][1]
    turns = [params for method, params in server.requests if method == "turn/start"]
    assert [turn.get("outputSchema") for turn in turns] == [
        Answer.model_json_schema(),
        None,
        Score.model_json_schema(),
    ]


async def test_gate_feedback_corrects_output_and_keeps_all_events_and_usage(
    tmp_path: Path,
    scripted_codex: ScriptedCodex,
) -> None:
    server = scripted_codex
    server.answers.extend(['{"answer":"wrong"}', '{"answer":"accepted"}'])

    async def gate(value: BaseModel) -> SubmissionDecision:
        assert isinstance(value, Answer)
        return SubmissionDecision(
            accepted=value.answer == "accepted", message="Use the exact answer accepted"
        )

    config = CodexSessionConfig(
        cwd=tmp_path, submission_gate_resolver=lambda _output: gate
    )
    async with create_codex(config).open() as handle:
        accepted = await handle.session.start(turn_request("answer", Answer))
        assert accepted.events is not None
        events = [event async for event in accepted.events.events()]
        result = await accepted.turn.result()
    assert result.output == Answer(answer="accepted")
    assert result.usage.input_tokens == 8
    assert result.usage.output_tokens == 4
    assert result.duration.total_seconds() == 0.02
    assert {event.identifiers.turn.value for event in events} == {"turn-1", "turn-2"}
    assert len(result.blocks) == 2
    assert len(result.messages) == 2
    replay = TurnResult[Answer].model_validate_json(result.model_dump_json())
    assert replay.messages[0].native is not None
    assert replay.messages[0].native["phase"] == "final_answer"
    turns = [params for method, params in server.requests if method == "turn/start"]
    assert "Use the exact answer accepted" in str(turns[1]["input"])


async def test_exhausted_validation_keeps_each_attempt_and_usage(
    tmp_path: Path,
    scripted_codex: ScriptedCodex,
) -> None:
    server = scripted_codex
    server.answers.extend(["not JSON", '{"wrong":"shape"}'])
    config = CodexSessionConfig(cwd=tmp_path, correction=CorrectionConfig(cycles=1))
    async with create_codex(config).open() as handle:
        accepted = await handle.session.start(turn_request("answer", Answer))
        with pytest.raises(StructuredOutputError) as raised:
            await accepted.turn.result()
    assert len(raised.value.failure.validation_history) == 2
    assert len(raised.value.failure.messages) == 2
    assert "valid JSON" in raised.value.failure.validation_history[0].message
    assert "requested schema" in raised.value.failure.validation_history[1].message
    assert raised.value.failure.usage.output_tokens == 4
    assert server.turn_count == 2


async def test_correcting_turn_steers_and_interrupts_the_current_native_turn(
    tmp_path: Path,
    scripted_codex: ScriptedCodex,
) -> None:
    server = scripted_codex
    server.answers.extend(['{"wrong":"shape"}', None])
    async with create_codex(CodexSessionConfig(cwd=tmp_path)).open() as handle:
        accepted = await handle.session.start(turn_request("answer", Answer))
        assert await server.started.get() == "turn-1"
        assert await asyncio.wait_for(server.started.get(), timeout=1) == "turn-2"
        assert accepted.steer is not None and accepted.interrupt is not None
        await accepted.steer.steer(TurnInput(text="Use the answer field"))
        await accepted.interrupt.interrupt()
        with pytest.raises(TurnInterruptedError):
            await accepted.turn.result()
    assert (
        "turn/steer",
        {
            "threadId": "thread-1",
            "expectedTurnId": "turn-2",
            "input": [{"type": "text", "text": "Use the answer field"}],
        },
    ) in server.requests
    assert server.turn_count == 2


async def test_session_close_cancels_a_pending_submission_gate(
    tmp_path: Path, scripted_codex: ScriptedCodex
) -> None:
    scripted_codex.answers.append('{"answer":"ready"}')
    entered = asyncio.Event()
    canceled = asyncio.Event()

    async def gate(_value: BaseModel) -> SubmissionDecision:
        entered.set()
        try:
            await asyncio.Event().wait()
            return SubmissionDecision(accepted=True)
        finally:
            canceled.set()

    config = CodexSessionConfig(
        cwd=tmp_path, submission_gate_resolver=lambda _output: gate
    )
    async with create_codex(config).open() as handle:
        accepted = await handle.session.start(turn_request("answer", Answer))
        await asyncio.wait_for(entered.wait(), timeout=1)
    assert canceled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await accepted.turn.result()


@pytest.mark.parametrize("limit", ["max_turns", "max_thinking_tokens"])
def test_native_unavailable_numeric_limits_are_never_silently_dropped(
    tmp_path: Path, limit: str
) -> None:
    request = SessionRequest.model_validate({"cwd": tmp_path, limit: 4})
    with pytest.raises(UnsupportedCapability, match=limit):
        codex_config(request)


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "form", "requestedSchema": {"type": "object"}},
        {"mode": "url", "url": "https://example.com/login", "elicitationId": "e1"},
        {"mode": "openai/userVerification", "credentialData": "challenge"},
    ],
)
async def test_interactive_mcp_elicitations_are_never_accepted_as_tool_approval(
    tmp_path: Path, params: JsonObject
) -> None:
    state = CodexConversationState(
        CodexSessionConfig(
            cwd=tmp_path, mcp_servers={"tools": CodexMcpServerConfig(command="tools")}
        ),
        CodexAppServer(Path("codex")),
        None,
    )
    state.thread_id = "thread-1"
    with pytest.raises(UnsupportedCapability, match="interactive"):
        await state.handle_server_request(
            RpcMessage(
                id=1,
                method="mcpServer/elicitation/request",
                params={"threadId": "thread-1", "serverName": "tools", **params},
            )
        )


async def test_mcp_approval_from_another_thread_is_declined(tmp_path: Path) -> None:
    state = CodexConversationState(
        CodexSessionConfig(
            cwd=tmp_path, mcp_servers={"tools": CodexMcpServerConfig(command="tools")}
        ),
        CodexAppServer(Path("codex")),
        None,
    )
    state.thread_id = "thread-1"
    assert await state.handle_server_request(
        RpcMessage(
            id=1,
            method="mcpServer/elicitation/request",
            params={
                "threadId": "other",
                "serverName": "tools",
                "_meta": {"codex_approval_kind": "mcp_tool_call"},
            },
        )
    ) == {"action": "decline"}


def test_reasoning_summary_survives_without_a_content_field() -> None:
    assert decode_completed_item(
        {"id": "r1", "type": "reasoning", "summary": ["Reasoning summary"]}
    ) == [TurnThinkingBlock(thinking="Reasoning summary")]


def test_unsuccessful_dynamic_tool_result_is_recorded_as_an_error() -> None:
    blocks = decode_completed_item(
        {
            "type": "dynamicToolCall",
            "id": "d1",
            "tool": "inspect",
            "arguments": {},
            "status": "completed",
            "success": False,
        }
    )
    assert blocks[-1].refusal is not None


def test_completed_command_with_nonzero_exit_status_is_an_error() -> None:
    blocks = decode_completed_item(
        {
            "type": "commandExecution",
            "id": "c1",
            "command": "false",
            "status": "completed",
            "aggregatedOutput": "",
            "exitCode": 1,
        }
    )
    assert blocks[-1].refusal is not None


def test_native_activity_survives_result_serialization_and_telemetry() -> None:
    payload: JsonObject = {
        "type": "contextCompaction",
        "id": "c1",
        "futureField": {"complete": [1, 2, 3]},
    }
    blocks = decode_completed_item(payload)
    assert blocks == [
        TurnNativeActivityBlock(
            provider="codex", activity="contextCompaction", payload=payload
        )
    ]
    adapter = TypeAdapter(list[AnyTurnBlock])
    assert adapter.validate_json(adapter.dump_json(blocks)) == blocks
    assert json.loads(blocks[0].telemetry_block.display_body) == payload
    assert blocks[0].text_payload is None
    assert blocks[0].tool_call_name is None


def test_version_generated_schema_requires_expected_turn_identity() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "codex"
    steer = json.loads((fixtures / "TurnSteerParams.json").read_text())
    start = json.loads((fixtures / "TurnStartParams.json").read_text())
    assert set(steer["required"]) == {"expectedTurnId", "threadId", "input"}
    assert "turnId" not in steer["properties"]
    assert "outputSchema" in start["properties"]
    assert "dynamicTools" not in start["properties"]


async def test_unrelated_notifications_do_not_claim_a_turn_channel() -> None:
    channel = CodexTurnChannel("thread-1")
    channel.feed(
        RpcNotification(method="unrelated/event", params={"turnId": "other-turn"})
    )
    channel.feed(
        RpcNotification(
            method="turn/started",
            params={"threadId": "other-thread", "turn": {"id": "other-turn"}},
        )
    )
    assert channel.turn_id is None
    assert channel.events.empty()


def test_every_native_completed_item_kind_produces_replay_evidence() -> None:
    schema = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "codex"
            / "ItemCompletedNotification.json"
        ).read_text()
    )
    kinds = {
        item["properties"]["type"]["enum"][0]
        for item in schema["definitions"]["ThreadItem"]["oneOf"]
    }
    assert kinds == {
        "userMessage",
        "hookPrompt",
        "agentMessage",
        "functionCallOutput",
        "plan",
        "reasoning",
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "subAgentActivity",
        "webSearch",
        "imageView",
        "sleep",
        "imageGeneration",
        "enteredReviewMode",
        "exitedReviewMode",
        "contextCompaction",
    }
    for kind in kinds | {"futureNativeActivity"}:
        payload: JsonObject = {
            "id": "item-1",
            "type": kind,
            "text": "complete text",
            "summary": ["summary"],
            "content": [],
            "arguments": {},
            "server": "tools",
            "tool": "inspect",
            "status": "completed",
            "command": "pwd",
            "aggregatedOutput": "/tmp",
            "changes": [],
        }
        blocks = decode_completed_item(payload)
        assert blocks, kind
        assert any(block.telemetry_block.display_body for block in blocks), kind
