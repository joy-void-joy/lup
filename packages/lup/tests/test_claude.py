"""The Claude adapter, driven by a scripted SDK client: no CLI process, no network, no clock.

The scripted client plays a turn from a list of steps. Messages are yielded as
Claude Code would send them; a tool call goes through the adapter's own MCP server,
over `mcp`'s in-memory client; an attempt to end the turn calls the adapter's own
`Stop` hook. So everything but the CLI is real.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, override

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLINotFoundError,
    HookJSONOutput,
    Message,
    ProcessError,
    RateLimitEvent,
    RateLimitInfo,
    ResultError,
    ResultMessage,
    StopHookInput,
    SystemMessage,
    TextBlock,
)
from mcp import Client
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel
from tenacity import stop_after_attempt, wait_none

import lup
from lup import (
    AgentUnavailableError,
    AuthMissingError,
    BlockedError,
    Friction,
    HowItWent,
    OutputMissingError,
    Recovery,
    RuntimeMissingError,
    SessionLayers,
    StoppedError,
    Submission,
    ToolsPresentError,
    TurnError,
    TurnTimeoutError,
    Usage,
    UsageLimitReachedError,
)
from lup.adapters.claude import Claude
from lup.adapters.claude import runtime as claude_runtime
from lup.adapters.claude.runtime import ClaudeAdapter
from lup.sessions.contract import TurnRequest, seam
from lup.sessions.declaration import Asking
from lup.sessions.errors import RealCallInTestError
from lup.sessions.submission import Toolbox
from lup.tools.speaking import SPEAKING
from lup.tools.submit import Submit

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterator

    from claude_agent_sdk.types import AssistantMessageError, RateLimitStatus
    from mcp.server import Server

    from lup.testing import FakeAgents
    from lup.tools.tool import AgentTool


class Forecast(BaseModel):
    probability: float


# The script's steps, beside the messages it yields as they are.


class Call(BaseModel):
    """The model calls one of lup's tools, by the name the server gives it."""

    name: str
    arguments: dict[str, Any]


class Listing(BaseModel):
    """Claude Code asks lup's server for its tools."""


class Stop(BaseModel):
    """The model tries to end its turn, so Claude Code runs the `Stop` hook."""


class Hang(BaseModel):
    """The model never answers."""


class Raise(BaseModel, arbitrary_types_allowed=True):
    """The SDK raises while the turn's messages are read."""

    error: Exception


type Step = Message | Call | Listing | Stop | Hang | Raise


class Scripted(ClaudeSDKClient):
    """An SDK client that plays a turn from a script instead of starting Claude Code."""

    def __init__(
        self,
        options: ClaudeAgentOptions,
        script: list[Step],
        *,
        refused: Exception | None,
        hanging: asyncio.Event,
    ) -> None:
        super().__init__(options)
        self.script = script
        self.refused = refused
        self.hanging = hanging
        self.prompts: list[str] = []
        self.connected = False
        self.disconnected = False
        self.interrupts = 0
        self.listed: list[Tool] = []
        self.answers: list[CallToolResult] = []
        self.stops: list[HookJSONOutput] = []

    @override
    async def connect(
        self, prompt: str | AsyncIterable[dict[str, Any]] | None = None
    ) -> None:
        if self.refused is not None:
            raise self.refused
        self.connected = True

    @override
    async def disconnect(self) -> None:
        self.disconnected = True

    @override
    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = "default"
    ) -> None:
        assert isinstance(prompt, str)
        self.prompts.append(prompt)

    @override
    async def interrupt(self) -> None:
        self.interrupts += 1

    @override
    async def receive_response(self) -> AsyncIterator[Message]:
        for step in self.script:
            match step:
                case Listing():
                    async with Client(self.server(), mode="legacy") as mcp:
                        self.listed = (await mcp.list_tools()).tools
                case Call(name=name, arguments=arguments):
                    async with Client(self.server(), mode="legacy") as mcp:
                        self.answers.append(await mcp.call_tool(name, arguments))
                case Stop():
                    self.stops.append(await self.stop())
                case Hang():
                    self.hanging.set()
                    await asyncio.Event().wait()
                case Raise(error=error):
                    raise error
                case message:
                    yield message

    def server(self) -> Server:
        servers = self.options.mcp_servers
        assert isinstance(servers, dict)
        config = servers["lup"]
        assert config.get("type") == "sdk"
        assert "instance" in config
        return config["instance"]

    async def stop(self) -> HookJSONOutput:
        hooks = self.options.hooks
        assert hooks is not None
        [matcher] = hooks["Stop"]
        [hook] = matcher.hooks
        event: StopHookInput = {
            "hook_event_name": "Stop",
            "stop_hook_active": bool(self.stops),
            "session_id": "session-1",
            "transcript_path": "",
            "cwd": "/",
        }
        return await hook(event, None, {"signal": None})


