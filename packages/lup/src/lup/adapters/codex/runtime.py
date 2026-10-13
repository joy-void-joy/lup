"""Codex's side of an ask: an app-server session through the `openai-codex` SDK.

Each ask starts a `codex app-server` process of its own, under lup's own Codex home
(`layout.py`), and runs on one thread of it:
- **No tools but lup's.** The thread is ephemeral, so it persists nothing. It has
  no environment (`environments: []`), so no shell and no file tools, and Codex's
  own subagents are off. The launch turns off web search, skills, every built-in
  feature that brings a tool, and the instructions describing them (`LAUNCH`).
  Approvals are never asked, and the sandbox is read-only.
- **lup's tools** are the thread's dynamic tools, set once for its life. Codex sends
  each call to the client as an `item/tool/call` request, which the SDK hands to
  a handler on its one reader thread; the handler passes the call to the event
  loop the ask runs on and waits for the toolbox's answer. The loop stays free
  for it because every blocking client call runs in a worker thread.
- **The guard.** Codex's hooks are commands configured in files, not callbacks,
  so the end of a turn is guarded here: once a turn completes, the toolbox says
  whether it may end, and where it may not, the same thread takes another turn
  whose one message is the toolbox's reason. The thread keeps its history, so
  the prompt isn't sent again.
- **Errors** are classified from the `codexErrorInfo` of the last error Codex
  reported without retrying it, never from its message. A spent usage window's
  reset is the one the last `account/rateLimits/updated` notification gave.
- **Usage** is the thread's running total once its turns are done; the thread is
  the ask's own, so the total started at zero. Codex reports no cost.
- **Cancellation**, as when the timeout layer's time passes, interrupts the turn
  before the cancellation goes on. The process is closed either way.

What this relies on, from `openai-codex` 0.162.0 and the app-server it pins, read in
their source and checked against a local mock of the Responses endpoint:
- the documented `Codex` and `AsyncCodex` clients take no handler for Codex's
  requests, so this drives the SDK's lower `CodexClient`. Its handler runs on the
  reader thread and blocks all routing while it runs; whatever it raises ends the
  client, and every waiter, the turn's stream among them, raises it in turn;
- `baseInstructions` replaces Codex's own prompt and arrives as the first developer
  message; left out, Codex sends its own coding agent's prompt, and empty, no
  developer message at all;
- reasoning effort is a `turn/start` setting, not a `thread/start` one;
- `thread/tokenUsage/updated` fires for each model request and again on turns that
  made none, so the running `total` is what a thread used, not a sum of `last`;
- before a usage limit's error, Codex reports the rate limits that came with it
  (`core/src/turn.rs`), and the SDK delivers that report outside any turn, through
  `next_notification`. It reaches the session's watcher thread first, which keeps
  it; the threads aren't synchronised, so a reset can in principle be missed;
- **code mode.** On models whose catalog entry says `tool_mode: code_mode_only`, the
  default `gpt-6.1-sol` among them, every tool, lup's included, is reached through
  a JavaScript `exec` tool, beside `wait` and `request_user_input_async`, and no
  setting removes them. An `exec` call trying each way out found it runs in a V8
  isolate with no `fetch`, `require`, `process` or `WebAssembly`, refuses every
  import, and has for nested tools only lup's, a clock, and MCP's resource readers,
  which read nothing without an MCP server. `request_user_input_async` only queues
  a question, with no request to the client. So code mode can't reach a shell,
  files, the network or another agent, and its host stays on: without it, lup's
  tools are out of reach on those models;
- **declared gap.** Codex has no API listing a session's tools, so a live check,
  run by hand when the pinned version changes, confirms the model's request
  carries only lup's tools.
"""

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, override

from openai_codex.client import ApprovalHandler, CodexClient, CodexConfig
from openai_codex.errors import CodexError, ServerBusyError
from openai_codex.generated import v2_all as wire
from pydantic import Field, JsonValue
from pydantic.alias_generators import to_camel

