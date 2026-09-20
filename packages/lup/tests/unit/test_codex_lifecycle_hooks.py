"""Post-tool feedback and Stop callbacks span bounded logical Codex turns."""

import asyncio
from pathlib import Path

import pytest

from lup.policy.hooks import LupHookInput, LupHookMatcher, LupHookOutput, LupHooksConfig
from lup.providers.codex.app_server import CodexAppServer, RpcNotification
from lup.providers.codex.runtime import (
    CodexConversationState,
    CodexHookSession,
    CodexSessionConfig,
    CodexTurnToolBinder,
)
from lup.sessions.composition import ComposedSession
from lup.sessions.errors import (
    ProviderTurnError,
    TurnAlreadyActiveError,
    TurnContinuationError,
)
from lup.sessions.events import TurnTextBlock, turn_request
from lup.sessions.middleware import CorrectionConfig, DecoratingSession
from lup.types import JsonObject, JsonValue


class CompletingServer(CodexAppServer):
    def __init__(self, tool: bool = False) -> None:
        super().__init__(Path("codex"))
        self.state: CodexConversationState | None = None
        self.starts: list[JsonObject] = []
        self.tool = tool

    async def request(self, method: str, params: JsonObject) -> JsonValue:
        if method == "turn/steer":
            raise RuntimeError("native turn already completed")
        assert method == "turn/start"
        self.starts.append(params)
        turn = f"turn-{len(self.starts)}"
        asyncio.get_running_loop().call_soon(self.finish, turn)
        return {"turn": {"id": turn}}

    def finish(self, turn: str) -> None:
        assert self.state is not None
        item: JsonObject = (
            {
                "id": "command",
                "type": "commandExecution",
                "command": "git status",
                "aggregatedOutput": "complete output",
                "status": "completed",
                "exitCode": 0,
            }
            if self.tool
            else {"id": "message", "type": "agentMessage", "text": turn}
        )
        self.state.handle_notification(
            RpcNotification(
                method="item/completed",
                params={"threadId": "thread", "turnId": turn, "item": item},
            )
        )
        self.state.handle_notification(
            RpcNotification(
                method="turn/completed",
                params={
                    "threadId": "thread",
                    "turn": {"id": turn, "status": "completed"},
                },
            )
        )


def hooked_session(
    tmp_path: Path, hooks: LupHooksConfig, *, tool: bool = False, cycles: int = 2
) -> tuple[CodexHookSession, CompletingServer]:
    server = CompletingServer(tool)
    state = CodexConversationState(
        CodexSessionConfig(cwd=tmp_path, hooks=hooks), server, None
    )
    state.thread_id = "thread"
    server.state = state
    raw = ComposedSession(state.start_turn, CodexTurnToolBinder(state))
    decorated = DecoratingSession(
        raw,
        timeout=None,
        budget=None,
        recovery=None,
        correction=None,
        persistence=None,
        continuation=CorrectionConfig(
            cycles=cycles, instruction="Follow the Stop hook."
        ),
    )
    return CodexHookSession(state, decorated), server


async def test_stop_continues_and_receipts_follow_acceptance(tmp_path: Path) -> None:
    active: list[bool] = []
    received: list[int] = []

    async def stop(event: LupHookInput) -> LupHookOutput:
        active.append(event.stop_hook_active)
        if len(active) == 1:
            return LupHookOutput(
                decision="block",
                reason="inspect the evidence",
                delivery_receipt=lambda: received.append(len(server.starts)),
            )
        return LupHookOutput()

    session, server = hooked_session(
        tmp_path, LupHooksConfig(stop=[LupHookMatcher(hook=stop)])
    )
    handle = await session.start(turn_request("work"))
    result = await handle.turn.result()
    assert len(server.starts) == 2
    assert active == [False, True]
    assert received == [2]
    assert "inspect the evidence" in str(server.starts[1]["input"])
    assert [
        block.text for block in result.blocks if isinstance(block, TurnTextBlock)
    ] == ["turn-1", "turn-2"]
    fresh = await session.start(turn_request("another logical turn"))
    await fresh.turn.result()
    assert active == [False, True, False]


async def test_repeated_stop_blocks_surface_exhaustion(tmp_path: Path) -> None:
    async def stop(_event: LupHookInput) -> LupHookOutput:
        return LupHookOutput(decision="block", reason="still missing evidence")

    session, server = hooked_session(
        tmp_path, LupHooksConfig(stop=[LupHookMatcher(hook=stop)])
    )
    handle = await session.start(turn_request("work"))
    with pytest.raises(TurnContinuationError) as raised:
        await handle.turn.result()
    assert len(server.starts) == 3
    assert "still missing evidence" in str(raised.value)
    assert len(raised.value.failure.blocks) == 3


async def test_late_post_tool_feedback_continues_instead_of_disappearing(
    tmp_path: Path,
) -> None:
    events: list[LupHookInput] = []
    receipts: list[int] = []

    async def after(event: LupHookInput) -> LupHookOutput:
        events.append(event)
        if len(events) == 1:
            return LupHookOutput(
                system_message="review the command output",
                delivery_receipt=lambda: receipts.append(len(server.starts)),
            )
        return LupHookOutput()

    hooks = LupHooksConfig(
        post_tool_use=[LupHookMatcher(matcher="^ShellCommand$", hook=after)]
    )
    session, server = hooked_session(tmp_path, hooks, tool=True)
    handle = await session.start(turn_request("work"))
    await handle.turn.result()
    assert len(server.starts) == 2
    assert receipts == [2]
    assert events[0].tool_input == {"command": "git status"}
    assert events[0].tool_result == "complete output"
    assert events[0].cwd == str(tmp_path)
    assert "review the command output" in str(server.starts[1]["input"])


@pytest.mark.parametrize("event", ["post_tool_use", "stop"])
async def test_hook_failure_preserves_completed_evidence(
    tmp_path: Path, event: str
) -> None:
    async def broken(_event: LupHookInput) -> LupHookOutput:
        raise RuntimeError("hook failed visibly")

    hooks = LupHooksConfig.model_validate({event: [LupHookMatcher(hook=broken)]})
    session, server = hooked_session(tmp_path, hooks, tool=event == "post_tool_use")
    handle = await session.start(turn_request("work"))
    with pytest.raises(ProviderTurnError) as raised:
        await handle.turn.result()
    assert "hook failed visibly" in str(raised.value)
    assert raised.value.failure.blocks
    assert len(server.starts) == 1


async def test_an_overlapping_public_start_cannot_reset_stop_state(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    released = asyncio.Event()

    async def stop(_event: LupHookInput) -> LupHookOutput:
        entered.set()
        await released.wait()
        return LupHookOutput()

    session, _ = hooked_session(
        tmp_path, LupHooksConfig(stop=[LupHookMatcher(hook=stop)])
    )
    handle = await session.start(turn_request("work"))
    await entered.wait()
    with pytest.raises(TurnAlreadyActiveError):
        await session.start(turn_request("overlap"))
    released.set()
    await handle.turn.result()
