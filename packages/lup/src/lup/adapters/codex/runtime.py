"""Codex app-server SessionFactory with live optional turn capabilities."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lup.adapters.codex.app_server import CodexAppServer, RpcMessage, RpcNotification
from lup.runtime.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.runtime.contracts import (
    EventStream,
    ForkSession,
    Interrupt,
    SessionFactory,
    Steer,
    TurnToolBinder,
)
from lup.runtime.errors import ProviderTurnError, TurnFailure, TurnInterruptedError
from lup.runtime.models import (
    BlockCompletedEvent,
    BlockDeltaEvent,
    SessionHandle,
    SessionId,
    SubmissionDecision,
    SubmissionGateResolver,
    TurnBlock,
    TurnCompletedEvent,
    TurnEvent,
    TurnStartedEvent,
    TurnIdentifiers,
    TurnId,
    TurnInput,
    TurnMessage,
    TurnToolBinding,
)
from lup.runtime.output import submission_schema, submit_output
from lup.types import EnvVars, JsonObject, JsonValue, Usage


class CodexSessionConfig(BaseModel):
    """Immutable Codex-only app-server configuration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    model: str
    developer_instructions: str = ""
    cwd: Path
    executable: Path = Path("codex")
    named_profile: str | None = None
    model_provider: str | None = None
    provider_config: JsonObject | None = None
    sandbox: Literal["readOnly", "workspaceWrite", "dangerFullAccess"] | None = None
    approval_policy: Literal["untrusted", "on-request", "never"] | None = None
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    environment: EnvVars = Field(default_factory=dict)
    submission_gate_resolver: SubmissionGateResolver | None = None
    mcp_servers: dict[str, "CodexMcpServerConfig"] = Field(default_factory=dict)
    writable_roots: list[Path] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_unhandled_approvals(self) -> "CodexSessionConfig":
        if self.approval_policy not in {None, "never"}:
            raise ValueError(
                "this app-server adapter handles dynamic-tool calls only; "
                "approval_policy must be 'never' until native approval requests "
                "are implemented"
            )
        return self


class CodexMcpServerConfig(BaseModel):
    """One project tool group served to Codex over an explicit subprocess."""

    model_config = ConfigDict(frozen=True)

    command: str
    args: list[str] = Field(default_factory=list)
    env: EnvVars = Field(default_factory=dict)


class CodexThreadRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str


class CodexTurnRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    status: str = "inProgress"
    duration_ms: int | None = Field(default=None, alias="durationMs")


class CodexThreadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread: CodexThreadRef


class CodexTurnResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn: CodexTurnRef


class DynamicToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str = Field(alias="threadId")
    turn_id: str = Field(alias="turnId")
    call_id: str = Field(alias="callId")
    tool: str
    arguments: JsonValue


class TokenUsageBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    cached_input_tokens: int = Field(alias="cachedInputTokens")


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

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turn_id: str | None = None
        self.events: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        self.completed: asyncio.Future[CompletedTurn] = (
            asyncio.get_running_loop().create_future()
        )
        self.blocks: list[TurnBlock] = []
        self.usage = Usage()
        self.started = perf_counter()

    def identifiers(self) -> TurnIdentifiers:
        if self.turn_id is None:
            raise RuntimeError("turn notification arrived without a turn identity")
        return TurnIdentifiers(
            session=SessionId(value=self.session_id),
            turn=TurnId(value=self.turn_id),
        )

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
                for block in decode_completed_item(item):
                    self.blocks.append(block)
                    self.events.put_nowait(
                        BlockCompletedEvent(
                            identifiers=self.identifiers(),
                            block=block,
                        )
                    )
            case "thread/tokenUsage/updated", {
                "turnId": str(),
                "tokenUsage": {"last": usage},
            } if isinstance(usage, dict):
                self.usage = decode_usage(usage)
            case "turn/completed", {
                "turn": {"id": str(), "status": str(status)} as turn
            }:
                duration_ms = turn.get("durationMs")  # lup: ignore[dict-get]
                duration = timedelta(
                    milliseconds=duration_ms
                    if isinstance(duration_ms, int)
                    else (perf_counter() - self.started) * 1000
                )
                if status == "completed":
                    messages = (
                        [TurnMessage(role="assistant", blocks=self.blocks)]
                        if self.blocks
                        else []
                    )
                    if not self.completed.done():
                        self.completed.set_result(
                            CompletedTurn(
                                messages=messages,
                                blocks=self.blocks,
                                usage=self.usage,
                                duration=duration,
                            )
                        )
                elif not self.completed.done():
                    native_error = turn.get("error")  # lup: ignore[dict-get]
                    message = (
                        native_error.get("message")  # lup: ignore[dict-get]
                        if isinstance(native_error, dict)
                        else None
                    )
                    failure = TurnFailure(
                        message=(
                            message
                            if isinstance(message, str) and message
                            else f"Codex turn ended with status {status}"
                        ),
                        blocks=self.blocks,
                        usage=self.usage,
                        duration=duration,
                        identifiers=self.identifiers(),
                    )
                    error = (
                        TurnInterruptedError(failure)
                        if status.lower() in {"interrupted", "cancelled", "canceled"}
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
    """Expose only notifications observed while the native turn is live."""

    def __init__(self, channel: CodexTurnChannel) -> None:
        self.channel = channel
        self.consumed = False

    async def iterate(self) -> AsyncIterator[TurnEvent]:
        if self.consumed:
            raise RuntimeError("live event stream can only be consumed once")
        self.consumed = True
        while (
            event
            := await self.channel.events.get()  # lup: ignore[dict-get] — asyncio.Queue
        ) is not None:
            yield event

    def events(self) -> AsyncIterator[TurnEvent]:
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
        self.binding: TurnToolBinding[BaseModel] | None = None
        self.schema_digest: str | None = None
        self.channel: CodexTurnChannel | None = None
        self.server.server_request_handler = self.handle_server_request
        self.server.notification_handler = self.handle_notification
        self.server.disconnect_handler = self.handle_disconnect

    async def ensure_thread(self) -> str:
        if self.thread_id is not None:
            return self.thread_id
        if self.resume is not None:
            if self.binding is not None:
                raise CodexSchemaRebindingError(
                    "Codex thread/resume cannot attach a fresh dynamic-tool handler"
                )
            params = self.thread_parameters()
            params["threadId"] = self.resume.value
            result = await self.server.request("thread/resume", params)
        else:
            params = self.thread_parameters()
            if self.binding is not None:
                params["dynamicTools"] = [dynamic_tool(self.binding)]
            result = await self.server.request("thread/start", params)
        response = CodexThreadResponse.model_validate(result)
        self.thread_id = response.thread.id
        return self.thread_id

    def thread_parameters(self) -> JsonObject:
        """Preserve configured thread behavior for new and resumed threads."""
        params: JsonObject = {
            "model": self.config.model,
            "cwd": str(self.config.cwd),
            "developerInstructions": self.config.developer_instructions,
        }
        if self.config.model_provider is not None:
            params["modelProvider"] = self.config.model_provider
        configuration = dict(self.config.provider_config or {})
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
        self.channel = channel
        params: JsonObject = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        if self.config.effort is not None:
            params["effort"] = self.config.effort
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
        if message.method != "item/tool/call":
            raise RuntimeError(f"unsupported app-server request {message.method!r}")
        call = DynamicToolCall.model_validate(message.params)
        binding = self.binding
        if binding is None or call.tool != "submit_output":
            return {
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "No matching turn output binding is active.",
                    }
                ],
                "success": False,
            }
        if self.channel is None or self.channel.turn_id != call.turn_id:
            return {
                "contentItems": [
                    {"type": "inputText", "text": "Submission belongs to a stale turn."}
                ],
                "success": False,
            }
        response = await submit_output(binding, call.arguments)
        return {
            "contentItems": [{"type": "inputText", "text": response.message}],
            "success": response.accepted,
        }

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
        digest = (
            hashlib.sha256(submission_schema(binding).encode("utf-8")).hexdigest()
            if binding is not None
            else None
        )
        if self.state.thread_id is not None and digest != self.state.schema_digest:
            raise CodexSchemaRebindingError(
                "the installed Codex app-server exposes dynamicTools only on "
                "thread/start; changing or removing submit_output would lose "
                "conversation identity"
            )
        if binding is None:
            self.state.binding = None
        else:
            self.state.binding = erased_binding(binding)
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
    async def open_fork(self, at: TurnId | None) -> AsyncIterator[SessionHandle]:
        if at is not None:
            raise ValueError("Codex thread/fork can only fork the latest thread state")
        thread_id = await self.state.ensure_thread()
        result = await self.state.server.request("thread/fork", {"threadId": thread_id})
        response = CodexThreadResponse.model_validate(result)
        factory = CodexSessionFactory(self.state.config)
        async with factory.open(SessionId(value=response.thread.id)) as handle:
            yield handle


