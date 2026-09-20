"""Codex app-server Client with live optional turn capabilities."""

import asyncio
from functools import partial
import json
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from lup.execution.threads import run_sync
from lup.providers.codex.app_server import (
    CodexAppServer,
    RpcMessage,
    RpcNotification,
    native_environment,
)
from lup.providers.codex.hooks import (
    APPROVAL_METHODS,
    CodexApprovalResponder,
    codex_hook_approval_policy,
)
from lup.providers.codex.home import CodexWorktreeHomeStore, install_declared_policy
from lup.providers.selection import SessionContainment
from lup.providers.codex.login import CODEX_HOME, native_home
from lup.providers.codex.output import CodexOutputContract, codex_output_contract
from lup.providers.codex.subagents import CodexSubagentTools
from lup.policy.hooks import LupHookInput, LupHookOutput, LupHooksConfig
from lup.policy.identity import POLICY_ROOT_ENV
from lup.sessions.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.sessions.capabilities import (
    EventStream,
    Session,
    ForkSession,
    Interrupt,
    Steer,
    TurnToolBinder,
)
from lup.sessions.errors import ProviderTurnError, StructuredOutputError
from lup.sessions.errors import TurnFailure, TurnInterruptedError, ValidationAttempt
from lup.sessions.errors import UnsupportedCapability
from lup.sessions.middleware import CorrectionConfig, DecoratingSession
from lup.sessions.errors import TurnAlreadyActiveError
from lup.sessions.middleware import SerializedTurn
from lup.sessions.client import Client
from lup.sessions.events import (
    BlockCompletedEvent,
    BlockDeltaEvent,
    LiveTurnEvent,
    MessageCompletedEvent,
    SessionHandle,
    SessionId,
    SubmissionGateResolver,
    AnyTurnBlock,
    TurnCompletedEvent,
    TurnEvent,
    TurnStartedEvent,
    TurnIdentifiers,
    TurnId,
    TurnInput,
    TurnRequest,
    TurnHandle,
    TurnMessage,
    TurnToolCallBlock,
    TurnToolResultBlock,
    TurnToolBinding,
)
from lup.sessions.output import TurnSubmission, bound_submission
from lup.sessions.recursion import (
    child_recursive_agent_allowance,
    recursive_agent_scope,
)
from lup.sessions.transcript import fold_transcript
from lup.types import EnvVars, JsonObject, JsonValue, Usage


type CodexEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
"""How much reasoning a Codex turn is asked to spend, in Codex's own words.

Declared beside the config that carries it rather than beside the table that
translates a portable tier into it, because a model and its effort are one
choice on the wire and this is where that choice is assembled.

Not every model accepts every rung, and the ladder moves: a home written for a
newer model here carried ``max``, which the API refused for an older one with
"Supported values are: 'none', 'low', 'medium', 'high', and 'xhigh'" — a list
that also omits the ``minimal`` this closes over. What follows from that is
:meth:`CodexSessionConfig.model_selection`, not a narrower literal: which
rungs a given model accepts is the vendor's to answer per model, and guessing
it here would refuse configurations that work.
"""


CODEX_PROGRAM = Path("codex")
"""The program a Codex session is started as when nothing names another.

Named once because two places read it: the field default below, and the
caller that falls back to it when a request asked for no container to enter.
Spelled twice, the fallback would be a second opinion about what this
runtime is called.
"""