from lup.adapters.codex import Effort
from lup.adapters.codex.layout import CodexLayout
from lup.adapters.codex.settings import CodexSettings
from lup.sessions.contract import Adapter, RawTurn, TurnRequest, guarded
from lup.sessions.errors import (
    AgentUnavailableError,
    AuthMissingError,
    RealCallInTestError,
    TurnError,
    UsageLimitReachedError,
)
from lup.sessions.results import Usage
from lup.sessions.submission import End, GiveUp, KeepGoing, Toolbox
from lup.tools.speaking import report
from lup.types import JsonObject, Model, MutableModel

if TYPE_CHECKING:
    from openai_codex import models as sdk

type Connect = Callable[[CodexConfig, ApprovalHandler], CodexClient]
"""Make the client an ask runs on, from its launch and the handler of Codex's requests."""

LAUNCH: dict[str, str | bool] = {
    "web_search": "disabled",
    "skills.include_instructions": False,
    "skills.bundled.enabled": False,
    "include_environment_context": False,
    "include_permissions_instructions": False,
    "include_apps_instructions": False,
    "include_collaboration_mode_instructions": False,
    "tools.experimental_request_user_input.enabled": False,
    **{
        f"features.{feature}": False
        for feature in [
            "goals",
            "sleep_tool",
            "image_generation",
            "multi_agent",
            "apps",
            "plugins",
            "remote_plugin",
            "skill_search",
            "tool_suggest",
            "view_image",
            "browser_use",
            "computer_use",
            "shell_tool",
            "unified_exec",
            "hooks",
            "workspace_dependencies",
        ]
    },
    "cli_auth_credentials_store": "file",
}
"""The configuration every app-server starts with, each entry a `--config` override.

Web search, skills, each built-in feature that brings a tool, and the instructions
describing them are off. The code-mode host stays on (see above). Credentials are
kept in a file: under `keyring` or `auto`, a token refresh deletes `auth.json`,
which in lup's home is the link to the operator's login.
"""


class Wire(Model, alias_generator=to_camel, populate_by_name=True):
    """A message of Codex's app-server protocol, its fields in camel case."""

    def sent(self) -> sdk.JsonObject:
        """Return the message as the client sends it."""
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)


class DynamicTool(Wire):
    """One of lup's tools, as a thread declares it to Codex."""

    type: Literal["function"] = "function"
    name: str
    description: str
    input_schema: JsonObject


class ThreadStart(Wire):
    """The `thread/start` request: an ephemeral thread with lup's tools and nothing else."""

    model: str
    base_instructions: str
    dynamic_tools: list[DynamicTool]
    ephemeral: bool = True
    """Persist nothing: no history, no resume list."""
    environments: list[JsonObject] = []
    """No environment, so no shell and no file tools."""
    approval_policy: Literal["never"] = "never"
    sandbox: Literal["read-only"] = "read-only"
    config: JsonObject = {"agents": {"enabled": False}}
    """Codex's own subagents off."""


class TurnSettings(Wire):
    """What each `turn/start` sets beside its input."""

    effort: Effort | None = None


class Thread(Wire):
    """The thread `thread/start` started."""

    id: str


class Started(Wire):
    """The `thread/start` answer."""

    thread: Thread


class Account(Wire):
    """The `account/read` answer: the login Codex found, if any, and whether it needs one."""

    account: JsonObject | None = None
    requires_openai_auth: bool


class ToolCall(Wire):
    """Codex's `item/tool/call` request: the model calling one of lup's tools."""

    tool: str
    arguments: JsonValue = None


class InputText(Wire):
    """Text a tool's answer carries back to the model."""

    type: Literal["inputText"] = "inputText"
    text: str


class ToolAnswer(Wire):
    """The answer to an `item/tool/call` request."""

    content_items: list[InputText]
    success: bool


class Question(Wire):
    """One question the model asks the user."""

    id: str


class UserInputRequest(Wire):
    """Codex's `item/tool/requestUserInput` request: the model asking the user."""

    questions: list[Question]


class Answers(Wire):
    """The answers given to one question."""

    answers: list[str]


