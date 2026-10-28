"""Codex's adapter, driven by a scripted client in place of the SDK's: no Codex process, no network.

The fake hands the adapter notifications as the SDK would, and sends Codex's requests
through the adapter's real handler, so tool calls reach the real toolbox.
"""

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from openai_codex.client import ApprovalHandler, CodexClient, CodexConfig
from openai_codex.errors import ServerBusyError, TransportClosedError
from openai_codex.generated import v2_all as wire
from openai_codex.models import InitializeResponse, JsonObject, JsonValue, Notification
from pydantic import BaseModel
from tenacity import stop_after_attempt, wait_none

import lup
from lup import (
    AgentUnavailableError,
    AuthMissingError,
    BlockedError,
    Friction,
    HowItFelt,
    OutputMissingError,
    Recovery,
    SessionLayers,
    StoppedError,
    TurnError,
    UsageLimitReachedError,
)
from lup.adapters.codex import Codex, Effort
from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.runtime import LAUNCH, CodexAdapter
from lup.adapters.codex.settings import CodexSettings
from lup.sessions.contract import Adapter, RawTurn, Seam, TurnRequest, seam
from lup.sessions.errors import RealCallInTestError
from lup.sessions.submission import Toolbox
from lup.tools.speaking import SPEAKING
from lup.tools.submit import Submit

if TYPE_CHECKING:
    from lup.sessions.declaration import Declaration
    from lup.testing import FakeAgents


class Forecast(BaseModel):
    probability: float


# What Codex sends: notifications, built with the SDK's own models.


def message(text: str, turn: str = "turn-1") -> Notification:
    payload = wire.ItemCompletedNotification.model_validate(
        {
            "completedAtMs": 1,
            "threadId": "thread-1",
            "turnId": turn,
            "item": {"type": "agentMessage", "id": "item", "text": text},
        }
    )
    return Notification(method="item/completed", payload=payload)


def breakdown(input_tokens: int, cached: int, output: int) -> dict[str, int]:
    return {
        "inputTokens": input_tokens,
        "cachedInputTokens": cached,
        "outputTokens": output,
        "reasoningOutputTokens": 0,
        "totalTokens": input_tokens + output,
    }


def tokens(total: dict[str, int], last: dict[str, int]) -> Notification:
    payload = wire.ThreadTokenUsageUpdatedNotification.model_validate(
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "tokenUsage": {"total": total, "last": last},
        }
    )
    return Notification(method="thread/tokenUsage/updated", payload=payload)


def error(info: JsonValue, *, will_retry: bool = False) -> Notification:
    payload = wire.ErrorNotification.model_validate(
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "willRetry": will_retry,
            "error": {"message": "it went wrong", "codexErrorInfo": info},
        }
    )
    return Notification(method="error", payload=payload)


def completed(
    turn: str = "turn-1", status: str = "completed", failure: JsonObject | None = None
) -> Notification:
    payload = wire.TurnCompletedNotification.model_validate(
        {
            "threadId": "thread-1",
            "turn": {"id": turn, "items": [], "status": status, "error": failure},
        }
    )
    return Notification(method="turn/completed", payload=payload)


def limits(primary: JsonObject, secondary: JsonObject | None = None) -> Notification:
    payload = wire.AccountRateLimitsUpdatedNotification.model_validate(
        {"rateLimits": {"primary": primary, "secondary": secondary}}
    )
    return Notification(method="account/rateLimits/updated", payload=payload)


@dataclass
class Ask:
    """A request Codex makes of the client, answered by the adapter's handler."""

    method: str
    params: JsonObject


@dataclass
class Stall:
    """The turn runs until it's interrupted."""


@dataclass
class Report:
    """A notification outside any turn; the turn waits until the watcher has taken it in."""

    notification: Notification


type Step = Notification | Ask | Stall | Report


