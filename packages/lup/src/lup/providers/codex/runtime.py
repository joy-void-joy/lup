"""Codex app-server Client with live optional turn capabilities."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from tempfile import TemporaryDirectory
from types import EllipsisType
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from lup.providers.codex.app_server import CodexAppServer, RpcMessage, RpcNotification
from lup.providers.codex.hooks import (
    APPROVAL_METHODS,
    CodexApprovalResponder,
)
from lup.providers.codex.home import CodexWorktreeHomeStore, install_declared_policy
from lup.providers.codex.login import CODEX_HOME
from lup.providers.codex.subagents import CodexSubagentTools
from lup.providers.codex.native_tools import CodexNativeTools
from lup.tools.native import NativeTools
from lup.tools.mcp import LupMcpTool, ServerCompanion, ToolResponse, running_companions
from lup.policy.hooks import LupHooksConfig
from lup.sessions.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.sessions.capabilities import (
    EventStream,
    ForkSession,
    Interrupt,
    Steer,
    TurnToolBinder,
)
from lup.sessions.errors import ProviderTurnError, TurnFailure, TurnInterruptedError
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
    TurnMessage,
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


class CodexSessionConfig(
    BaseModel,
    frozen=True,
    arbitrary_types_allowed=True,
    extra="forbid",
    revalidate_instances="always",
):
    """Immutable Codex-only app-server configuration."""

    model: str | None = None
    developer_instructions: str = ""
    cwd: Path
    executable: Path = CODEX_PROGRAM
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
    mcp_servers: dict[str, "CodexMcpServerConfig"] = {}
    writable_roots: list[Path] = []
    delegated_tools: CodexSubagentTools | None = None
    native_tools: NativeTools = None
    application_tools: dict[str, LupMcpTool] = {}
    companions: list[ServerCompanion] = []

    @model_validator(mode="after")
    def reject_unanswerable_approvals(self) -> "CodexSessionConfig":
        """Refuse a thread that would ask questions this session cannot answer.

        An approval policy that asks makes the app-server send approval
        requests back here, and only declared hooks answer them. Without
        those the transport refuses every request as unhandled, which stalls
        the turn on its first command — so the combination is rejected at
        construction instead of at the first act.
        """
        CodexNativeTools.compile(self.native_tools)
        for key in self.provider_config or {}:
            if key not in {"model_provider", "model_providers"}:
                raise ValueError(
                    f"provider_config {key!r} is outside provider endpoint declarations and explicit session authority; use native_tools or tool_servers"
                )
        for name in self.application_tools:
            if (
                not name.startswith("lup_app_")
                or not name.isascii()
                or not all(char.isalnum() or char in "_-" for char in name)
                or len(name) > 64
                or name == SUBMISSION_TOOL
            ):
                raise ValueError(f"invalid or reserved application tool name {name!r}")
        if self.delegated_tools is not None and self.native_tools:
            raise ValueError(
                "delegated_tools and native_tools are alternative authority declarations"
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

    def native_capabilities(self) -> CodexNativeTools:
        """Resolve explicit delegated facilities through the same startup bounds."""
        if self.delegated_tools is not None:
            return CodexNativeTools(
                shell=self.delegated_tools.workspace_read,
                images=self.delegated_tools.workspace_read,
                web=self.delegated_tools.web_search,
            )
        return CodexNativeTools.compile(self.native_tools)


class CodexMcpServerConfig(BaseModel, frozen=True):
    """One project tool group served to Codex over an explicit subprocess."""

    command: str
    args: list[str] = []
    env: EnvVars = {}
    required: bool = True


class CodexThreadRef(BaseModel, frozen=True):
    id: str
    path: Path | None = None


class CodexPersistedTool(BaseModel, frozen=True):
    """The function-tool metadata persisted in the native rollout header."""

    type: Literal["function"] = "function"
    name: str
    description: str
    input_schema: JsonObject = Field(alias="inputSchema")


class CodexRolloutSession(BaseModel, frozen=True):
    id: str
    dynamic_tools: list[CodexPersistedTool] = []


class CodexRolloutHeader(BaseModel, frozen=True):
    type: Literal["session_meta"]
    payload: CodexRolloutSession


class CodexInheritedConfig(BaseModel, frozen=True):
    """Ambient tool sources disabled before the thread begins."""

    mcp_servers: dict[str, JsonValue] = {}
    plugins: dict[str, JsonValue] = {}
    model: str | None = None


class CodexConfigReadResponse(BaseModel, frozen=True):
    config: CodexInheritedConfig


class CodexTurnRef(BaseModel, frozen=True):
    id: str
    status: str = "inProgress"
    duration_ms: int | None = Field(default=None, alias="durationMs")


class CodexThreadResponse(BaseModel, frozen=True):
    thread: CodexThreadRef


class CodexTurnResponse(BaseModel, frozen=True):
    turn: CodexTurnRef


class DynamicToolCall(BaseModel, frozen=True):
    thread_id: str = Field(alias="threadId")
    turn_id: str = Field(alias="turnId")
    call_id: str = Field(alias="callId")
    tool: str
    arguments: JsonValue


class McpElicitationRequest(BaseModel, frozen=True):
    """One approval elicitation for an MCP server tool call.

    Codex treats session-scoped MCP servers as untrusted and elicits an
    approval (``mcpServer/elicitation/request``, with
    ``_meta.codex_approval_kind = "mcp_tool_call"``) before every call.
    """

    thread_id: str = Field(alias="threadId")
    server_name: str = Field(alias="serverName")


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


class CodexSchemaRebindingError(RuntimeError):
    """The current app-server cannot change thread-scoped dynamic tools safely."""


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
                    usage=self.usage,
                    duration=timedelta(seconds=perf_counter() - self.started),
                    identifiers=identifiers,
                )
            )
        if not self.completed.done():
            self.completed.set_exception(failure)
        self.events.put_nowait(None)

    def decode(self, notification: RpcNotification) -> None:
        candidate = notification_turn_id(notification)
        if candidate is not None:
            if self.turn_id is not None and candidate != self.turn_id:
                return
            self.turn_id = candidate
        if notification.method not in self.notifications:
            return
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
                                role=message_role(item), blocks=completed
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


# lup: ignore[constant-declaration] — what the app-server advertises the tool as
SUBMISSION_TOOL = "submit_output"
"""What the app-server advertises this turn's dynamic submission tool as."""


