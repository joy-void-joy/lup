"""Realtime relay wiring: mailbox protocol, served tools, and the wake loop.

The relay is how persistent mode works on backends whose tools run in a
subprocess (Codex/OpenAI): tools append events and a sleep request to
files, the parent applies them to the Scheduler and drives turn-per-wake
cycles. These tests round-trip that boundary without any LLM or
subprocess — the tool handlers and the parent loop share a directory,
exactly like the two processes share one in production.
"""

import asyncio
import json
from pathlib import Path
from typing import Any


from lup.adapters.common import Conversation
from lup.mcp import LupMcpTool
from lup.realtime import Scheduler
from lup.realtime_relay import (
    MISSING_SLEEP_MESSAGE,
    ContextReadEvent,
    DebounceEvent,
    MetaEvent,
    RealtimeMailbox,
    RelayState,
    RemindEvent,
    ReplyEvent,
    ScheduleActionEvent,
    apply_relay_event,
    create_realtime_relay_tools,
    run_relay_session,
)
from lup.trace import TraceLogger
from lup.types import LupResponse


def tool_map(realtime_dir: Path) -> dict[str, LupMcpTool]:
    return {t.name: t for t in create_realtime_relay_tools(realtime_dir)}


async def call(
    tools: dict[str, LupMcpTool], name: str, args: dict[str, Any]
) -> dict[
    str, Any
]:  # claude: ignore — MCP handler boundary returns a ToolResponse-shaped dict
    return await tools[name].handler(args)


class TestMailbox:
    def test_events_round_trip_in_order(self, tmp_path: Path) -> None:
        writer = RealtimeMailbox(tmp_path)
        reader = RealtimeMailbox(tmp_path)

        writer.append_event(ReplyEvent(message="hi"))
        writer.append_event(RemindEvent(label="follow up", delay_seconds=60))
        writer.append_event(ContextReadEvent())

        events = reader.read_new_events()
        assert [type(e) for e in events] == [ReplyEvent, RemindEvent, ContextReadEvent]
        assert reader.read_new_events() == []

        writer.append_event(MetaEvent(thought="pacing fine"))
        followup = reader.read_new_events()
        assert len(followup) == 1
        assert isinstance(followup[0], MetaEvent)

    def test_incomplete_line_not_consumed(self, tmp_path: Path) -> None:
        writer = RealtimeMailbox(tmp_path)
        reader = RealtimeMailbox(tmp_path)
        writer.append_event(ReplyEvent(message="complete"))

        with writer.actions_path.open("a", encoding="utf-8") as f:
            f.write('{"type": "reply", "message": "partial"')

        events = reader.read_new_events()
        assert [e.message for e in events if isinstance(e, ReplyEvent)] == ["complete"]

        with writer.actions_path.open("a", encoding="utf-8") as f:
            f.write(', "delay_seconds": 0}\n')

        completed = reader.read_new_events()
        assert [e.message for e in completed if isinstance(e, ReplyEvent)] == [
            "partial"
        ]

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        mailbox = RealtimeMailbox(tmp_path)
        mailbox.root.mkdir(parents=True, exist_ok=True)
        with mailbox.actions_path.open("a", encoding="utf-8") as f:
            f.write('{"type": "unknown_event"}\n')
        mailbox.append_event(ReplyEvent(message="still parsed"))

        events = mailbox.read_new_events()
        assert len(events) == 1
        assert isinstance(events[0], ReplyEvent)

    def test_sleep_request_consumed_once(self, tmp_path: Path) -> None:
        from lup.realtime import SleepInput

        mailbox = RealtimeMailbox(tmp_path)
        assert mailbox.consume_sleep_request() is None

        mailbox.write_sleep_request(SleepInput(seconds=300))
        request = mailbox.consume_sleep_request()
        assert request is not None
        assert request.seconds == 300
        assert mailbox.consume_sleep_request() is None

    def test_state_snapshot_carries_domain_fields(self, tmp_path: Path) -> None:
        mailbox = RealtimeMailbox(tmp_path)
        assert mailbox.read_state() is None

        mailbox.write_state(
            RelayState.model_validate({"unread_events": 2, "channel": "general"})
        )
        state = mailbox.read_state()
        assert state is not None
        assert state.unread_events == 2
        assert state.model_dump()["channel"] == "general"