class UserInputAnswer(Wire):
    """The answer to an `item/tool/requestUserInput` request, by question."""

    answers: dict[str, Answers]


def app_server(config: CodexConfig, serve: ApprovalHandler) -> CodexClient:
    """Return a client for Codex's own app-server, unless real turns are refused, as in tests."""
    if guarded.get():
        message = (
            "a test reached Codex's real app-server; ask for the `fake_agents` "
            "fixture and script the answer with `fake_agents.answer(...)`"
        )
        raise RealCallInTestError(message)
    return CodexClient(config, approval_handler=serve)


def serving(toolbox: Toolbox, loop: asyncio.AbstractEventLoop) -> ApprovalHandler:
    """Return the handler of Codex's requests to the client: calls to lup's tools.

    It runs on the SDK's reader thread, so it hands each call to `loop`, where the
    toolbox lives, and waits for the answer. A question for the user gets a refusal,
    since no one is there to answer it. Any other request means Codex reached for
    something an ask never allows; raising it ends the client, and the ask with it.
    """

    def serve(method: str, params: sdk.JsonObject | None) -> sdk.JsonObject:
        match method:
            case "item/tool/call":
                call = ToolCall.model_validate(params)
                answering = toolbox.call(call.tool, call.arguments)
                answer = asyncio.run_coroutine_threadsafe(answering, loop).result()
                text = InputText(text=answer.text)
                return ToolAnswer(content_items=[text], success=not answer.error).sent()
            case "item/tool/requestUserInput":
                asked = UserInputRequest.model_validate(params)
                refused = (
                    "No one can answer here. Carry on with what you have, or call "
                    f"`{report.name}` to say what's missing."
                )
                refusal = Answers(answers=[refused])
                answers = {question.id: refusal for question in asked.questions}
                return UserInputAnswer(answers=answers).sent()
            case _:
                message = (
                    f"Codex asked lup's client to answer `{method}`, which an ask "
                    "with no tools but lup's own never needs"
                )
                raise TurnError(message)

    return serve


def resets(limits: wire.RateLimitSnapshot | None) -> datetime | None:
    """Return when the spent usage window resets, as Codex last reported it.

    That's the latest reset of the windows reported full, or the primary window's
    where none is.
    """
    if limits is None:
        return None
    windows = [
        window for window in [limits.primary, limits.secondary] if window is not None
    ]
    spent = [
        window.resets_at
        for window in windows
        if window.used_percent >= 100 and window.resets_at is not None
    ]
    if spent:
        return datetime.fromtimestamp(max(spent), UTC)
    primary = limits.primary
    if primary is None or primary.resets_at is None:
        return None
    return datetime.fromtimestamp(primary.resets_at, UTC)


def classified(
    failure: wire.TurnError | None, limits: wire.RateLimitSnapshot | None
) -> TurnError:
    """Return the error a failed turn raises, by the `codexErrorInfo` Codex gave it.

    Overload, a server error, a rate limit, and a connection that failed or dropped
    with no status, a 408, a 429 or a 5xx, are the model out of reach for a while,
    which the recovery layer retries. A 401 or `unauthorized` is a refused login.
    Anything else (a full context window, a bad request, a policy, an unknown
    kind) fails the ask as it is.
    """
    if failure is None:
        return TurnError("Codex failed the turn without saying why")
    said = failure.message
    info = failure.codex_error_info
    kind = "no kind" if info is None else info.model_dump_json(by_alias=True)
    match None if info is None else info.root:
        case (
            wire.CodexErrorInfoValue.server_overloaded
            | wire.CodexErrorInfoValue.internal_server_error
            | wire.CodexErrorInfoValue.rate_limit_exceeded
        ):
            return AgentUnavailableError(
                f"Codex couldn't reach its model ({kind}): {said}"
            )
        case wire.CodexErrorInfoValue.usage_limit_exceeded:
            message = f"the Codex account's usage limit is reached ({kind}): {said}"
            return UsageLimitReachedError(message, reset_at=resets(limits))
        case wire.CodexErrorInfoValue.unauthorized:
            return AuthMissingError(f"Codex's login was refused ({kind}): {said}")
        case (
            wire.HttpConnectionFailedCodexErrorInfo(
                http_connection_failed=wire.HttpConnectionFailed(
                    http_status_code=status
                )
            )
            | wire.ResponseStreamConnectionFailedCodexErrorInfo(
                response_stream_connection_failed=wire.ResponseStreamConnectionFailed(
                    http_status_code=status
                )
            )
            | wire.ResponseStreamDisconnectedCodexErrorInfo(
                response_stream_disconnected=wire.ResponseStreamDisconnected(
                    http_status_code=status
                )
            )
            | wire.ResponseTooManyFailedAttemptsCodexErrorInfo(
                response_too_many_failed_attempts=wire.ResponseTooManyFailedAttempts(
                    http_status_code=status
                )
            )
        ):
            if status is None or status >= 500 or status in [408, 429]:
                return AgentUnavailableError(
                    f"Codex couldn't reach its model ({kind}): {said}"
                )
            if status == 401:
                return AuthMissingError(f"Codex's login was refused ({kind}): {said}")
            return TurnError(f"Codex's model refused the request ({kind}): {said}")
        case _:
            return TurnError(f"Codex failed the turn ({kind}): {said}")