def calling(
    tool: str, arguments: JsonValue, call: str = "call-1", turn: str = "turn-1"
) -> Ask:
    """Codex calls one of lup's tools, as a dynamic tool."""
    params: JsonObject = {
        "threadId": "thread-1",
        "turnId": turn,
        "callId": call,
        "namespace": None,
        "tool": tool,
        "arguments": arguments,
    }
    return Ask("item/tool/call", params)


def submitting(arguments: JsonValue, call: str = "call-1", turn: str = "turn-1") -> Ask:
    return calling("submit", arguments, call, turn)


class FakeClient(CodexClient):
    """The SDK's client, scripted: each turn's steps in order, every call the adapter made logged."""

    def __init__(
        self,
        config: CodexConfig,
        approval_handler: ApprovalHandler,
        *,
        turns: deque[deque[Step]],
        account: JsonObject,
        refuse: dict[str, Exception],
        stalled: threading.Event,
    ) -> None:
        super().__init__(config, approval_handler)
        self.launched = config
        self.serve = approval_handler
        self.turns = turns
        self.steps: deque[Step] = deque()
        self.account = account
        self.refuse = refuse
        self.stalled = stalled
        self.log: list[str] = []
        self.sent: dict[str, list[JsonObject]] = {}
        self.answers: list[JsonObject] = []
        self.cond = threading.Condition()
        self.pending: deque[Notification] = deque()
        self.watching = False
        self.closed = False
        self.interrupted = False

    def start(self) -> None:
        self.log.append("start")

    def initialize(self) -> InitializeResponse:
        self.log.append("initialize")
        return InitializeResponse()

    def close(self) -> None:
        self.log.append("close")
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def request[M: BaseModel](
        self, method: str, params: JsonObject | None, *, response_model: type[M]
    ) -> M:
        self.log.append(method)
        self.sent.setdefault(method, []).append(params or {})
        if method in self.refuse:
            raise self.refuse[method]
        if method == "turn/interrupt":
            with self.cond:
                self.interrupted = True
                self.cond.notify_all()
        answers: dict[str, JsonObject] = {
            "account/read": self.account,
            "thread/start": {"thread": {"id": "thread-1"}},
            "turn/interrupt": {},
        }
        return response_model.model_validate(answers[method])

    def turn_start(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: wire.TurnStartParams | JsonObject | None = None,
    ) -> wire.TurnStartResponse:
        self.log.append("turn/start")
        assert isinstance(input_items, str)
        assert isinstance(params, dict)
        sent: JsonObject = {"threadId": thread_id, "input": input_items, **params}
        self.sent.setdefault("turn/start", []).append(sent)
        self.steps = self.turns.popleft()
        turn = f"turn-{len(self.sent['turn/start'])}"
        return wire.TurnStartResponse.model_validate(
            {"turn": {"id": turn, "items": [], "status": "inProgress"}}
        )

    def next_turn_notification(self, turn_id: str) -> Notification:
        while True:
            step = self.steps.popleft()
            match step:
                case Ask(method=method, params=params):
                    self.answers.append(self.serve(method, params))
                case Report(notification=notification):
                    with self.cond:
                        self.pending.append(notification)
                        self.cond.notify_all()
                        self.cond.wait_for(lambda: not self.pending and self.watching)
                case Stall():
                    self.stalled.set()
                    with self.cond:
                        self.cond.wait_for(lambda: self.interrupted or self.closed)
                    return completed(turn_id, "interrupted")
                case Notification():
                    return step

    def unregister_turn_notifications(self, turn_id: str) -> None:
        self.log.append(f"unregister {turn_id}")

    def next_notification(self) -> Notification:
        with self.cond:
            self.watching = True
            self.cond.notify_all()
            self.cond.wait_for(lambda: bool(self.pending) or self.closed)
            self.watching = False
            if not self.pending:
                message = "the client closed"
                raise TransportClosedError(message)
            return self.pending.popleft()