class CodexConversationState:
    """One app-server connection, thread, and current turn binding."""

    def __init__(
        self,
        config: CodexSessionConfig,
        server: CodexAppServer,
        resume: SessionId | None,
        policy_plugin: str | None = None,
        models: dict[str, JsonObject] | None = None,
        fork_from: SessionId | None = None,
    ) -> None:
        self.config = CodexSessionConfig.model_validate(config)
        self.server = server
        self.resume = resume
        self.thread_id: str | None = None
        self.submission: TurnSubmission | None = None
        self.schema_digest: str | None = None
        self.channel: CodexTurnChannel | None = None
        self.inherited_servers: list[str] = []
        self.inherited_plugins: list[str] = []
        self.policy_plugin = policy_plugin
        self.models = models
        self.fork_from = fork_from
        self.server.server_request_handler = self.handle_server_request
        self.server.notification_handler = self.handle_notification
        self.server.disconnect_handler = self.handle_disconnect

    async def ensure_thread(self) -> str:
        if self.thread_id is not None:
            return self.thread_id
        if self.config.delegated_tools is not None and self.resume is not None:
            raise ValueError(
                "a delegated role cannot resume a thread with inherited tools"
            )
        inherited = CodexConfigReadResponse.model_validate(
            await self.server.request(
                "config/read", {"cwd": str(self.config.cwd), "includeLayers": False}
            )
        )
        self.inherited_servers = list(inherited.config.mcp_servers)
        self.inherited_plugins = list(inherited.config.plugins)
        if (
            self.config.model is None
            and inherited.config.model is not None
            and self.models is not None
            and inherited.config.model not in self.models
        ):
            raise ValueError(
                f"Codex cannot bound tools for inherited unknown model {inherited.config.model!r}; select a model from its installed catalog"
            )
        if self.resume is not None or self.fork_from is not None:
            prior = self.resume or self.fork_from
            assert prior is not None
            await self.validate_persisted_tools(prior)
            params = self.thread_parameters()
            params.pop("dynamicTools")
            params["threadId"] = prior.value
            result = await self.server.request(
                "thread/resume" if self.resume else "thread/fork", params
            )
        else:
            params = self.thread_parameters()
            result = await self.server.request("thread/start", params)
        response = CodexThreadResponse.model_validate(result)
        self.thread_id = response.thread.id
        return self.thread_id

    async def validate_persisted_tools(self, session: SessionId) -> None:
        """Resume cannot change dynamicTools in Codex 0.155.1; compare the native header."""
        response = CodexThreadResponse.model_validate(
            await self.server.request(
                "thread/read",
                {"threadId": session.value, "includeTurns": False},
            )
        )
        if response.thread.path is None:
            raise CodexSchemaRebindingError(
                "Codex cannot verify resumed tools without a persisted rollout; open a fresh session"
            )
        with response.thread.path.open() as source:
            header = CodexRolloutHeader.model_validate_json(source.readline())
        declared = self.thread_parameters()["dynamicTools"]
        if not isinstance(declared, list):
            raise ValueError("dynamic tool declaration must be a list")
        expected = [CodexPersistedTool.model_validate(tool) for tool in declared]
        if header.payload.id != session.value or sorted(
            header.payload.dynamic_tools, key=lambda tool: tool.name
        ) != sorted(expected, key=lambda tool: tool.name):
            raise CodexSchemaRebindingError(
                "Codex cannot change or remove persisted application/output tools on resume; open a fresh session with the intended tools"
            )

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
        configuration.update(self.config.native_capabilities().configuration())
        if self.policy_plugin is not None:
            features = configuration["features"]
            assert isinstance(features, dict)
            features["hooks"] = True
            features["plugins"] = True
            configuration["plugins"] = {
                **{name: {"enabled": False} for name in self.inherited_plugins},
                self.policy_plugin: {"enabled": True},
            }
        configuration["mcp_servers"] = {
            **{name: {"enabled": False} for name in self.inherited_servers},
            **{
                name: {"enabled": True, **server.model_dump(mode="json")}
                for name, server in self.config.mcp_servers.items()
            },
        }
        dynamic: list[JsonValue] = [
            {
                "name": name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for name, tool in self.config.application_tools.items()
        ]
        if self.submission is not None:
            dynamic.append(dynamic_tool(self.submission))
        params["dynamicTools"] = dynamic
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
        native = self.config.native_capabilities()
        if native.write and self.config.sandbox is None:
            params["sandbox"] = "workspace-write"
        if (
            not native.shell
            and not native.write
            and self.config.delegated_tools is None
        ):
            params["sandbox"] = "read-only"
            params["approvalPolicy"] = "never"
        return params

    async def start_turn(self, text: str) -> AcceptedTurn:
        thread_id = await self.ensure_thread()
        channel = CodexTurnChannel(thread_id)
        self.channel = channel
        params: JsonObject = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        # The other half. A named model always brings one, so the home's own
        # effort never rides beside a model the home did not choose.
        selected = self.config.model_selection()
        if "effort" in selected:
            params["effort"] = selected["effort"]
        result = await self.server.request("turn/start", params)
        response = CodexTurnResponse.model_validate(result)
        channel.turn_id = response.turn.id
        identifiers = TurnIdentifiers(
            session=SessionId(value=thread_id),
            turn=TurnId(value=response.turn.id),
        )

        async def complete() -> CompletedTurn:
            return await channel.completed

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
        if message.method != "item/tool/call":
            raise RuntimeError(f"unsupported app-server request {message.method!r}")
        call = DynamicToolCall.model_validate(message.params)
        if (
            self.channel is None
            or self.channel.turn_id != call.turn_id
            or self.thread_id != call.thread_id
        ):
            return {
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "Tool call belongs to a stale or foreign turn.",
                    }
                ],
                "success": False,
            }
        if call.tool in self.config.application_tools:
            return await self.call_application_tool(call)
        submission = self.submission
        if submission is None or call.tool != SUBMISSION_TOOL:
            return {
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "No matching turn output binding is active.",
                    }
                ],
                "success": False,
            }
        response = await submission.submit(call.arguments)
        return {
            "contentItems": [{"type": "inputText", "text": response.message}],
            "success": response.accepted,
        }

    async def call_application_tool(self, call: DynamicToolCall) -> JsonObject:
        """Invoke a declared closure in its hosting process with @lup_tool validation."""
        if not isinstance(call.arguments, dict):
            return {
                "contentItems": [
                    {"type": "inputText", "text": "Tool arguments must be an object."}
                ],
                "success": False,
            }
        try:
            result: ToolResponse = await self.config.application_tools[
                call.tool
            ].handler(call.arguments)
        except Exception as error:
            logging.getLogger(__name__).exception(
                "application tool %s failed", call.tool
            )
            return {
                "contentItems": [
                    {"type": "inputText", "text": f"{call.tool}: {error}"}
                ],
                "success": False,
            }

        def content_items() -> Iterator[JsonValue]:
            for item in result["content"] if "content" in result else []:
                match item:
                    case {"type": "text", "text": str(text)}:
                        yield {"type": "inputText", "text": text}
                    case {"type": "image", "data": str(data), "mimeType": str(mime)}:
                        yield {
                            "type": "inputImage",
                            "imageUrl": f"data:{mime};base64,{data}",
                        }
                    case _:
                        raise ValueError("unsupported application tool content")

        return {
            "contentItems": list(content_items()),
            "success": not ("is_error" in result and result["is_error"]),
        }

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
        responder = CodexApprovalResponder(hooks=self.config.hooks)
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
        if request.server_name in self.config.mcp_servers:
            return {"action": "accept"}
        return {"action": "decline"}

    def handle_notification(self, notification: RpcNotification) -> None:
        if self.channel is not None:
            self.channel.feed(notification)

    def handle_disconnect(self, error: Exception) -> None:
        if self.channel is not None:
            self.channel.fail(error)