class CodexSessionFactory(SessionFactory):
    """Open one initialized app-server process per Lup session."""

    def __init__(self, config: CodexSessionConfig) -> None:
        self.config = config

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_session(resume)

    @asynccontextmanager
    async def open_session(
        self, resume: SessionId | None
    ) -> AsyncIterator[SessionHandle]:
        server = CodexAppServer(
            self.config.executable,
            arguments=(
                ["--profile", self.config.named_profile]
                if self.config.named_profile is not None
                else None
            ),
            environment=self.config.environment,
        )
        await server.start()
        state = CodexConversationState(self.config, server, resume)
        session = ComposedSession(
            state.start_turn,
            CodexTurnToolBinder(state),
            gate_resolver=self.config.submission_gate_resolver,
        )
        try:
            yield SessionHandle(session=session, fork=CodexFork(state))
        finally:
            try:
                await session.abort_active()
            finally:
                await server.close()


def create_codex_session_factory(config: CodexSessionConfig) -> SessionFactory:
    """Create the named Codex runtime composition root."""
    return CodexSessionFactory(config)


def dynamic_tool(binding: TurnToolBinding[BaseModel]) -> JsonObject:
    """Render the exact Pydantic schema into the experimental native tool spec."""
    return {
        "name": "submit_output",
        "description": "Submit the final validated result for this turn.",
        "inputSchema": binding.output_type.model_json_schema(),
        "deferLoading": False,
    }


def erased_binding[T: BaseModel](
    binding: TurnToolBinding[T],
) -> TurnToolBinding[BaseModel]:
    """Preserve the typed gate while storing a runtime-erased native binding."""
    if binding.gate is None:
        gate = None
    else:
        binding_gate = binding.gate

        async def validate_gate(
            value: BaseModel,  # lup: ignore[bare-basemodel] — adapter-local generic erasure
        ) -> SubmissionDecision:
            typed = binding.output_type.model_validate(value.model_dump(mode="json"))
            return await binding_gate(typed)

        gate = validate_gate
    return TurnToolBinding[BaseModel](
        output_type=binding.output_type,
        store=binding.store,
        gate=gate,
    )


def decode_usage(payload: JsonObject) -> Usage:
    """Decode one app-server token-usage breakdown."""
    native = TokenUsageBreakdown.model_validate(payload)
    return Usage(
        input_tokens=native.input_tokens,
        output_tokens=native.output_tokens,
        cache_read_input_tokens=native.cached_input_tokens,
    )


def decode_completed_item(payload: JsonObject) -> list[TurnBlock]:
    """Decode one typed completed app-server item into canonical blocks."""
    from lup.runtime.models import (
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
            blocks: list[TurnBlock] = [
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