LOGGED_IN: JsonObject = {
    "account": {"type": "chatgpt", "email": "x@example.com", "planType": "pro"},
    "requiresOpenaiAuth": True,
}


class Rig:
    """An adapter on a fake client, in homes under the test's own directory."""

    def __init__(
        self,
        tmp_path: Path,
        turns: list[list[Step]],
        *,
        account: JsonObject = LOGGED_IN,
        refuse: dict[str, Exception] | None = None,
        system_prompt: str | None = "Answer briefly.",
        effort: Effort | None = "low",
        model: str | None = "gpt-6.1-sol",
    ) -> None:
        self.operator = tmp_path / "operator"
        self.operator.mkdir(exist_ok=True)
        (self.operator / "auth.json").write_text("{}")
        self.layout = CodexLayout(
            home=tmp_path / "state" / "lup" / "codex", operator_home=self.operator
        )
        self.stalled = threading.Event()
        self.made: list[FakeClient] = []
        self.turns = deque(deque(turn) for turn in turns)

        def connect(config: CodexConfig, serve: ApprovalHandler) -> FakeClient:
            client = FakeClient(
                config,
                serve,
                turns=self.turns,
                account=account,
                refuse=refuse or {},
                stalled=self.stalled,
            )
            self.made.append(client)
            return client

        self.adapter = CodexAdapter(
            model=model,
            system_prompt=system_prompt,
            effort=effort,
            layout=self.layout,
            connect=connect,
        )

    @property
    def client(self) -> FakeClient:
        [client] = self.made
        return client


def toolbox(*, typed: bool = True, attempts: int = 3) -> Toolbox:
    submit = Submit(Forecast)
    return Toolbox(
        tools=[*SPEAKING, submit] if typed else SPEAKING,
        output=submit.name if typed else None,
        attempts=attempts,
    )


def run(rig: Rig, tools: Toolbox, prompt: str = "Will it rain?") -> RawTurn:
    request = TurnRequest(
        prompt=prompt, toolbox=tools, output=Forecast if tools.output else None
    )
    return asyncio.run(rig.adapter.run(request))


ANSWERED: list[Step] = [submitting({"probability": 0.3}), message("Done."), completed()]


# Thread and turn parameters.


def test_the_thread_carries_lups_tools_and_nothing_else(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    [started] = rig.client.sent["thread/start"]
    assert started == {
        "model": "gpt-6.1-sol",
        "baseInstructions": "Answer briefly.",
        "dynamicTools": [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            }
            for spec in toolbox().specs()
        ],
        "ephemeral": True,
        "environments": [],
        "approvalPolicy": "never",
        "sandbox": "read-only",
        "config": {"agents": {"enabled": False}},
    }


def test_each_turn_carries_the_prompt_and_the_effort(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    assert rig.client.sent["turn/start"] == [
        {"threadId": "thread-1", "input": "Will it rain?", "effort": "low"}
    ]


def test_no_system_prompt_and_no_effort_send_neither(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED], system_prompt=None, effort=None)
    run(rig, toolbox())
    [started] = rig.client.sent["thread/start"]
    assert started["baseInstructions"] == ""
    assert rig.client.sent["turn/start"] == [
        {"threadId": "thread-1", "input": "Will it rain?"}
    ]


def test_no_model_starts_the_thread_on_codex_s_default(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED], model=None)
    run(rig, toolbox())
    [started] = rig.client.sent["thread/start"]
    assert "model" not in started