class CodexSessionConfig(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Immutable Codex-only app-server configuration."""

    model: str | None = None
    developer_instructions: str = ""
    cwd: Path
    policy_root: Path | None = None
    """Application project declaring policy; direct callers default to cwd."""
    executable: Path = CODEX_PROGRAM
    containment: SessionContainment = "none"
    """The boundary owning this executable's home; outer wrappers prepare theirs."""
    named_profile: str | None = None
    model_provider: str | None = None
    provider_config: JsonObject | None = None
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] | None = None
    # The app-server's own wire spellings, passed through by thread_parameters.
    approval_policy: Literal["untrusted", "on-request", "granular", "never"] | None = (
        None
    )
    hooks: LupHooksConfig | None = None
    effort: CodexEffort | None = None
    """What this session asks the model to spend, or None to leave it to the home.

    ``None`` means inherit, which is right only while the *model* is also
    inherited. Where a model is named, :attr:`paired_effort` answers instead —
    see :meth:`model_selection` for why the two cannot travel apart.
    """

    paired_effort: CodexEffort = "medium"
    """The effort a named model carries when the caller names none.

    A judgement, so it is an overridable default rather than a constant: a
    caller who knows what their model should spend says so and this is never
    read. What it must not be is *absent*, because absence is what let a
    caller's model reach the API beside a stranger's effort.
    """

    environment: EnvVars = {}
    submission_gate_resolver: SubmissionGateResolver | None = None
    correction: CorrectionConfig = CorrectionConfig()
    continuation: CorrectionConfig = CorrectionConfig(
        instruction="Continue according to the Stop hook feedback."
    )
    mcp_servers: dict[str, "CodexMcpServerConfig"] = {}
    writable_roots: list[Path] = []
    delegated_tools: CodexSubagentTools | None = None

    @model_validator(mode="after")
    def reject_unanswerable_approvals(self) -> "CodexSessionConfig":
        """Refuse a thread that would ask questions this session cannot answer.

        An approval policy that asks makes the app-server send approval
        requests back here, and only declared hooks answer them. Without
        those the transport refuses every request as unhandled, which stalls
        the turn on its first command — so the combination is rejected at
        construction instead of at the first act.
        """
        if self.containment == "outer" and self.executable == CODEX_PROGRAM:
            raise ValueError(
                "outer containment requires the prepared container executable"
            )
        if self.delegated_tools is not None and (
            self.sandbox != "read-only" or self.approval_policy != "never"
        ):
            raise ValueError(
                "delegated tools require read-only sandbox and never approvals"
            )
        if self.delegated_tools is not None and (
            self.mcp_servers or self.writable_roots
        ):
            raise ValueError(
                "delegated tool capabilities do not grant MCP servers or writable roots"
            )
        if self.approval_policy not in {None, "never"} and self.hooks is None:
            raise ValueError(
                f"approval_policy {self.approval_policy!r} makes the app-server "
                "ask this session for decisions; supply hooks to answer them, "
                "or use 'never'"
            )
        return self

    def validated_for_app_server(self) -> "CodexSessionConfig":
        """Refuse native capabilities before any process starts, without payloads."""
        if self.named_profile is not None:
            raise UnsupportedCapability(
                "Codex app-server cannot select named profiles or apply all startup "
                "settings through thread configuration. Configure the intended "
                "CODEX_HOME/config.toml before opening, or supply explicit supported "
                "session settings. Interactive Codex launches support named profiles."
            )
        return self

    def model_selection(self) -> JsonObject:
        """The model and the effort that goes with it — both, or neither.

        A model and its reasoning effort are one choice, and the home this
        session opens against already holds an answer to both: it is seeded
        from the operator's own configuration, so it carries the model *they*
        chose and the effort they chose for it.

        Naming only the model therefore does not select a model. It selects
        half of somebody else's pair, and the API is the first thing to notice
        — ``'max' is not supported with the 'gpt-5.5' model``, a 400 before the
        turn does anything, naming neither the home nor the caller. Every
        Codex session Lup opened through a named model was one home edit away
        from it.

        So the two travel together. Naming neither inherits a pair that was
        chosen together and is therefore coherent; naming a model sends an
        effort beside it, the caller's where they gave one and
        :attr:`paired_effort` where they did not.
        """
        if self.model is None:
            return {} if self.effort is None else {"effort": self.effort}
        return {"model": self.model, "effort": self.effort or self.paired_effort}


class CodexMcpServerConfig(BaseModel, frozen=True):
    """One project tool group served to Codex over an explicit subprocess."""

    command: str
    args: list[str] = []
    env: EnvVars = {}


class CodexThreadRef(BaseModel, frozen=True):
    id: str


class CodexInheritedConfig(BaseModel, frozen=True):
    """Only the inherited MCP roster is needed to restrict a delegated role."""

    mcp_servers: dict[str, JsonValue] = {}


class CodexConfigReadResponse(BaseModel, frozen=True):
    config: CodexInheritedConfig


class CodexNotificationScope(BaseModel, frozen=True):
    thread_id: str | None = Field(default=None, alias="threadId")


class CodexTurnRef(BaseModel, frozen=True):
    id: str
    status: str = "inProgress"
    duration_ms: int | None = Field(default=None, alias="durationMs")


class CodexThreadResponse(BaseModel, frozen=True):
    thread: CodexThreadRef


class CodexTurnResponse(BaseModel, frozen=True):
    turn: CodexTurnRef


class McpElicitationMetadata(BaseModel, frozen=True):
    codex_approval_kind: str | None = None


class CodexHookActivity(BaseModel, frozen=True, extra="ignore"):
    """Native notification/request identity and optional completed item."""

    thread_id: str | None = Field(default=None, alias="threadId")
    turn_id: str | None = Field(default=None, alias="turnId")
    item: JsonObject | None = None


class McpElicitationRequest(BaseModel, frozen=True):
    """One approval elicitation for an MCP server tool call.

    Codex treats session-scoped MCP servers as untrusted and elicits an
    approval (``mcpServer/elicitation/request``, with
    ``_meta.codex_approval_kind = "mcp_tool_call"``) before every call.
    """

    thread_id: str = Field(alias="threadId")
    server_name: str = Field(alias="serverName")
    metadata: McpElicitationMetadata = Field(
        default_factory=McpElicitationMetadata, alias="_meta"
    )


class CodexItemOutcome(BaseModel, frozen=True):
    """Outcome fields shared by native activities, with their absent defaults."""

    activity: str = Field(default="unknown", alias="type")
    status: str | None = None
    success: bool | None = None
    exit_code: int | None = Field(default=None, alias="exitCode")
    failure: JsonValue = None

    @property
    def failed(self) -> bool:
        return (
            self.success is False
            or self.exit_code not in (None, 0)
            or self.status in ("failed", "errored", "rejected")
            or self.failure is not None
        )


class CodexReasoningItem(BaseModel, frozen=True):
    summary: list[str] = []
    content: list[str] = []


class TokenUsageBreakdown(BaseModel, frozen=True):
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    cached_input_tokens: int = Field(alias="cachedInputTokens")