class Clients:
    """Hands the adapter a scripted client per turn, and keeps each one."""

    def __init__(self, *scripts: list[Step], refused: Exception | None = None) -> None:
        self.scripts = list(scripts)
        self.refused = refused
        self.hanging = asyncio.Event()
        """Set once a client reaches a `Hang` step."""
        self.made: list[Scripted] = []

    def client(self, options: ClaudeAgentOptions) -> ClaudeSDKClient:
        script = self.scripts.pop(0) if self.scripts else []
        client = Scripted(options, script, refused=self.refused, hanging=self.hanging)
        self.made.append(client)
        return client

    def only(self) -> Scripted:
        [client] = self.made
        return client


UNTYPED_TOOLS = [f"mcp__lup__{tool.spec().name}" for tool in SPEAKING]
TYPED_TOOLS = [*UNTYPED_TOOLS, "mcp__lup__submit"]
USAGE = {
    "input_tokens": 12,
    "output_tokens": 34,
    "cache_read_input_tokens": 56,
    "cache_creation_input_tokens": 78,
    "service_tier": "standard",
}


def init(
    tools: list[str] | None = None, servers: list[str] | None = None
) -> SystemMessage:
    """The session's first message, listing what it loaded, as Claude Code sends it."""
    return SystemMessage(
        subtype="init",
        data={
            "type": "system",
            "subtype": "init",
            "tools": TYPED_TOOLS if tools is None else tools,
            "mcp_servers": [
                {"name": name, "status": "connected", "source": "sdk"}
                for name in (servers or ["lup"])
            ],
            "skills": ["update-config"],
            "plugins": [],
            "agents": ["general-purpose"],
            "slash_commands": ["compact", "review"],
            "model": "claude-opus",
            "permissionMode": "dontAsk",
        },
    )


def said(
    text: str = "", error: AssistantMessageError | None = None
) -> AssistantMessage:
    return AssistantMessage(
        content=[TextBlock(text=text)], model="claude-opus", error=error
    )


def limit(status: RateLimitStatus, resets_at: int | None = None) -> RateLimitEvent:
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, resets_at=resets_at),
        uuid="event-1",
        session_id="session-1",
    )


def result(
    text: str = "",
    *,
    is_error: bool = False,
    subtype: str = "success",
    status: int | None = None,
    reason: str | None = "completed",
    errors: list[str] | None = None,
    session: str = "session-1",
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=8,
        is_error=is_error,
        num_turns=1,
        session_id=session,
        total_cost_usd=0.25,
        usage=USAGE,
        result=text,
        errors=errors,
        api_error_status=status,
        terminal_reason=reason,
    )


def failed(status: int | None, error: AssistantMessageError | None) -> list[Step]:
    """A turn whose API call failed, as Claude Code reports one."""
    return [
        init(),
        said(f"API Error: {status}", error),
        result(
            f"API Error: {status}", is_error=True, status=status, reason="api_error"
        ),
    ]


def request(
    output: type[BaseModel] | None = Forecast,
    attempts: int = 3,
    prompt: str = "Will it rain?",
) -> TurnRequest:
    submit = None if output is None else Submit(output)
    tools: list[AgentTool] = SPEAKING if submit is None else [*SPEAKING, submit]
    toolbox = Toolbox(
        tools=tools,
        output=None if submit is None else submit.name,
        attempts=attempts,
    )
    return TurnRequest(prompt=prompt, toolbox=toolbox, output=output)