class CodexTurnToolBinder(TurnToolBinder):
    """Refresh A-to-A handler state and reject unsafe schema transitions."""

    def __init__(self, state: CodexConversationState) -> None:
        self.state = state

    async def bind[T: BaseModel](self, binding: TurnToolBinding[T] | None) -> None:
        submission = bound_submission(binding) if binding is not None else None
        digest = submission.digest if submission is not None else None
        if self.state.schema_digest is not None and digest != self.state.schema_digest:
            raise CodexSchemaRebindingError(
                "the installed Codex app-server exposes dynamicTools only on "
                "thread/start; changing or removing submit_output would lose "
                "conversation identity"
            )
        self.state.submission = submission
        self.state.schema_digest = digest


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
                "turnId": self.turn_id,
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
        opener = CodexSessionOpener(self.state.config)
        async with opener.open_session(fork_from=SessionId(value=thread_id)) as handle:
            yield handle


class CodexSessionOpener:
    """Open one initialized app-server process per Lup session."""

    def __init__(self, config: CodexSessionConfig) -> None:
        self.config = CodexSessionConfig.model_validate(config)

    @asynccontextmanager
    async def open_session(
        self, resume: SessionId | None = None, *, fork_from: SessionId | None = None
    ) -> AsyncGenerator[SessionHandle]:
        # Installed here rather than where the home is named: installing runs
        # a package manager, and a home is named wherever a request is merely
        # described. A session that opened without the policy it was meant to
        # run under is indistinguishable from one running under it, so a
        # failure is raised rather than warned past.
        allowance = child_recursive_agent_allowance(self.config.environment)
        environment = allowance.environment(self.config.environment)
        config = self.config.model_copy(
            update={
                "environment": environment,
                "mcp_servers": {
                    name: server.model_copy(
                        update={"env": allowance.environment(server.env)}
                    )
                    for name, server in self.config.mcp_servers.items()
                },
            }
        )
        policy_plugin = None
        if config.native_tools and CODEX_HOME in config.environment:
            home = Path(config.environment[CODEX_HOME])
            policy_plugin = await asyncio.to_thread(
                install_declared_policy,
                home,
                root=config.cwd,
                seed=CodexWorktreeHomeStore().derived(home),
            )
        server = CodexAppServer(
            config.executable,
            arguments=(
                (
                    ["--profile", config.named_profile]
                    if config.named_profile is not None
                    else []
                )
                + config.native_capabilities().arguments()
            ),
            environment=config.environment,
        )
        native = config.native_capabilities()
        catalog = await asyncio.to_thread(
            native.model_catalog, config.executable, config.environment, config.model
        )
        directory = TemporaryDirectory(
            prefix="lup-native-",
            dir=Path(config.environment[CODEX_HOME])
            if CODEX_HOME in config.environment
            else None,
        )
        catalog_path = Path(directory.name) / "models.json"
        catalog_path.write_text(json.dumps(catalog))
        server.arguments.extend(
            ["--config", f"model_catalog_json={json.dumps(str(catalog_path))}"]
        )
        try:
            with recursive_agent_scope(allowance):
                await server.start()
        except (Exception, asyncio.CancelledError):
            try:
                await server.close()
            finally:
                directory.cleanup()
            raise
        state = CodexConversationState(
            config,
            server,
            resume,
            policy_plugin.selector if policy_plugin else None,
            {
                item["slug"]: item
                for item in catalog["models"]
                if isinstance(item, dict)
                and "slug" in item
                and isinstance(item["slug"], str)
            }
            if isinstance(catalog["models"], list)
            else {},
            fork_from=fork_from,
        )
        session = ComposedSession(
            state.start_turn,
            CodexTurnToolBinder(state),
            gate_resolver=config.submission_gate_resolver,
            submission_tool=SUBMISSION_TOOL,
        )
        with recursive_agent_scope(allowance):
            async with running_companions(config.companions):
                try:
                    yield SessionHandle(session=session, fork=CodexFork(state))
                finally:
                    try:
                        await session.abort_active()
                    finally:
                        try:
                            await server.close()
                        finally:
                            directory.cleanup()