class CodexTurnFailure(BaseModel, frozen=True):
    """The `error` object an app-server turn carries when it did not complete."""

    message: str | None = None


class CodexCompletedTurn(BaseModel, frozen=True):
    """One `turn/completed` payload, read for the fields this adapter needs."""

    status: str
    duration_ms: int | None = Field(default=None, alias="durationMs")
    error: CodexTurnFailure | None = None


def notification_turn_id(notification: RpcNotification) -> str | None:
    """Extract the native turn identity without mutating channel ownership."""
    match notification.params:
        case {"turnId": str(turn_id)}:
            return turn_id
        case {"turn": {"id": str(turn_id)}}:
            return turn_id
        case _:
            return None


class CodexTurnChannel:
    """Route one turn's notifications into live events and completed replay."""

    notifications: Sequence[str] = (
        "turn/started",
        "item/agentMessage/delta",
        "item/completed",
        "thread/tokenUsage/updated",
        "turn/completed",
    )
    """Every notification method :meth:`decode` answers.

    Those arms narrow vendor method strings, which no union of ours enumerates,
    so the roster is declared here beside them and gates the match rather than
    describing it. A method that gains an arm without gaining an entry never
    reaches it, and the suite naming each shape fails instead of a renamed
    notification passing as one this turn had no interest in.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turn_id: str | None = None
        self.events: asyncio.Queue[LiveTurnEvent | None] = asyncio.Queue()
        self.completed: asyncio.Future[CompletedTurn] = (
            asyncio.get_running_loop().create_future()
        )
        self.durable: list[TurnEvent] = []
        self.blocks: list[AnyTurnBlock] = []
        self.usage = Usage()
        self.started = perf_counter()
        self.hook_tasks: list[asyncio.Task[None]] = []
        self.hook_error: Exception | None = None
        self.deferred_context: list[LupHookOutput] = []

    def identifiers(self) -> TurnIdentifiers:
        if self.turn_id is None:
            raise RuntimeError("turn notification arrived without a turn identity")
        return TurnIdentifiers(
            session=SessionId(value=self.session_id),
            turn=TurnId(value=self.turn_id),
        )

    def emit(self, event: TurnEvent) -> None:
        """Record one durable event and publish it, so both views agree."""
        self.durable.append(event)
        self.events.put_nowait(event)

    def feed(self, notification: RpcNotification) -> None:
        try:
            self.decode(notification)
        except Exception as error:
            self.fail(error)

    def fail(self, error: Exception) -> None:
        """Fail this turn with all live evidence accumulated so far."""
        if isinstance(error, ProviderTurnError | TurnInterruptedError):
            failure = error
        else:
            identifiers = self.identifiers() if self.turn_id is not None else None
            failure = ProviderTurnError(
                TurnFailure(
                    message=str(error),
                    blocks=self.blocks,
                    messages=fold_transcript(self.durable),
                    usage=self.usage,
                    duration=timedelta(seconds=perf_counter() - self.started),
                    identifiers=identifiers,
                )
            )
        if not self.completed.done():
            self.completed.set_exception(failure)
        self.events.put_nowait(None)

    def decode(self, notification: RpcNotification) -> None:
        if notification.method not in self.notifications:
            return
        scope = CodexNotificationScope.model_validate(notification.params)
        if scope.thread_id not in (None, self.session_id):
            return
        candidate = notification_turn_id(notification)
        if candidate is not None:
            if self.turn_id is not None and candidate != self.turn_id:
                return
            self.turn_id = candidate
        match notification.method, notification.params:
            case "turn/started", {"turn": {"id": str()}}:
                self.events.put_nowait(TurnStartedEvent(identifiers=self.identifiers()))
            case "item/agentMessage/delta", {
                "turnId": str(),
                "delta": str(delta),
            }:
                self.events.put_nowait(
                    BlockDeltaEvent(
                        identifiers=self.identifiers(),
                        delta=delta,
                    )
                )
            case "item/completed", {
                "turnId": str(),
                "item": item,
            } if isinstance(item, dict):
                completed = decode_completed_item(item)
                for block in completed:
                    self.blocks.append(block)
                    self.emit(
                        BlockCompletedEvent(identifiers=self.identifiers(), block=block)
                    )
                if completed:
                    self.emit(
                        MessageCompletedEvent(
                            identifiers=self.identifiers(),
                            message=TurnMessage(
                                role=message_role(item),
                                blocks=completed,
                                native=item,
                            ),
                        )
                    )
            case "thread/tokenUsage/updated", {
                "turnId": str(),
                "tokenUsage": {"last": usage},
            } if isinstance(usage, dict):
                self.usage = decode_usage(usage)
            case "turn/completed", {"turn": {"id": str(), "status": str()} as turn}:
                completed_turn = CodexCompletedTurn.model_validate(turn)
                status = completed_turn.status
                duration = timedelta(
                    milliseconds=completed_turn.duration_ms
                    if completed_turn.duration_ms is not None
                    else (perf_counter() - self.started) * 1000
                )
                if not self.completed.done():
                    match status:
                        case "completed":
                            self.completed.set_result(
                                CompletedTurn(
                                    messages=fold_transcript(self.durable),
                                    blocks=self.blocks,
                                    usage=self.usage,
                                    duration=duration,
                                )
                            )
                        case _:
                            message = (
                                completed_turn.error.message
                                if completed_turn.error
                                else None
                            )
                            failure = TurnFailure(
                                message=(
                                    message
                                    if message
                                    else f"Codex turn ended with status {status}"
                                ),
                                blocks=self.blocks,
                                messages=fold_transcript(self.durable),
                                usage=self.usage,
                                duration=duration,
                                identifiers=self.identifiers(),
                            )
                            error = (
                                TurnInterruptedError(failure)
                                if status.lower()
                                in {"interrupted", "cancelled", "canceled"}
                                else ProviderTurnError(failure)
                            )
                            self.completed.set_exception(error)
                self.events.put_nowait(
                    TurnCompletedEvent(identifiers=self.identifiers())
                )
                self.events.put_nowait(None)
            case _:
                return


class CodexLiveEventStream(EventStream):
    """One ordered channel, viewed either with in-flight deltas or without.

    The durable view filters the same sequence rather than reading a second
    one, so the two can never report different histories.
    """

    def __init__(self, channel: CodexTurnChannel) -> None:
        self.channel = channel
        self.consumed = False

    async def iterate(self) -> AsyncIterator[LiveTurnEvent]:
        if self.consumed:
            raise RuntimeError("live event stream can only be consumed once")
        self.consumed = True
        while (event := await self.channel.events.get()) is not None:
            yield event

    async def durable(self) -> AsyncIterator[TurnEvent]:
        async for event in self.iterate():
            if (durable := event.durable) is not None:
                yield durable

    def events(self) -> AsyncIterator[TurnEvent]:
        return self.durable()

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        return self.iterate()


class CodexConversationState:
    """One app-server connection, thread, and current turn binding."""

    def __init__(
        self,
        config: CodexSessionConfig,
        server: CodexAppServer,
        resume: SessionId | None,
    ) -> None:
        self.config = config
        self.server = server
        self.resume = resume
        self.thread_id: str | None = None
        self.submission: TurnSubmission | None = None
        self.channel: CodexTurnChannel | None = None
        self.inherited_servers: list[str] = []
        self.context_lock = asyncio.Lock()
        self.stop_hook_active = False
        self.pending_hook_receipts: list[LupHookOutput] = []
        self.server.server_request_handler = self.handle_server_request
        self.server.notification_handler = self.handle_notification
        self.server.disconnect_handler = self.handle_disconnect

    async def ensure_thread(self) -> str:
        if self.thread_id is not None:
            return self.thread_id
        if self.config.delegated_tools is not None:
            if self.resume is not None:
                raise ValueError(
                    "a delegated role cannot resume a thread with inherited tools"
                )
            inherited = CodexConfigReadResponse.model_validate(
                await self.server.request(
                    "config/read", {"cwd": str(self.config.cwd), "includeLayers": False}
                )
            )
            self.inherited_servers = list(inherited.config.mcp_servers)
        if self.resume is not None:
            params = self.thread_parameters()
            params["threadId"] = self.resume.value
            result = await self.server.request("thread/resume", params)
        else:
            params = self.thread_parameters()
            result = await self.server.request("thread/start", params)
        response = CodexThreadResponse.model_validate(result)
        self.thread_id = response.thread.id
        return self.thread_id

    def thread_parameters(self) -> JsonObject:
        """Preserve configured thread behavior for new and resumed threads."""
        params: JsonObject = {
            "cwd": str(self.config.cwd),
            "developerInstructions": self.config.developer_instructions,
        }
        # One half of the pair `model_selection` settles; its other half rides
        # `turn/start`, which is the only reason they are written apart.
        selected = self.config.model_selection()
        if "model" in selected:
            params["model"] = selected["model"]
        if self.config.model_provider is not None:
            params["modelProvider"] = self.config.model_provider
        configuration = dict(self.config.provider_config or {})
        if self.config.delegated_tools is not None:
            configuration.update(self.config.delegated_tools.configuration())
            configuration["mcp_servers"] = {
                name: {"enabled": False} for name in self.inherited_servers
            }
        if self.config.mcp_servers:
            configuration["mcp_servers"] = {
                name: server.model_dump(mode="json")
                for name, server in self.config.mcp_servers.items()
            }
        if self.config.writable_roots:
            configuration["sandbox_workspace_write"] = {
                "writable_roots": [str(path) for path in self.config.writable_roots]
            }
        if configuration:
            params["config"] = configuration
        if self.config.sandbox is not None:
            params["sandbox"] = self.config.sandbox
        if self.config.approval_policy is not None:
            params["approvalPolicy"] = self.config.approval_policy
        return params

    async def start_turn(self, text: str) -> AcceptedTurn:
        thread_id = await self.ensure_thread()
        channel = CodexTurnChannel(thread_id)
        stop_hook_active = self.stop_hook_active
        self.channel = channel
        submission = self.submission
        output = codex_output_contract(submission.schema) if submission else None
        params: JsonObject = {
            "threadId": thread_id,
            "input": [
                {"type": "text", "text": output.prompt(text) if output else text}
            ],
        }
        # The other half. A named model always brings one, so the home's own
        # effort never rides beside a model the home did not choose.
        selected = self.config.model_selection()
        if "effort" in selected:
            params["effort"] = selected["effort"]
        if output is not None:
            params["outputSchema"] = output.native
        result = await self.server.request("turn/start", params)
        response = CodexTurnResponse.model_validate(result)
        for receipt in self.pending_hook_receipts:
            receipt.delivered()
        self.pending_hook_receipts.clear()
        channel.turn_id = response.turn.id
        identifiers = TurnIdentifiers(
            session=SessionId(value=thread_id),
            turn=TurnId(value=response.turn.id),
        )

        async def complete() -> CompletedTurn:
            completed = await self.complete_turn(channel, identifiers, stop_hook_active)
            if submission is not None and output is not None:
                await submit_completed_output(
                    submission, output, completed, identifiers
                )
            return completed

        return AcceptedTurn(
            identifiers=identifiers,
            complete=complete,
            events=CodexLiveEventStream(channel),
            interrupt=CodexInterrupt(self, response.turn.id),
            steer=CodexSteer(self, response.turn.id),
        )

    async def handle_server_request(self, message: RpcMessage) -> JsonValue:
        if message.method in APPROVAL_METHODS:
            return await self.resolve_approval(message)
        if message.method == "mcpServer/elicitation/request":
            return self.resolve_mcp_elicitation(message)
        raise UnsupportedCapability(
            f"Codex app-server request {message.method!r} requires a client handler; use an interactive client for this capability"
        )

    async def complete_turn(
        self,
        channel: CodexTurnChannel,
        identifiers: TurnIdentifiers,
        stop_hook_active: bool,
    ) -> CompletedTurn:
        """Evaluate completion only after all completed-tool hooks have settled."""
        from lup.sessions.errors import TurnContinuationError

        completed = await channel.completed
        await asyncio.gather(*channel.hook_tasks)
        async with self.context_lock:
            outputs = list(channel.deferred_context)
            if self.config.hooks is not None and channel.hook_error is None:
                responder = CodexApprovalResponder(hooks=self.config.hooks)
                try:
                    outputs.extend(
                        await responder.evaluate(
                            LupHookInput(
                                event="Stop",
                                cwd=str(self.config.cwd),
                                stop_hook_active=stop_hook_active,
                            )
                        )
                    )
                except Exception as error:
                    channel.hook_error = error
            feedback = CodexApprovalResponder(hooks=LupHooksConfig()).context(outputs)
            refused = any(
                output.decision in {"deny", "block", "ask"} for output in outputs
            )
            if channel.hook_error is None and not feedback and not refused:
                return completed
            failure = TurnFailure(
                message=str(channel.hook_error)
                if channel.hook_error
                else (feedback or "The Stop hook requires another continuation."),
                blocks=completed.blocks,
                messages=completed.messages,
                usage=completed.usage,
                duration=completed.duration,
                identifiers=identifiers,
            )
            if channel.hook_error is not None:
                raise ProviderTurnError(failure) from channel.hook_error
            self.stop_hook_active = True
            self.pending_hook_receipts = outputs
            raise TurnContinuationError(failure)

    async def deliver_activity(
        self,
        channel: CodexTurnChannel,
        notification: RpcNotification,
    ) -> None:
        """Run completed-tool callbacks and retain feedback the turn cannot accept."""
        try:
            if self.config.hooks is None:
                return
            async with self.context_lock:
                if channel is not self.channel:
                    return
                responder = CodexApprovalResponder(
                    hooks=self.config.hooks,
                    deliver_context=partial(self.deliver_context, channel),
                )
                item = CodexHookActivity.model_validate(notification.params).item
                if item is not None:
                    blocks = decode_completed_item(item)
                    results = {
                        block.tool_call_id: block.content
                        for block in blocks
                        # lup: ignore[own-model-dispatch] — adapter pairs tool call/result records
                        if isinstance(block, TurnToolResultBlock)
                    }
                    for block in blocks:
                        # lup: ignore[own-model-dispatch] — adapter pairs tool call/result records
                        if isinstance(block, TurnToolCallBlock):
                            outputs = await responder.evaluate(
                                LupHookInput(
                                    event="PostToolUse",
                                    tool_name=block.name,
                                    tool_input=block.arguments,
                                    tool_result=results.get(block.id, ""),
                                    cwd=str(self.config.cwd),
                                )
                            )
                            if not await responder.deliver(outputs):
                                channel.deferred_context.extend(outputs)
                if not channel.completed.done():
                    await responder.deliver_pending()
        except Exception as error:
            channel.hook_error = error
            raise

    async def resolve_approval(self, message: RpcMessage) -> JsonValue:
        """Answer one approval request from this session's declared hooks.

        A session with no hooks declines rather than accepting. Reaching here
        at all means the thread was started under a policy that asks, and the
        constructor refuses that combination — so this is the belt to that
        validator's braces, and the safe answer to a question nobody can
        answer is no.
        """
        if self.config.hooks is None:
            return {"decision": "decline"}
        channel = self.channel
        if channel is None or channel.completed.done():
            return {"decision": "decline"}
        if self.thread_id is None or channel.turn_id is None:
            return {"decision": "decline"}
        activity = CodexHookActivity.model_validate(message.params)
        if activity.turn_id != channel.turn_id:
            return {"decision": "decline"}
        if activity.thread_id != self.thread_id:
            return {"decision": "decline"}
        responder = CodexApprovalResponder(
            hooks=self.config.hooks,
            deliver_context=partial(self.deliver_context, channel),
            delivery_lock=self.context_lock,
        )
        method = message.method or ""
        return {"decision": await responder.decide(method, message.params)}

    def resolve_mcp_elicitation(self, message: RpcMessage) -> JsonValue:
        """Accept tool-call elicitations for servers this session composed.

        The composition that opened this session declared its ``mcp_servers``,
        so calls to those servers are pre-authorized; an elicitation naming
        any other server declines. Without this, every project tool call is
        reported to the model as "user rejected MCP tool call".
        """
        request = McpElicitationRequest.model_validate(message.params)
        if request.thread_id != self.thread_id:
            return {"action": "decline"}
        if request.metadata.codex_approval_kind != "mcp_tool_call":
            raise UnsupportedCapability(
                "Codex MCP forms, URL and verification elicitations require an interactive client; use an interactive session to answer them"
            )
        if request.server_name in self.config.mcp_servers:
            return {"action": "accept"}
        return {"action": "decline"}

    async def deliver_context(self, channel: CodexTurnChannel, text: str) -> None:
        """Steer only the active turn whose context this hook is delivering."""
        if (
            channel is not self.channel
            or channel.turn_id is None
            or channel.completed.done()
        ):
            raise RuntimeError("no active Codex turn can receive hook context")
        await CodexSteer(self, channel.turn_id).steer(TurnInput(text=text))

    def handle_notification(self, notification: RpcNotification) -> None:
        activity = CodexHookActivity.model_validate(notification.params)
        if activity.thread_id not in {None, self.thread_id}:
            return
        if self.channel is not None:
            self.channel.feed(notification)
            if (
                notification.method == "item/completed"
                and notification_turn_id(notification) == self.channel.turn_id
            ):
                self.channel.hook_tasks.append(
                    self.server.spawn_handler(
                        self.deliver_activity(self.channel, notification)
                    )
                )

    def handle_disconnect(self, error: Exception) -> None:
        if self.channel is not None:
            self.channel.fail(error)


class CodexHookSession(Session):
    """Reset Stop state once per logical turn, preserving it across native retries."""

    def __init__(self, state: CodexConversationState, inner: Session) -> None:
        self.state = state
        self.inner = inner
        self.lock = asyncio.Lock()

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        if self.lock.locked():
            raise TurnAlreadyActiveError("a logical Codex turn is already active")
        await self.lock.acquire()
        self.state.stop_hook_active = False
        self.state.pending_hook_receipts.clear()
        accepted = False
        try:
            handle = await self.inner.start(request)
            accepted = True
        finally:
            if not accepted:
                self.lock.release()
        return TurnHandle[T](
            turn=SerializedTurn(handle.turn, self.lock),
            events=handle.events,
            interrupt=handle.interrupt,
            steer=handle.steer,
        )


class CodexTurnToolBinder(TurnToolBinder):
    """Bind each turn's native final-output schema and validation independently."""

    def __init__(self, state: CodexConversationState) -> None:
        self.state = state

    async def bind[T: BaseModel](self, binding: TurnToolBinding[T] | None) -> None:
        submission = bound_submission(binding) if binding is not None else None
        self.state.submission = submission