class TestRelayTools:
    async def test_sleep_requires_meta_then_records(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)

        denied = await call(tools, "sleep", {"seconds": 60})
        assert denied.get("is_error") is True
        assert not (tmp_path / "sleep_request.json").exists()

        reflected = await call(tools, "meta", {"thought": "good pacing"})
        assert reflected.get("is_error") is None
        assert (tmp_path / "meta_flag").exists()

        recorded = await call(tools, "sleep", {"seconds": 60})
        assert recorded.get("is_error") is None
        assert (tmp_path / "sleep_request.json").exists()

    async def test_reply_resets_meta_gate(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)

        await call(tools, "meta", {"thought": "assessed"})
        await call(tools, "reply", {"messages": [{"message": "hello"}]})

        denied = await call(tools, "sleep", {"seconds": 60})
        assert denied.get("is_error") is True

        await call(tools, "meta", {"thought": "assessed again"})
        allowed = await call(tools, "sleep", {"seconds": 60})
        assert allowed.get("is_error") is None

    async def test_unread_events_block_sleep_until_context(
        self, tmp_path: Path
    ) -> None:
        tools = tool_map(tmp_path)
        parent = RealtimeMailbox(tmp_path)
        parent.write_state(RelayState(unread_events=3))

        await call(tools, "meta", {"thought": "assessed"})
        denied = await call(tools, "sleep", {"seconds": 60})
        assert denied.get("is_error") is True

        context = await call(tools, "context", {})
        payload = json.loads(context["content"][0]["text"])
        assert payload["unread_events"] == 3

        allowed = await call(tools, "sleep", {"seconds": 60})
        assert allowed.get("is_error") is None

        events = parent.read_new_events()
        assert any(isinstance(e, ContextReadEvent) for e in events)

    async def test_force_bypasses_unread_guard(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)
        RealtimeMailbox(tmp_path).write_state(RelayState(unread_events=3))

        await call(tools, "meta", {"thought": "assessed"})
        forced = await call(tools, "sleep", {"seconds": 60, "force": True})
        assert forced.get("is_error") is None

    async def test_reply_relays_staggered_messages(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)
        parent = RealtimeMailbox(tmp_path)

        result = await call(
            tools,
            "reply",
            {
                "messages": [
                    {"message": "now"},
                    {"message": "later", "delay_seconds": 10},
                ]
            },
        )
        payload = json.loads(result["content"][0]["text"])
        assert payload == {"sent": 1, "scheduled": 1}

        events = parent.read_new_events()
        replies = [e for e in events if isinstance(e, ReplyEvent)]
        assert [(r.message, r.delay_seconds) for r in replies] == [
            ("now", 0),
            ("later", 10),
        ]


class TestApplyRelayEvent:
    async def test_reply_delivers_and_cancels_scheduled_action(self) -> None:
        delivered: list[str] = []

        async def on_action(content: str) -> None:
            delivered.append(content)

        scheduler = Scheduler(on_action=on_action)
        await apply_relay_event(
            ScheduleActionEvent(content="nudge", delay_seconds=300),
            scheduler=scheduler,
        )
        assert scheduler.get_state().get("scheduled_action") is not None

        await apply_relay_event(ReplyEvent(message="hello"), scheduler=scheduler)
        assert delivered == ["hello"]
        assert scheduler.get_state().get("scheduled_action") is None
        assert "nudge" in scheduler.ideas

    async def test_scheduling_events_reach_scheduler(self) -> None:
        async def on_action(_content: str) -> None:
            pass

        scheduler = Scheduler(on_action=on_action)
        await apply_relay_event(
            RemindEvent(label="check back", delay_seconds=120), scheduler=scheduler
        )
        await apply_relay_event(
            DebounceEvent(initial_seconds=30, quiet_seconds=5), scheduler=scheduler
        )

        state = scheduler.get_state()
        assert state.get("debounce_active") is True
        assert [r["label"] for r in state.get("pending_reminders", [])] == [
            "check back"
        ]

    async def test_context_read_consumes_pending_wake(self) -> None:
        async def on_action(_content: str) -> None:
            pass

        scheduler = Scheduler(on_action=on_action)
        scheduler.wake("user_message")
        assert scheduler.wake_pending is True

        await apply_relay_event(ContextReadEvent(), scheduler=scheduler)
        assert scheduler.wake_pending is False

    async def test_meta_logged_to_trace(self, tmp_path: Path) -> None:
        async def on_action(_content: str) -> None:
            pass

        trace = TraceLogger(trace_path=tmp_path / "trace.md", title="t")
        await apply_relay_event(
            MetaEvent(thought="pacing was rushed"),
            scheduler=Scheduler(on_action=on_action),
            trace_logger=trace,
        )
        assert any("pacing was rushed" in line for line in trace.lines)


class AgentTurn:
    """One scripted agent turn: tool calls the fake agent makes."""

    def __init__(
        self,
        tools: dict[str, LupMcpTool],
        calls: list[tuple[str, dict[str, Any]]],
        *,
        pause_seconds: float = 0.0,
    ) -> None:
        self.tools = tools
        self.calls = calls
        self.pause_seconds = pause_seconds

    async def play(self) -> None:
        for name, args in self.calls:
            await self.tools[name].handler(args)
        if self.pause_seconds:
            await asyncio.sleep(self.pause_seconds)