class Session(MutableModel, arbitrary_types_allowed=True):
    """One ask's app-server session: its client, its thread, and what its turns reported."""

    client: CodexClient
    thread: str
    text: str = ""
    """The last message the model wrote."""
    total: wire.TokenUsageBreakdown | None = None
    """The thread's running token count, as last reported."""
    failure: wire.TurnError | None = None
    """The turn's last error that Codex didn't retry itself."""
    limits: wire.RateLimitSnapshot | None = None
    """The account's rate limits as last reported, kept by `watch`."""

    def watch(self) -> None:
        """Keep the account's rate limits as Codex reports them, until the client ends.

        It runs on a thread of its own, since the SDK hands out reports outside any
        turn one at a time, blocking until the next. Whatever ends the client also
        reaches the turn's stream, which raises it, so here it only ends the watch.
        """
        try:
            while True:
                match self.client.next_notification().payload:
                    case wire.AccountRateLimitsUpdatedNotification(rate_limits=limits):
                        self.limits = limits
                    case _:
                        pass
        except Exception:
            return

    async def converse(
        self, prompt: str, toolbox: Toolbox, effort: Effort | None
    ) -> RawTurn:
        """Take turns until the toolbox lets the thread end: the prompt, then each reason it gives."""
        said = prompt
        while True:
            completed = await self.take(said, effort)
            match completed.status:
                case wire.TurnStatus.failed:
                    raise classified(self.failure or completed.error, self.limits)
                case wire.TurnStatus.interrupted | wire.TurnStatus.in_progress:
                    message = (
                        f"Codex ended the turn as {completed.status.value}, unasked"
                    )
                    raise TurnError(message)
                case wire.TurnStatus.completed:
                    pass
            match toolbox.end():
                case KeepGoing(reason=reason):
                    said = reason
                case End() | GiveUp():
                    return RawTurn(
                        text=self.text, usage=self.usage(), session_id=self.thread
                    )

    async def take(self, said: str, effort: Effort | None) -> wire.Turn:
        """Run one turn on `said`, and return it once Codex completes it.

        Cancelled while it runs, it interrupts the turn, then lets the cancellation
        go on.
        """
        client = self.client
        settings = TurnSettings(effort=effort).sent()
        started = await asyncio.to_thread(
            client.turn_start, self.thread, said, settings
        )
        turn = started.turn.id
        self.failure = None
        try:
            while True:
                notification = await asyncio.to_thread(
                    client.next_turn_notification, turn
                )
                match notification.payload:
                    case wire.ItemCompletedNotification(
                        item=wire.ThreadItem(
                            root=wire.AgentMessageThreadItem(text=text)
                        )
                    ):
                        self.text = text
                    case wire.ThreadTokenUsageUpdatedNotification(token_usage=usage):
                        self.total = usage.total
                    case wire.ErrorNotification(error=error, will_retry=False):
                        self.failure = error
                    case wire.TurnCompletedNotification(turn=completed):
                        return completed
                    case _:
                        pass
        except asyncio.CancelledError as cancelled:
            try:
                await asyncio.to_thread(client.turn_interrupt, self.thread, turn)
            except CodexError as failed:
                cancelled.add_note(f"interrupting Codex's turn {turn} failed: {failed}")
            raise
        finally:
            client.unregister_turn_notifications(turn)

    def usage(self) -> Usage:
        """Return what the thread's turns used, from its running total.

        Codex counts cached input among its input tokens, and reasoning among its
        output tokens; lup counts the input read from cache apart, so
        `input_tokens` is the input that wasn't.
        """
        total = self.total
        if total is None:
            return Usage()
        cached = total.cached_input_tokens
        return Usage(
            input_tokens=total.input_tokens - cached,
            output_tokens=total.output_tokens,
            cache_read_tokens=cached,
            cache_write_tokens=total.cache_write_input_tokens or 0,
        )