class CodexInterrupt(Interrupt):
    def __init__(self, state: CodexConversationState, turn_id: str) -> None:
        self.state = state
        self.turn_id = turn_id

    async def interrupt(self) -> None:
        thread_id = await self.state.ensure_thread()
        await self.state.server.request(
            "turn/interrupt", {"threadId": thread_id, "turnId": self.turn_id}
        )


class CodexSteer(Steer):
    def __init__(self, state: CodexConversationState, turn_id: str) -> None:
        self.state = state
        self.turn_id = turn_id

    async def steer(self, input: TurnInput) -> None:
        thread_id = await self.state.ensure_thread()
        await self.state.server.request(
            "turn/steer",
            {
                "threadId": thread_id,
                "expectedTurnId": self.turn_id,
                "input": [{"type": "text", "text": input.text}],
            },
        )


class CodexFork(ForkSession):
    def __init__(self, state: CodexConversationState) -> None:
        self.state = state

    def fork(
        self, at: TurnId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_fork(at)

    @asynccontextmanager
    async def open_fork(self, at: TurnId | None) -> AsyncGenerator[SessionHandle]:
        if at is not None:
            raise ValueError("Codex thread/fork can only fork the latest thread state")
        thread_id = await self.state.ensure_thread()
        result = await self.state.server.request("thread/fork", {"threadId": thread_id})
        response = CodexThreadResponse.model_validate(result)
        opener = CodexSessionOpener(self.state.config)
        async with opener.open_session(SessionId(value=response.thread.id)) as handle:
            yield handle


class CodexSessionOpener:
    """Validate hook coverage before opening one app-server per Lup session.

    Direct configuration has the same hook coverage contract as portable
    selection. Native approval callbacks also require an explicit asking
    policy; inheriting a policy could silently prevent every callback.
    Lifecycle observers leave the selected approval policy untouched.
    """

    def __init__(self, config: CodexSessionConfig) -> None:
        self.config = config.validated_for_app_server()

    @asynccontextmanager
    async def open_session(
        self, resume: SessionId | None = None
    ) -> AsyncGenerator[SessionHandle]:
        approval = codex_hook_approval_policy(self.config.hooks)
        if approval == "on-request" and self.config.approval_policy in {None, "never"}:
            raise UnsupportedCapability(
                "Native approval-scoped PreToolUse hooks require an explicit asking "
                "approval_policy; use 'on-request' so the app-server can call them."
            )
        # Installed here rather than where the home is named: installing runs
        # a package manager, and a home is named wherever a request is merely
        # described. A session that opened without the policy it was meant to
        # run under is indistinguishable from one running under it, so a
        # failure is raised rather than warned past.
        allowance = child_recursive_agent_allowance(self.config.environment)
        environment = allowance.environment(self.config.environment)
        config = self.config.model_copy(
            update={
                "environment": {
                    **environment,
                    POLICY_ROOT_ENV: str(self.config.policy_root or self.config.cwd),
                },
                "mcp_servers": {
                    name: server.model_copy(
                        update={"env": allowance.environment(server.env)}
                    )
                    for name, server in self.config.mcp_servers.items()
                },
            }
        )
        if config.containment != "outer":
            effective = native_environment(config.environment)
            home = native_home(effective)
            if not effective.get(CODEX_HOME):
                home.mkdir(mode=0o700, parents=True, exist_ok=True)
            await run_sync(
                partial(
                    install_declared_policy,
                    home,
                    config.policy_root or config.cwd,
                    seed=CodexWorktreeHomeStore().derived(home),
                    workspace=config.cwd,
                    executable=config.executable,
                    environment=effective,
                )
            )
            config = config.model_copy(
                update={"environment": {**effective, CODEX_HOME: str(home)}}
            )
        server = CodexAppServer(
            config.executable,
            environment=config.environment,
        )
        await server.start()
        state = CodexConversationState(config, server, resume)
        session = ComposedSession(
            state.start_turn,
            CodexTurnToolBinder(state),
            gate_resolver=config.submission_gate_resolver,
        )
        corrected = DecoratingSession(
            session,
            timeout=None,
            budget=None,
            recovery=None,
            correction=config.correction,
            continuation=config.continuation,
            persistence=None,
        )
        with recursive_agent_scope(allowance):
            try:
                yield SessionHandle(
                    session=CodexHookSession(state, corrected), fork=CodexFork(state)
                )
            finally:
                try:
                    await session.abort_active()
                finally:
                    try:
                        await corrected.close()
                    finally:
                        await server.close()


def create_codex(
    options: CodexSessionConfig | None = None,
    *,
    model: str | None = None,
    system_prompt: str = "",
    cwd: Path | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Client:
    """Open Codex sessions, configured by argument or by whole declaration.

    The same two shapes :func:`lup.providers.claude.runtime.create_claude` takes,
    for the same reason: a reader meeting the library names arguments, and a
    composition that already holds a declaration passes it positionally.

    ``system_prompt`` is the shared spelling across both constructors, and this
    provider's configuration calls the same thing ``developer_instructions``.
    The translation happens here rather than at the call, so a reader moving
    between providers keeps one argument list -- which is the whole reason the
    constructors share one.

    ``cwd`` is resolved at call time rather than defaulted at import, because
    this configuration requires one and the honest default is where the caller
    is standing when it asks -- read at import, a library loaded before a
    process changed directory would open every session somewhere else.
    """
    base = options or CodexSessionConfig(cwd=Path.cwd())
    config = base.model_copy(
        update={
            "model": base.model if model is None else model,
            "developer_instructions": system_prompt or base.developer_instructions,
            "cwd": base.cwd if cwd is None else cwd,
        }
    )
    if base_url is not None:
        # Imported inside the call for the reason the Claude constructor gives:
        # `config` imports this module, so naming it above closes the cycle.
        from lup.providers.codex.config import (
            CodexCompatibilityTransform,
            CodexCompatibleEndpoint,
        )

        endpoint = CodexCompatibleEndpoint.model_validate(
            {"base_url": base_url, "api_key": api_key}
        )
        config = CodexCompatibilityTransform(endpoint).apply(config)
    return Client(CodexSessionOpener(config).open_session)


async def submit_completed_output(
    submission: TurnSubmission,
    output: CodexOutputContract,
    completed: CompletedTurn,
    identifiers: TurnIdentifiers,
) -> None:
    """Validate a native final answer and retain actionable correction evidence."""
    text = next(
        (
            text
            for block in reversed(completed.blocks)
            if (text := block.text_payload) is not None
        ),
        "",
    )
    try:
        value = output.decode(text)
    except ValidationError as error:
        message = f"Final output is not valid JSON: {error}"
    else:
        response = await submission.submit(value)
        if response.accepted:
            return
        message = response.message
    raise StructuredOutputError(
        TurnFailure(
            message=message,
            blocks=completed.blocks,
            messages=completed.messages,
            usage=completed.usage,
            duration=completed.duration,
            identifiers=identifiers,
            validation_history=[ValidationAttempt(message=message)],
        )
    )


def decode_usage(payload: JsonObject) -> Usage:
    """Decode one app-server token-usage breakdown."""
    native = TokenUsageBreakdown.model_validate(payload)
    return Usage(
        input_tokens=native.input_tokens,
        output_tokens=native.output_tokens,
        cache_read_input_tokens=native.cached_input_tokens,
    )


def message_role(payload: JsonObject) -> Literal["user", "assistant", "tool", "system"]:
    """Which transcript role one completed item belongs to.

    A tool call and its result are the model's own act and the environment's
    reply, and collapsing both into one assistant message is what made a
    trace unable to show a call beside the result it produced.
    """
    match payload:
        case (
            {"type": "commandExecution"}
            | {"type": "fileChange"}
            | {"type": "mcpToolCall"}
            | {"type": "functionCallOutput"}
            | {"type": "webSearch"}
            | {"type": "imageView"}
            | {"type": "imageGeneration"}
            | {"type": "collabAgentToolCall"}
            | {"type": "sleep"}
        ):
            return "tool"
        case {"type": "userMessage"}:
            return "user"
        case {
            "type": "hookPrompt"
            | "contextCompaction"
            | "enteredReviewMode"
            | "exitedReviewMode"
            | "subAgentActivity"
        }:
            return "system"
        case _:
            return "assistant"


def decode_completed_item(payload: JsonObject) -> list[AnyTurnBlock]:
    """Decode one typed completed app-server item into canonical blocks."""
    from lup.sessions.events import (
        TurnTextBlock,
        TurnThinkingBlock,
        TurnToolCallBlock,
        TurnToolResultBlock,
        TurnNativeActivityBlock,
    )

    native = CodexItemOutcome.model_validate(payload)
    match payload:
        case {"type": "agentMessage", "text": str(text)}:
            return [TurnTextBlock(text=text)]
        case {"type": "reasoning"}:
            reasoning = CodexReasoningItem.model_validate(payload)
            return [
                TurnThinkingBlock(
                    thinking="\n".join([*reasoning.summary, *reasoning.content])
                )
            ]
        case {
            "type": "commandExecution",
            "id": str(identifier),
            "command": str(command),
            "aggregatedOutput": output,
            "status": status,
        }:
            blocks: list[AnyTurnBlock] = [
                TurnToolCallBlock(
                    id=identifier,
                    name="ShellCommand",
                    arguments={"command": command},
                ),
                TurnToolResultBlock(
                    tool_call_id=identifier,
                    content=output if isinstance(output, str) else "",
                    is_error=status != "completed" or native.failed,
                ),
            ]
            return blocks
        case {
            "type": "fileChange",
            "id": str(identifier),
            "changes": list(changes),
            "status": status,
        }:
            blocks = [
                TurnToolCallBlock(
                    id=identifier,
                    name="EditBatch",
                    arguments={"changes": changes},
                ),
                TurnToolResultBlock(
                    tool_call_id=identifier,
                    content=str(status),
                    is_error=status != "completed",
                ),
            ]
            return blocks
        case {
            "type": "mcpToolCall",
            "id": str(identifier),
            "server": str(server),
            "tool": str(tool),
            "arguments": arguments,
            "status": status,
        }:
            encoded_arguments: JsonObject = (
                {str(key): value for key, value in arguments.items()}
                if isinstance(arguments, dict)
                else {"value": arguments}
            )
            blocks = [
                TurnToolCallBlock(
                    id=identifier,
                    name=f"mcp__{server}__{tool}",
                    arguments=encoded_arguments,
                ),
                TurnToolResultBlock(
                    tool_call_id=identifier,
                    content=json.dumps(payload, sort_keys=True),
                    is_error=status != "completed",
                ),
            ]
            return blocks
        case {
            "type": "dynamicToolCall",
            "id": str(identifier),
            "tool": str(tool),
            "arguments": arguments,
            "status": status,
        }:
            encoded_arguments: JsonObject = (
                {str(key): value for key, value in arguments.items()}
                if isinstance(arguments, dict)
                else {"value": arguments}
            )
            blocks = [
                TurnToolCallBlock(
                    id=identifier,
                    name=tool,
                    arguments=encoded_arguments,
                ),
                TurnToolResultBlock(
                    tool_call_id=identifier,
                    content=json.dumps(payload, sort_keys=True),
                    is_error=status != "completed" or native.failed,
                ),
            ]
            return blocks
        case {"type": "functionCallOutput", "id": str(identifier)}:
            return [
                TurnToolResultBlock(
                    tool_call_id=identifier, content=json.dumps(payload, sort_keys=True)
                )
            ]
        case {
            "type": (
                "webSearch"
                | "imageView"
                | "collabAgentToolCall"
                | "imageGeneration"
                | "sleep"
            ) as activity,
            "id": str(identifier),
        }:
            return [
                TurnToolCallBlock(id=identifier, name=activity, arguments=payload),
                TurnToolResultBlock(
                    tool_call_id=identifier,
                    content=json.dumps(payload, sort_keys=True),
                    is_error=native.failed,
                ),
            ]
        case _:
            return [
                TurnNativeActivityBlock(
                    provider="codex",
                    activity=native.activity,
                    payload=payload,
                )
            ]