class FakeConversation(Conversation):
    """Conversation stand-in that plays scripted turns."""

    def __init__(self, turns: list[AgentTurn]) -> None:
        self.turns = turns
        self.prompts: list[str] = []

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.prompts.append(prompt)
        await self.turns[len(self.prompts) - 1].play()
        return LupResponse()


META = ("meta", {"thought": "assessed"})
SLEEP = ("sleep", {"seconds": 0})


class TestRelaySession:
    async def test_wake_cycles_with_corrective_turn(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)
        delivered: list[str] = []

        async def on_action(content: str) -> None:
            delivered.append(content)

        scheduler = Scheduler(on_action=on_action)
        conversation = FakeConversation(
            [
                AgentTurn(
                    tools,
                    [("reply", {"messages": [{"message": "hello"}]}), META, SLEEP],
                ),
                AgentTurn(tools, []),  # ends turn without sleeping
                AgentTurn(tools, [META, SLEEP]),
            ]
        )

        turns = await run_relay_session(
            conversation,
            scheduler=scheduler,
            mailbox=RealtimeMailbox(tmp_path),
            initial_prompt="[session start]",
            should_continue=lambda: len(conversation.prompts) < 3,
            poll_interval_seconds=0.01,
        )

        assert turns == 3
        assert delivered == ["hello"]
        assert conversation.prompts[0] == "[session start]"
        assert conversation.prompts[1].startswith("[wake] reason: timer")
        assert conversation.prompts[2] == MISSING_SLEEP_MESSAGE

    async def test_events_applied_during_turn_not_after(self, tmp_path: Path) -> None:
        tools = tool_map(tmp_path)
        delivered_during_turn: list[bool] = []

        async def on_action(_content: str) -> None:
            delivered_during_turn.append(in_turn[0])

        in_turn = [False]

        class MidTurnConversation(FakeConversation):
            async def send(
                self,
                prompt: str,
                *,
                trace_logger: TraceLogger | None = None,
                prefix: str = "",
            ) -> LupResponse:
                in_turn[0] = True
                try:
                    return await super().send(prompt, trace_logger=trace_logger)
                finally:
                    in_turn[0] = False

        conversation = MidTurnConversation(
            [
                AgentTurn(
                    tools,
                    [
                        ("reply", {"messages": [{"message": "mid-turn"}]}),
                        META,
                        SLEEP,
                    ],
                    pause_seconds=0.1,
                ),
            ]
        )

        await run_relay_session(
            conversation,
            scheduler=Scheduler(on_action=on_action),
            mailbox=RealtimeMailbox(tmp_path),
            initial_prompt="[session start]",
            should_continue=lambda: len(conversation.prompts) < 1,
            poll_interval_seconds=0.01,
        )

        assert delivered_during_turn == [True]

    async def test_session_ends_after_repeated_missing_sleep(
        self, tmp_path: Path
    ) -> None:
        tools = tool_map(tmp_path)

        async def on_action(_content: str) -> None:
            pass

        conversation = FakeConversation([AgentTurn(tools, []) for _ in range(5)])

        turns = await run_relay_session(
            conversation,
            scheduler=Scheduler(on_action=on_action),
            mailbox=RealtimeMailbox(tmp_path),
            initial_prompt="[session start]",
            max_missing_sleep_retries=2,
            poll_interval_seconds=0.01,
        )

        assert turns == 3  # initial turn + two corrective retries
        assert conversation.prompts[1:] == [MISSING_SLEEP_MESSAGE] * 2

    async def test_sleep_request_applies_debounce_and_follow_ups(
        self, tmp_path: Path
    ) -> None:
        tools = tool_map(tmp_path)
        delivered: list[str] = []

        async def on_action(content: str) -> None:
            delivered.append(content)

        scheduler = Scheduler(on_action=on_action)
        conversation = FakeConversation(
            [
                AgentTurn(
                    tools,
                    [
                        META,
                        (
                            "sleep",
                            {
                                "seconds": 0,
                                "follow_ups": [
                                    {"message": "thread pull", "delay_seconds": 600}
                                ],
                            },
                        ),
                    ],
                ),
            ]
        )

        await run_relay_session(
            conversation,
            scheduler=scheduler,
            mailbox=RealtimeMailbox(tmp_path),
            initial_prompt="[session start]",
            should_continue=lambda: len(conversation.prompts) < 1,
            poll_interval_seconds=0.01,
        )

        scheduler.cancel_delayed_actions()
        assert "thread pull" in scheduler.ideas
        assert delivered == []