class CodexAdapter(Model, Adapter, arbitrary_types_allowed=True):
    """Runs an ask's turns on Codex's app-server, in a process of the ask's own."""

    model: str
    system_prompt: str | None = None
    """Replaces Codex's own prompt; none sends no system prompt at all."""
    effort: Effort | None = None
    layout: CodexLayout = Field(default_factory=lambda: CodexLayout.of(CodexSettings()))
    connect: Connect = app_server
    """Makes the client; a test gives a fake one."""

    @override
    async def run(self, request: TurnRequest) -> RawTurn:
        """Run the ask's turns on a thread of their own, until the toolbox lets them end."""
        layout = self.layout
        launch = [f"{key}={json.dumps(value)}" for key, value in LAUNCH.items()]
        config = CodexConfig(
            config_overrides=tuple(launch),
            env={"CODEX_HOME": str(layout.home)},
        )
        client = self.connect(
            config, serving(request.toolbox, asyncio.get_running_loop())
        )
        try:
            layout.home.mkdir(parents=True, exist_ok=True)
            login = layout.login
            if login.is_symlink() and login.readlink() != layout.operator_login:
                login.unlink()
            if not login.is_symlink() and not login.exists():
                login.symlink_to(layout.operator_login)
            await asyncio.to_thread(client.start)
            await asyncio.to_thread(client.initialize)
            account = await asyncio.to_thread(
                lambda: client.request(
                    "account/read", {"refreshToken": False}, response_model=Account
                )
            )
            if account.account is None and account.requires_openai_auth:
                found = (
                    "" if layout.operator_login.exists() else ", which doesn't exist"
                )
                message = (
                    f"Codex has no login lup can use. lup runs Codex in a home of its own "
                    f"({layout.home}), whose `auth.json` links to yours "
                    f"({layout.operator_login}){found}. Log in with `codex login`. A login "
                    "kept in the system keyring can't be seen from lup's home: set "
                    '`cli_auth_credentials_store = "file"` in your Codex configuration, '
                    "then log in again."
                )
                raise AuthMissingError(message)
            tools = [
                DynamicTool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                )
                for spec in request.toolbox.specs()
            ]
            thread = ThreadStart(
                model=self.model,
                base_instructions=""
                if self.system_prompt is None
                else self.system_prompt,
                dynamic_tools=tools,
            )
            started = await asyncio.to_thread(
                lambda: client.request(
                    "thread/start", thread.sent(), response_model=Started
                )
            )
            session = Session(client=client, thread=started.thread.id)
            threading.Thread(target=session.watch, daemon=True).start()
            return await session.converse(request.prompt, request.toolbox, self.effort)
        except ServerBusyError as busy:
            message = f"Codex's app-server is too busy to take the ask: {busy}"
            raise AgentUnavailableError(message) from busy
        except CodexError as failed:
            message = f"Codex's app-server failed: {failed}"
            raise TurnError(message) from failed
        finally:
            await asyncio.to_thread(client.close)