def adapter(clients: Clients) -> ClaudeAdapter:
    return ClaudeAdapter(model="opus", client=clients.client)


FAST = SessionLayers(recovery=Recovery(stop=stop_after_attempt(3), wait=wait_none()))


def asking(clients: Clients, layers: SessionLayers = FAST) -> Asking:
    """An ask of a `Claude` declaration, run on the adapter with scripted clients."""
    declaration = Claude(model="opus", layers=layers)
    return Asking(declaration=declaration, runtime_adapter=adapter(clients))


@pytest.fixture
def unseamed() -> Iterator[None]:
    """Run declarations on their runtime's own adapter, as outside a test."""
    token = seam.set(None)
    yield
    seam.reset(token)


# The options a session is given.


def test_a_session_gets_lup_s_tools_and_nothing_of_the_operator_s() -> None:
    clients = Clients([init(), result("It will.")])
    claude = ClaudeAdapter(
        model="opus",
        system_prompt="You forecast.",
        effort="low",
        client=clients.client,
    )
    asyncio.run(claude.run(request()))
    client = clients.only()
    options = client.options
    assert options.model == "opus"
    assert options.system_prompt == "You forecast."
    assert options.effort == "low"
    assert options.tools == []
    assert options.allowed_tools == TYPED_TOOLS
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.skills == []
    assert options.plugins == []
    assert options.verbatim_prompts is True
    assert options.env == {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    assert options.extra_args == {"no-session-persistence": None}
    assert isinstance(options.mcp_servers, dict)
    assert list(options.mcp_servers) == ["lup"]
    assert options.hooks is not None
    assert list(options.hooks) == ["Stop"]
    assert client.prompts == ["Will it rain?"]
    assert client.connected
    assert client.disconnected


def test_an_untyped_session_has_no_output_tool_and_keeps_the_defaults() -> None:
    clients = Clients([init(tools=UNTYPED_TOOLS), result("Bonjour")])
    asyncio.run(adapter(clients).run(request(None)))
    options = clients.only().options
    assert options.allowed_tools == UNTYPED_TOOLS
    assert options.system_prompt is None
    assert options.effort is None


def test_a_session_with_no_model_leaves_it_to_claude_code() -> None:
    clients = Clients([init(), result("It will.")])
    asyncio.run(ClaudeAdapter(client=clients.client).run(request()))
    assert clients.only().options.model is None


# lup's tools, served by its own MCP server.


def test_the_server_lists_each_tool_with_its_schema() -> None:
    clients = Clients([init(), Listing(), result()])
    asyncio.run(adapter(clients).run(request()))
    listed = clients.only().listed
    assert [tool.name for tool in listed] == [
        "blocked",
        "stop",
        "note",
        "friction",
        "how_it_went",
        "submit",
    ]
    [submit] = [tool for tool in listed if tool.name == "submit"]
    assert submit.input_schema == Forecast.model_json_schema()
    assert submit.description == Submit(Forecast).description


def test_each_call_reaches_the_toolbox_which_validates_it() -> None:
    clients = Clients(
        [
            init(),
            Call(name="submit", arguments={"probability": "high"}),
            Call(name="submit", arguments={"probability": 0.3}),
            Stop(),
            result(),
        ]
    )
    turn = request()
    asyncio.run(adapter(clients).run(turn))
    refused, accepted = clients.only().answers
    assert refused.is_error
    [refusal] = refused.content
    assert isinstance(refusal, TextContent)
    assert refusal.text.startswith("Refused: ")
    assert not accepted.is_error
    [rejection] = turn.toolbox.rejected()
    assert rejection.submitted == {"probability": "high"}
    assert turn.toolbox.accepted() == Forecast(probability=0.3)


def test_a_note_is_taken_through_the_server() -> None:
    clients = Clients(
        [
            init(tools=UNTYPED_TOOLS),
            Call(name="note", arguments={"remark": "Assumes London."}),
            result(),
        ]
    )
    turn = request(None)
    asyncio.run(adapter(clients).run(turn))
    assert turn.toolbox.notes() == ["Assumes London."]


def test_a_friction_and_how_it_went_are_taken_through_the_server() -> None:
    jammed = {"text": "The feed timed out; a retry would have saved it."}
    clients = Clients(
        [
            init(tools=UNTYPED_TOOLS),
            Call(name="friction", arguments=jammed),
            Call(name="how_it_went", arguments={"text": "Calm."}),
            result(),
        ]
    )
    turn = request(None)
    asyncio.run(adapter(clients).run(turn))
    taken, went = clients.only().answers
    assert not taken.is_error
    assert not went.is_error
    assert turn.toolbox.frictions() == [
        Friction(text="The feed timed out; a retry would have saved it.")
    ]
    assert turn.toolbox.how_it_went() == HowItWent(text="Calm.")


# The Stop hook: the turn's guard.


def test_the_stop_hook_lets_an_answered_turn_end() -> None:
    clients = Clients(
        [init(), Call(name="submit", arguments={"probability": 0.3}), Stop(), result()]
    )
    asyncio.run(adapter(clients).run(request()))
    assert clients.only().stops == [{}]


def test_the_stop_hook_keeps_an_unanswered_turn_going_saying_why() -> None:
    clients = Clients(
        [
            init(),
            Stop(),
            Call(name="submit", arguments={"probability": 0.3}),
            Stop(),
            result(),
        ]
    )
    turn = request()
    asyncio.run(adapter(clients).run(turn))
    blocked, ended = clients.only().stops
    assert blocked == {
        "decision": "block",
        "reason": (
            "Call the `mcp__lup__submit` tool with your final answer, "
            "`mcp__lup__blocked` if it can't be answered, or `mcp__lup__stop` to stop "
            "by your own choice: your turn can't end until one is accepted."
        ),
    }
    assert ended == {}
    assert turn.toolbox.refused_endings == 1


@pytest.mark.usefixtures("unseamed")
def test_the_stop_hook_gives_up_past_the_attempts_and_the_ask_raises() -> None:
    clients = Clients([init(), Stop(), Stop(), result("I can't.")])
    layers = FAST.model_copy(update={"submission": Submission(attempts=1)})
    with pytest.raises(OutputMissingError):
        asyncio.run(asking(clients, layers).ask("Will it rain?", Forecast))
    blocked, let_go = clients.only().stops
    assert blocked.get("decision") == "block"
    assert let_go == {}


@pytest.mark.usefixtures("unseamed")
def test_the_stop_hook_lets_a_turn_end_once_the_agent_stops_and_the_ask_raises() -> (
    None
):
    clients = Clients(
        [
            init(),
            Call(name="friction", arguments={"text": "No date given."}),
            Call(name="stop", arguments={"why": "I'd rather not guess."}),
            Stop(),
            result("Stopped."),
        ]
    )
    with pytest.raises(StoppedError) as raised:
        asyncio.run(asking(clients).ask("Will it rain?", Forecast))
    assert clients.only().stops == [{}]
    assert raised.value.why == "I'd rather not guess."
    assert raised.value.frictions == [Friction(text="No date given.")]


@pytest.mark.usefixtures("unseamed")
def test_the_stop_hook_lets_a_blocked_turn_end_and_the_ask_raises() -> None:
    clients = Clients(
        [
            init(),
            Call(name="blocked", arguments={"problem": "No place given."}),
            Stop(),
            result("Blocked."),
        ]
    )
    with pytest.raises(BlockedError, match="No place given"):
        asyncio.run(asking(clients).ask("Will it rain?", Forecast))
    assert clients.only().stops == [{}]


# The tool check.


def test_a_built_in_tool_stops_the_call_before_the_model_runs() -> None:
    clients = Clients(
        [init(tools=[*TYPED_TOOLS, "Bash"]), said("ran a command"), result("done")]
    )
    with pytest.raises(ToolsPresentError, match="Bash") as raised:
        asyncio.run(adapter(clients).run(request()))
    assert raised.value.tools == [*TYPED_TOOLS, "Bash"]
    client = clients.only()
    assert client.interrupts == 1
    assert client.disconnected


def test_another_mcp_server_stops_the_call() -> None:
    clients = Clients([init(servers=["lup", "github"]), result()])
    with pytest.raises(ToolsPresentError, match="github"):
        asyncio.run(adapter(clients).run(request()))
    assert clients.only().interrupts == 1


def test_skills_agents_and_commands_listed_without_a_tool_to_call_them_pass() -> None:
    clients = Clients([init(), result("fine")])
    raw = asyncio.run(adapter(clients).run(request()))
    assert raw.text == "fine"
    assert clients.only().interrupts == 0


def test_a_turn_whose_tools_were_never_listed_raises() -> None:
    clients = Clients([said("hi"), result("hi")])
    with pytest.raises(TurnError, match="weren't checked"):
        asyncio.run(adapter(clients).run(request()))


def test_a_failed_turn_says_why_even_when_its_tools_were_never_listed() -> None:
    clients = Clients(failed(None, "authentication_failed")[1:])
    with pytest.raises(AuthMissingError):
        asyncio.run(adapter(clients).run(request()))


def test_a_turn_that_ends_without_a_result_raises() -> None:
    clients = Clients([init(), said("partial")])
    with pytest.raises(TurnError, match="without a result"):
        asyncio.run(adapter(clients).run(request()))


# Errors, classified from structured fields.


def test_an_overloaded_api_is_unavailable() -> None:
    clients = Clients(failed(529, "server_error"))
    with pytest.raises(AgentUnavailableError):
        asyncio.run(adapter(clients).run(request()))


def test_a_rate_limited_api_is_unavailable() -> None:
    clients = Clients(failed(429, "rate_limit"))
    with pytest.raises(AgentUnavailableError):
        asyncio.run(adapter(clients).run(request()))


def test_a_dropped_connection_is_unavailable() -> None:
    clients = Clients(failed(None, "unknown"))
    with pytest.raises(AgentUnavailableError):
        asyncio.run(adapter(clients).run(request()))


@pytest.mark.usefixtures("unseamed")
def test_an_unavailable_api_is_retried_by_the_ask() -> None:
    clients = Clients(
        failed(529, "server_error"),
        [init(), Call(name="submit", arguments={"probability": 0.2}), Stop(), result()],
    )
    answer = asyncio.run(asking(clients).ask("Will it rain?", Forecast))
    assert answer.output == Forecast(probability=0.2)
    assert len(clients.made) == 2


def test_a_spent_usage_window_carries_its_reset() -> None:
    script: list[Step] = [
        init(),
        limit("rejected", 1791800000),
        *failed(429, "rate_limit")[1:],
    ]
    clients = Clients(script)
    with pytest.raises(UsageLimitReachedError) as raised:
        asyncio.run(adapter(clients).run(request()))
    assert raised.value.reset_at == datetime(2026, 10, 12, 10, 13, 20, tzinfo=UTC)


def test_a_rejected_window_that_lets_the_turn_finish_is_no_error() -> None:
    clients = Clients([init(), limit("rejected", 1791800000), result("fine")])
    raw = asyncio.run(adapter(clients).run(request()))
    assert raw.text == "fine"


def test_a_refused_key_is_a_missing_login() -> None:
    clients = Clients(failed(401, "authentication_failed"))
    with pytest.raises(AuthMissingError):
        asyncio.run(adapter(clients).run(request()))


def test_no_login_at_all_is_a_missing_login_though_no_status_came() -> None:
    clients = Clients(failed(None, "authentication_failed"))
    with pytest.raises(AuthMissingError):
        asyncio.run(adapter(clients).run(request()))


def test_a_refused_request_is_a_plain_turn_error_carrying_what_was_reported() -> None:
    clients = Clients(
        [
            init(),
            said("API Error: 400", "invalid_request"),
            result(
                "API Error: 400 prompt is too long",
                is_error=True,
                status=400,
                reason="api_error",
            ),
        ]
    )
    with pytest.raises(TurnError, match="prompt is too long") as raised:
        asyncio.run(adapter(clients).run(request()))
    assert type(raised.value) is TurnError


def test_a_missing_cli_is_a_missing_runtime() -> None:
    clients = Clients([], refused=CLINotFoundError("Claude Code not found"))
    with pytest.raises(RuntimeMissingError):
        asyncio.run(adapter(clients).run(request()))


def test_an_error_result_raised_by_the_sdk_is_classified_too() -> None:
    raised_by_sdk = ResultError(
        "Claude Code returned an error result",
        data={
            "subtype": "success",
            "api_error_status": 529,
            "terminal_reason": "api_error",
        },
    )
    clients = Clients([init(), Raise(error=raised_by_sdk)])
    with pytest.raises(AgentUnavailableError):
        asyncio.run(adapter(clients).run(request()))
    assert clients.only().disconnected


def test_a_failed_cli_process_is_a_turn_error() -> None:
    clients = Clients([init(), Raise(error=ProcessError("CLI crashed", exit_code=137))])
    with pytest.raises(TurnError, match="CLI crashed"):
        asyncio.run(adapter(clients).run(request()))


# What a turn reports.


def test_usage_cost_text_and_session_are_read_off_the_result() -> None:
    clients = Clients(
        [init(tools=UNTYPED_TOOLS), result("It will rain.", session="session-42")]
    )
    raw = asyncio.run(adapter(clients).run(request(None)))
    assert raw.text == "It will rain."
    assert raw.session_id == "session-42"
    assert raw.usage == Usage(
        input_tokens=12,
        output_tokens=34,
        cache_read_tokens=56,
        cache_write_tokens=78,
        cost_usd=0.25,
    )


@pytest.mark.usefixtures("unseamed")
def test_a_typed_ask_comes_back_whole() -> None:
    clients = Clients(
        [
            init(),
            Call(name="submit", arguments={"probability": "high"}),
            Call(name="note", arguments={"remark": "Assumes London."}),
            Call(name="submit", arguments={"probability": 0.7}),
            Stop(),
            result("Submitted.", session="session-7"),
        ]
    )
    answer = asyncio.run(asking(clients).ask("Will it rain?", Forecast))
    assert answer.output == Forecast(probability=0.7)
    assert [each.submitted for each in answer.rejected] == [{"probability": "high"}]
    assert answer.notes == ["Assumes London."]
    assert answer.session_id == "session-7"
    assert answer.usage.cost_usd == 0.25


# Cancellation.


def test_a_cancelled_turn_is_interrupted_then_cancelled() -> None:
    clients = Clients([init(), Hang()])

    async def cancelled() -> None:
        running = asyncio.create_task(adapter(clients).run(request()))
        await clients.hanging.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(cancelled())
    client = clients.only()
    assert client.interrupts == 1
    assert client.disconnected


@pytest.mark.usefixtures("unseamed")
def test_the_timeout_interrupts_the_turn() -> None:
    clients = Clients([init(), Hang()])
    layers = FAST.model_copy(update={"timeout": timedelta(0)})
    with pytest.raises(TurnTimeoutError):
        asyncio.run(asking(clients, layers).ask("Will it rain?", Forecast))
    assert clients.only().interrupts == 1


# The guard.


def test_a_real_client_is_refused_in_a_test_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[ClaudeAgentOptions] = []

    def recording(options: ClaudeAgentOptions) -> ClaudeSDKClient:
        started.append(options)
        return ClaudeSDKClient(options)

    monkeypatch.setattr(claude_runtime, "ClaudeSDKClient", recording)
    with pytest.raises(RealCallInTestError, match="fake_agents"):
        asyncio.run(ClaudeAdapter(model="opus").run(request()))
    assert started == []


@pytest.mark.usefixtures("unseamed")
def test_a_declaration_on_its_own_adapter_is_refused_in_a_test() -> None:
    with pytest.raises(RealCallInTestError):
        asyncio.run(Claude(model="opus").ask("hello"))


def test_a_declaration_without_the_fake_is_refused() -> None:
    with pytest.raises(RealCallInTestError):
        asyncio.run(Claude(model="opus").ask("hello"))


def test_a_declaration_answers_from_the_fake(fake_agents: FakeAgents) -> None:
    fake_agents.answer(Forecast, Forecast(probability=0.4))
    answer = asyncio.run(
        Claude(model="opus", effort="high").ask("Will it rain?", Forecast)
    )
    assert answer.output == Forecast(probability=0.4)
    [call] = fake_agents.calls
    assert call.declaration == Claude(model="opus", effort="high")


def test_the_front_door_loads_the_declaration() -> None:
    assert lup.Claude is Claude