def test_the_app_server_starts_in_lups_home_with_every_built_in_off(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    launched = rig.client.launched
    assert launched.env == {"CODEX_HOME": str(rig.layout.home)}
    overrides = list(launched.config_overrides)
    assert 'web_search="disabled"' in overrides
    assert "features.shell_tool=false" in overrides
    assert "features.multi_agent=false" in overrides
    assert 'cli_auth_credentials_store="file"' in overrides
    assert len(overrides) == len(LAUNCH)
    assert not any("code_mode" in override for override in overrides)


def test_the_session_starts_checks_the_login_then_starts_the_thread_and_closes(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    assert rig.client.log == [
        "start",
        "initialize",
        "account/read",
        "thread/start",
        "turn/start",
        "unregister turn-1",
        "close",
    ]


# Tools, and the toolbox's guard.


def test_a_tool_call_reaches_the_toolbox_and_its_answer_goes_back(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    tools = toolbox()
    raw = run(rig, tools)
    assert tools.accepted() == Forecast(probability=0.3)
    [answer] = rig.client.answers
    assert answer["success"] is True
    assert answer["contentItems"] == [
        {
            "type": "inputText",
            "text": '{"accepted":true,"message":"Your answer is accepted. You can end your turn now."}',
        }
    ]
    assert raw.text == "Done."
    assert raw.session_id == "thread-1"


def test_a_refused_call_answers_with_the_reason_and_fails(tmp_path: Path) -> None:
    turn: list[Step] = [
        submitting({"probability": "high"}, call="call-1"),
        submitting({"probability": 0.9}, call="call-2"),
        completed(),
    ]
    rig = Rig(tmp_path, [turn])
    tools = toolbox()
    run(rig, tools)
    refused, accepted = rig.client.answers
    assert refused["success"] is False
    assert "probability" in str(refused["contentItems"])
    assert accepted["success"] is True
    assert [rejection.submitted for rejection in tools.rejected()] == [
        {"probability": "high"}
    ]


def test_a_turn_ending_unanswered_continues_the_thread_with_the_reason(
    tmp_path: Path,
) -> None:
    first: list[Step] = [message("It might rain."), completed()]
    second: list[Step] = [
        submitting({"probability": 0.4}, turn="turn-2"),
        message("Submitted.", turn="turn-2"),
        completed("turn-2"),
    ]
    rig = Rig(tmp_path, [first, second])
    tools = toolbox()
    raw = run(rig, tools)
    once, again = rig.client.sent["turn/start"]
    assert once["input"] == "Will it rain?"
    assert again["threadId"] == "thread-1"
    assert again["input"] == (
        "Call the `submit` tool with your final answer, `blocked` if it can't be "
        "answered, or `stop` to stop by your own choice: your turn can't end until "
        "one is accepted."
    )
    assert len(rig.client.sent["thread/start"]) == 1
    assert tools.accepted() == Forecast(probability=0.4)
    assert tools.refused_endings == 1
    assert raw.text == "Submitted."


def test_an_answered_turn_ends_at_once(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    assert len(rig.client.sent["turn/start"]) == 1


def test_a_friction_and_how_it_felt_reach_the_toolbox_and_end_nothing(
    tmp_path: Path,
) -> None:
    jammed: JsonObject = {"text": "The feed timed out as I read it."}
    turn: list[Step] = [
        calling("friction", jammed, call="call-1"),
        calling("how_it_felt", {"text": "The question was clear."}, call="call-2"),
        *ANSWERED,
    ]
    rig = Rig(tmp_path, [turn])
    tools = toolbox()
    run(rig, tools)
    taken, went, _ = rig.client.answers
    assert taken["success"] is True
    assert went["success"] is True
    assert tools.frictions() == [Friction(text="The feed timed out as I read it.")]
    assert tools.how_it_felt() == [HowItFelt(text="The question was clear.")]
    assert len(rig.client.sent["turn/start"]) == 1


def test_a_turn_the_agent_stops_ends_at_once_and_the_ask_raises(
    tmp_path: Path,
) -> None:
    turn: list[Step] = [
        calling("stop", {"why": "I'd rather not guess."}),
        message("Stopped."),
        completed(),
    ]
    rig = Rig(tmp_path, [turn])
    token = seam.set(On(rig.adapter))
    try:
        with pytest.raises(StoppedError) as raised:
            asyncio.run(
                Codex(model="gpt-6.1-sol", layers=FAST).ask("Will it rain?", Forecast)
            )
    finally:
        seam.reset(token)
    assert raised.value.why == "I'd rather not guess."
    assert len(rig.client.sent["turn/start"]) == 1


def test_a_blocked_turn_ends_at_once_and_the_ask_raises(tmp_path: Path) -> None:
    turn: list[Step] = [
        calling("blocked", {"problem": "No place given."}),
        message("Blocked."),
        completed(),
    ]
    rig = Rig(tmp_path, [turn])
    token = seam.set(On(rig.adapter))
    try:
        with pytest.raises(BlockedError, match="No place given"):
            asyncio.run(
                Codex(model="gpt-6.1-sol", layers=FAST).ask("Will it rain?", Forecast)
            )
    finally:
        seam.reset(token)
    assert len(rig.client.sent["turn/start"]) == 1


def test_an_untyped_turn_ends_with_its_text(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [[message("Bonjour"), completed()]])
    raw = run(rig, toolbox(typed=False), prompt="Translate hello")
    assert raw.text == "Bonjour"
    assert len(rig.client.sent["turn/start"]) == 1


def test_giving_up_stops_the_thread_without_an_answer(tmp_path: Path) -> None:
    unanswered: list[list[Step]] = [
        [message("No."), completed(f"turn-{number}")] for number in [1, 2]
    ]
    rig = Rig(tmp_path, unanswered)
    tools = toolbox(attempts=1)
    run(rig, tools)
    assert len(rig.client.sent["turn/start"]) == 2
    assert tools.accepted() is None


def test_a_question_for_the_user_is_refused(tmp_path: Path) -> None:
    asking = Ask(
        "item/tool/requestUserInput",
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item",
            "isBlocking": True,
            "questions": [{"id": "city", "header": "City", "question": "Which city?"}],
        },
    )
    rig = Rig(tmp_path, [[asking, *ANSWERED]])
    run(rig, toolbox())
    refusal, _ = rig.client.answers
    assert refusal == {
        "answers": {
            "city": {
                "answers": [
                    (
                        "No one can answer here. Carry on with what you have, or call "
                        "`blocked` to say what's missing."
                    )
                ]
            }
        }
    }


def test_any_other_request_from_codex_fails_the_ask(tmp_path: Path) -> None:
    approval = Ask("item/commandExecution/requestApproval", {"threadId": "thread-1"})
    rig = Rig(tmp_path, [[approval, *ANSWERED]])
    with pytest.raises(TurnError, match="item/commandExecution/requestApproval"):
        run(rig, toolbox())
    assert rig.client.log[-1] == "close"


# Usage.


def test_usage_is_the_threads_total_not_a_sum_of_each_request(tmp_path: Path) -> None:
    turn: list[Step] = [
        tokens(total=breakdown(100, 40, 10), last=breakdown(100, 40, 10)),
        tokens(total=breakdown(250, 140, 30), last=breakdown(150, 100, 20)),
        tokens(total=breakdown(250, 140, 30), last=breakdown(150, 100, 20)),
        *ANSWERED,
    ]
    rig = Rig(tmp_path, [turn])
    raw = run(rig, toolbox())
    assert raw.usage.input_tokens == 110
    assert raw.usage.cache_read_tokens == 140
    assert raw.usage.output_tokens == 30
    assert raw.usage.cache_write_tokens == 0
    assert raw.usage.cost_usd is None


def test_usage_spans_every_turn_of_the_thread(tmp_path: Path) -> None:
    first: list[Step] = [
        tokens(breakdown(100, 0, 10), breakdown(100, 0, 10)),
        completed(),
    ]
    second: list[Step] = [
        tokens(breakdown(300, 0, 25), breakdown(200, 0, 15)),
        submitting({"probability": 0.1}, turn="turn-2"),
        completed("turn-2"),
    ]
    rig = Rig(tmp_path, [first, second])
    raw = run(rig, toolbox())
    assert raw.usage.input_tokens == 300
    assert raw.usage.output_tokens == 25


def test_a_turn_reporting_no_usage_used_none(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    assert run(rig, toolbox()).usage == lup.Usage()


# Errors.


@pytest.mark.parametrize(
    "info",
    [
        "serverOverloaded",
        "internalServerError",
        "rateLimitExceeded",
        {"httpConnectionFailed": {"httpStatusCode": 502}},
        {"httpConnectionFailed": {"httpStatusCode": None}},
        {"responseStreamConnectionFailed": {"httpStatusCode": 429}},
        {"responseStreamDisconnected": {}},
        {"responseTooManyFailedAttempts": {"httpStatusCode": 408}},
    ],
)
def test_the_model_out_of_reach_is_unavailable(tmp_path: Path, info: JsonValue) -> None:
    rig = Rig(tmp_path, [[error(info), completed(status="failed")]])
    with pytest.raises(AgentUnavailableError, match="it went wrong"):
        run(rig, toolbox())


@pytest.mark.parametrize(
    "info", ["unauthorized", {"httpConnectionFailed": {"httpStatusCode": 401}}]
)
def test_a_refused_login_is_auth_missing(tmp_path: Path, info: JsonValue) -> None:
    rig = Rig(tmp_path, [[error(info), completed(status="failed")]])
    with pytest.raises(AuthMissingError):
        run(rig, toolbox())


@pytest.mark.parametrize(
    "info",
    [
        "contextWindowExceeded",
        "badRequest",
        "other",
        "somethingCodexAddsLater",
        {"httpConnectionFailed": {"httpStatusCode": 400}},
        None,
    ],
)
def test_any_other_failure_is_a_turn_error(tmp_path: Path, info: JsonValue) -> None:
    rig = Rig(tmp_path, [[error(info), completed(status="failed")]])
    with pytest.raises(TurnError) as raised:
        run(rig, toolbox())
    assert type(raised.value) is TurnError


def test_only_the_error_codex_gave_up_on_is_classified(tmp_path: Path) -> None:
    turn: list[Step] = [
        error("serverOverloaded", will_retry=True),
        error("contextWindowExceeded"),
        completed(status="failed"),
    ]
    rig = Rig(tmp_path, [turn])
    with pytest.raises(TurnError, match="contextWindowExceeded") as raised:
        run(rig, toolbox())
    assert type(raised.value) is TurnError


def test_a_failed_turn_without_an_error_notification_reads_the_turns_own(
    tmp_path: Path,
) -> None:
    failure: JsonObject = {
        "message": "overloaded",
        "codexErrorInfo": "serverOverloaded",
    }
    rig = Rig(tmp_path, [[completed(status="failed", failure=failure)]])
    with pytest.raises(AgentUnavailableError, match="overloaded"):
        run(rig, toolbox())


def test_a_spent_usage_limit_carries_its_reset(tmp_path: Path) -> None:
    reported = limits(
        primary={"usedPercent": 100, "resetsAt": 1791800000, "windowDurationMins": 300},
        secondary={
            "usedPercent": 40,
            "resetsAt": 1792000000,
            "windowDurationMins": 10080,
        },
    )
    turn: list[Step] = [
        Report(reported),
        error("usageLimitExceeded"),
        completed(status="failed"),
    ]
    rig = Rig(tmp_path, [turn])
    with pytest.raises(UsageLimitReachedError) as raised:
        run(rig, toolbox())
    assert raised.value.reset_at == datetime.fromtimestamp(1791800000, UTC)


def test_a_spent_weekly_limit_resets_when_its_own_window_does(tmp_path: Path) -> None:
    reported = limits(
        primary={"usedPercent": 30, "resetsAt": 1791800000},
        secondary={"usedPercent": 100, "resetsAt": 1792000000},
    )
    turn: list[Step] = [
        Report(reported),
        error("usageLimitExceeded"),
        completed(status="failed"),
    ]
    rig = Rig(tmp_path, [turn])
    with pytest.raises(UsageLimitReachedError) as raised:
        run(rig, toolbox())
    assert raised.value.reset_at == datetime.fromtimestamp(1792000000, UTC)


def test_a_usage_limit_without_reported_limits_has_no_reset(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [[error("usageLimitExceeded"), completed(status="failed")]])
    with pytest.raises(UsageLimitReachedError) as raised:
        run(rig, toolbox())
    assert raised.value.reset_at is None


def test_a_turn_interrupted_unasked_is_a_turn_error(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [[completed(status="interrupted")]])
    with pytest.raises(TurnError, match="interrupted"):
        run(rig, toolbox())


def test_a_busy_app_server_is_unavailable(tmp_path: Path) -> None:
    busy = ServerBusyError(-32001, "busy", {"codex_error_info": "server_overloaded"})
    rig = Rig(tmp_path, [ANSWERED], refuse={"thread/start": busy})
    with pytest.raises(AgentUnavailableError) as raised:
        run(rig, toolbox())
    assert raised.value.__cause__ is busy
    assert rig.client.log[-1] == "close"


def test_a_closed_app_server_is_a_turn_error(tmp_path: Path) -> None:
    closed = TransportClosedError("Codex process closed stdout")
    rig = Rig(tmp_path, [ANSWERED], refuse={"thread/start": closed})
    with pytest.raises(TurnError) as raised:
        run(rig, toolbox())
    assert type(raised.value) is TurnError
    assert raised.value.__cause__ is closed


# The login.


def test_lups_home_links_the_operators_login(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    run(rig, toolbox())
    assert rig.layout.login.is_symlink()
    assert rig.layout.login.readlink() == rig.operator / "auth.json"


def test_a_link_to_another_login_is_replaced(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    rig.layout.home.mkdir(parents=True)
    rig.layout.login.symlink_to(tmp_path / "elsewhere" / "auth.json")
    run(rig, toolbox())
    assert rig.layout.login.readlink() == rig.operator / "auth.json"


def test_a_login_of_lups_homes_own_is_left_alone(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    rig.layout.home.mkdir(parents=True)
    rig.layout.login.write_text('{"own": true}')
    run(rig, toolbox())
    assert not rig.layout.login.is_symlink()
    assert rig.layout.login.read_text() == '{"own": true}'


def test_no_login_is_auth_missing_before_the_thread_starts(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path, [ANSWERED], account={"account": None, "requiresOpenaiAuth": True}
    )
    (rig.operator / "auth.json").unlink()
    with pytest.raises(AuthMissingError, match="codex login") as raised:
        run(rig, toolbox())
    assert "doesn't exist" in str(raised.value)
    assert "keyring" in str(raised.value)
    assert "thread/start" not in rig.client.sent
    assert rig.client.log[-1] == "close"


def test_a_provider_needing_no_login_goes_ahead(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path, [ANSWERED], account={"account": None, "requiresOpenaiAuth": False}
    )
    run(rig, toolbox())
    assert "thread/start" in rig.client.sent


def test_the_homes_default_to_xdg_state_and_the_operators_codex_home(
    tmp_path: Path,
) -> None:
    settings = CodexSettings(
        xdg_state_home=tmp_path / "state", codex_home=tmp_path / "mine"
    )
    layout = CodexLayout.of(settings)
    assert layout.home == tmp_path / "state" / "lup" / "codex"
    assert layout.operator_login == tmp_path / "mine" / "auth.json"
    defaults = CodexLayout.of(CodexSettings(xdg_state_home=None, codex_home=None))
    assert defaults.home == Path.home() / ".local" / "state" / "lup" / "codex"
    assert defaults.operator_home == Path.home() / ".codex"


# Cancellation.


def test_cancelling_interrupts_the_turn_then_closes(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [[Stall()]])
    request = TurnRequest(prompt="Will it rain?", toolbox=toolbox(), output=Forecast)

    async def cancel() -> None:
        task = asyncio.create_task(rig.adapter.run(request))
        await asyncio.to_thread(rig.stalled.wait)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert rig.client.sent["turn/interrupt"] == [
        {"threadId": "thread-1", "turnId": "turn-1"}
    ]
    assert rig.client.log[-3:] == ["turn/interrupt", "unregister turn-1", "close"]


# The guard.


def test_a_real_client_is_refused_in_a_test_before_anything_starts(
    tmp_path: Path,
) -> None:
    layout = CodexLayout(home=tmp_path / "home", operator_home=tmp_path / "operator")
    adapter = CodexAdapter(model="gpt-6.1-sol", layout=layout)
    request = TurnRequest(prompt="Will it rain?", toolbox=toolbox(), output=Forecast)
    with pytest.raises(RealCallInTestError, match="fake_agents"):
        asyncio.run(adapter.run(request))
    assert not layout.home.exists()


# The declaration.


class On(Seam):
    """Runs every declaration's asks on one adapter."""

    def __init__(self, adapter: Adapter) -> None:
        self.on = adapter

    def adapter(self, declaration: Declaration) -> Adapter:
        return self.on


FAST = SessionLayers(recovery=Recovery(stop=stop_after_attempt(2), wait=wait_none()))


def test_codex_is_an_agent_with_its_runtimes_fields() -> None:
    codex = Codex(model="gpt-6.1-sol", system_prompt="Be brief.", effort="xhigh")
    assert isinstance(codex, lup.Agent)
    assert codex.runtime == "codex"
    assert codex.effort == "xhigh"
    assert lup.Codex is Codex


def test_codex_asks_through_the_layers(fake_agents: FakeAgents) -> None:
    fake_agents.answer(Forecast, Forecast(probability=0.2))
    result = asyncio.run(Codex(model="gpt-6.1-sol").ask("Will it rain?", Forecast))
    assert result.output == Forecast(probability=0.2)
    [call] = fake_agents.calls
    assert call.declaration.runtime == "codex"


def test_codex_answers_end_to_end_on_the_fake_client(tmp_path: Path) -> None:
    rig = Rig(tmp_path, [ANSWERED])
    token = seam.set(On(rig.adapter))
    try:
        result = asyncio.run(
            Codex(model="gpt-6.1-sol", layers=FAST).ask("Will it rain?", Forecast)
        )
    finally:
        seam.reset(token)
    assert result.output == Forecast(probability=0.3)
    assert result.session_id == "thread-1"


def test_codex_without_an_answer_raises_output_missing(tmp_path: Path) -> None:
    unanswered: list[list[Step]] = [
        [message("No."), completed(f"turn-{number}")] for number in [1, 2, 3, 4]
    ]
    rig = Rig(tmp_path, unanswered)
    token = seam.set(On(rig.adapter))
    try:
        with pytest.raises(OutputMissingError):
            asyncio.run(
                Codex(model="gpt-6.1-sol", layers=FAST).ask("Will it rain?", Forecast)
            )
    finally:
        seam.reset(token)
    assert len(rig.client.sent["turn/start"]) == 4


def test_an_unavailable_model_is_retried_by_recovery(tmp_path: Path) -> None:
    turns: list[list[Step]] = [
        [error("serverOverloaded"), completed(status="failed")],
        ANSWERED,
    ]
    rig = Rig(tmp_path, turns)
    token = seam.set(On(rig.adapter))
    try:
        result = asyncio.run(
            Codex(model="gpt-6.1-sol", layers=FAST).ask("Will it rain?", Forecast)
        )
    finally:
        seam.reset(token)
    assert result.output == Forecast(probability=0.3)
    assert len(rig.made) == 2