def create_codex(
    options: CodexSessionConfig | None = None,
    *,
    model: str | None = None,
    system_prompt: str = "",
    cwd: Path | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    native_tools: NativeTools | EllipsisType = ...,
    tools: Sequence[LupMcpTool] | None = None,
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
    if tools is not None and len({tool.name for tool in tools}) != len(tools):
        raise ValueError("application tool names must be unique")
    base = options or CodexSessionConfig(cwd=Path.cwd())
    config = base.model_copy(
        update={
            "model": base.model if model is None else model,
            "developer_instructions": system_prompt or base.developer_instructions,
            "cwd": base.cwd if cwd is None else cwd,
            "native_tools": base.native_tools if native_tools is ... else native_tools,
            "application_tools": base.application_tools
            if tools is None
            else {f"lup_app_{tool.name}": tool for tool in tools},
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


def dynamic_tool(submission: TurnSubmission) -> JsonObject:
    """Render the exact Pydantic schema into the experimental native tool spec."""
    return {
        "name": SUBMISSION_TOOL,
        "description": "Submit the final validated result for this turn.",
        "inputSchema": submission.schema,
        "deferLoading": False,
    }


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
        ):
            return "tool"
        case _:
            return "assistant"


def decode_completed_item(payload: JsonObject) -> list[AnyTurnBlock]:
    """Decode one typed completed app-server item into canonical blocks."""
    from lup.sessions.events import (
        TurnTextBlock,
        TurnThinkingBlock,
        TurnToolCallBlock,
        TurnToolResultBlock,
    )

    match payload:
        case {"type": "agentMessage", "text": str(text)}:
            return [TurnTextBlock(text=text)]
        case {"type": "reasoning", "content": list(content)}:
            return [
                TurnThinkingBlock(thinking="\n".join(str(item) for item in content))
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
                    is_error=status != "completed",
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
                    is_error=status != "completed",
                ),
            ]
            return blocks
        case _:
            return []
