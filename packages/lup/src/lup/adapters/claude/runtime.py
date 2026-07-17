"""Claude SessionFactory composition with per-turn MCP tool rebinding."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field

from lup.mcp import LupMcpServerConfig, McpServerEntry
from lup.hooks import LupHooksConfig
from lup.runtime.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.runtime.contracts import (
    EventStream,
    ForkSession,
    Interrupt,
    SessionFactory,
    TurnToolBinder,
)
from lup.runtime.errors import ProviderTurnError, TurnFailure
from lup.runtime.models import (
    BlockCompletedEvent,
    BlockDeltaEvent,
    SessionHandle,
    SessionId,
    SubmissionDecision,
    SubmissionGateResolver,
    TurnBlock,
    TurnIdentifiers,
    TurnId,
    TurnCompletedEvent,
    TurnEvent,
    TurnStartedEvent,
    TurnMessage,
    TurnToolBinding,
)
from lup.runtime.output import submit_output
from lup.types import (
    EnvVars,
    JsonObject,
    JsonValue,
    SubagentSpec,
    Usage,
)

if TYPE_CHECKING:
    import claude_agent_sdk as claude
    from claude_agent_sdk import types as claude_types


SESSION_THINKING_TOKENS = 128_000 - 1


class ClaudeSandboxConfig(BaseModel):
    """Claude SDK sandbox settings consumed by this factory."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    auto_allow_bash_if_sandboxed: bool = True
    allow_unsandboxed_commands: bool = False


class ClaudeSessionConfig(BaseModel):
    """Immutable Claude-only provider configuration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    model: str
    system_prompt: str = ""
    coding_harness_preset: bool = True
    tools: list[str] | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    tool_servers: dict[str, McpServerEntry] = Field(default_factory=dict)
    permission_mode: (
        Literal[
            "default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"
        ]
        | None
    ) = "bypassPermissions"
    max_turns: int | None = None
    max_thinking_tokens: int | None = SESSION_THINKING_TOKENS
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    cwd: Path | None = None
    add_dirs: list[Path] = Field(default_factory=list)
    environment: EnvVars = Field(default_factory=dict)
    sandbox: ClaudeSandboxConfig | None = None
    hooks: LupHooksConfig | None = None
    submission_gate_resolver: SubmissionGateResolver | None = None
    subagents: list[SubagentSpec] = Field(default_factory=list)


class ClaudeConversationState:
    """Adapter-private reconnect/resume state for one Lup session."""

    def __init__(self, config: ClaudeSessionConfig, resume: SessionId | None) -> None:
        self.config = config
        self.resume = resume.value if resume is not None else None
        self.session_id = self.resume or str(uuid4())
        self.client: claude.ClaudeSDKClient | None = None
        self.binding: TurnToolBinding[BaseModel] | None = None

    async def disconnect(self) -> None:
        if self.client is None:
            return
        try:
            await self.client.disconnect()
        finally:
            self.client = None

    async def connect(self) -> "claude.ClaudeSDKClient":
        if self.client is not None:
            return self.client
        import claude_agent_sdk as claude

        options = build_claude_options(
            self.config,
            binding=self.binding,
            resume=self.resume,
            session_id=None if self.resume is not None else self.session_id,
        )
        client = claude.ClaudeSDKClient(options=options)
        await client.connect()
        self.client = client
        return client

    async def start_turn(self, text: str) -> AcceptedTurn:
        client = await self.connect()
        await client.query(text, session_id=self.session_id)
        identifiers = TurnIdentifiers(
            session=SessionId(value=self.session_id),
            turn=TurnId(value=uuid4().hex),
        )
        events: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        events.put_nowait(TurnStartedEvent(identifiers=identifiers))

        async def complete() -> CompletedTurn:
            from claude_agent_sdk import types as claude_types

            messages: list[TurnMessage] = []  # lup: ignore[empty-collection]
            result: claude_types.ResultMessage | None = None
            started = perf_counter()
            try:
                async for message in client.receive_response():
                    match message:
                        case claude_types.AssistantMessage(content=content):
                            blocks = [convert_claude_block(block) for block in content]
                            messages.append(
                                TurnMessage(
                                    role="assistant",
                                    blocks=blocks,
                                )
                            )
                            for block in blocks:
                                events.put_nowait(
                                    BlockCompletedEvent(
                                        identifiers=identifiers,
                                        block=block,
                                    )
                                )
                        case claude_types.UserMessage(content=content) if isinstance(
                            content, list
                        ):
                            messages.append(
                                TurnMessage(
                                    role="tool",
                                    blocks=[
                                        convert_claude_block(block) for block in content
                                    ],
                                )
                            )
                        case claude_types.UserMessage(content=str(text)):
                            from lup.runtime.models import TurnTextBlock

                            messages.append(
                                TurnMessage(
                                    role="user", blocks=[TurnTextBlock(text=text)]
                                )
                            )
                        case claude_types.ResultMessage() as terminal:
                            result = terminal
                        case claude_types.StreamEvent(event=event):
                            match event:
                                case {
                                    "type": "content_block_delta",
                                    "delta": {"text": str(delta)},
                                } | {
                                    "type": "content_block_delta",
                                    "delta": {"thinking": str(delta)},
                                }:
                                    events.put_nowait(
                                        BlockDeltaEvent(
                                            identifiers=identifiers,
                                            delta=delta,
                                        )
                                    )
            except Exception as error:
                raise ProviderTurnError(
                    TurnFailure(
                        message=str(error),
                        blocks=[
                            block for message in messages for block in message.blocks
                        ],
                        duration=timedelta(seconds=perf_counter() - started),
                        identifiers=identifiers,
                    )
                ) from error

            if result is None:
                raise ProviderTurnError(
                    TurnFailure(
                        message="Claude completed without a terminal result",
                        blocks=[
                            block for message in messages for block in message.blocks
                        ],
                        identifiers=identifiers,
                    )
                )
            if result.session_id is not None:
                self.session_id = result.session_id
                self.resume = result.session_id
            blocks = [block for message in messages for block in message.blocks]
            usage = claude_usage(result.usage, total_cost_usd=result.total_cost_usd)
            duration = timedelta(milliseconds=result.duration_ms or 0)
            if result.is_error:
                raise ProviderTurnError(
                    TurnFailure(
                        message=str(result.result or "Claude turn failed"),
                        blocks=blocks,
                        usage=usage,
                        duration=duration,
                        identifiers=identifiers,
                    )
                )
            return CompletedTurn(
                messages=messages,
                blocks=blocks,
                usage=usage,
                duration=duration,
            )

        async def complete_with_events() -> CompletedTurn:
            try:
                return await complete()
            finally:
                events.put_nowait(TurnCompletedEvent(identifiers=identifiers))
                events.put_nowait(None)

        completion = asyncio.create_task(complete_with_events())

        def observe_completion(task: asyncio.Task[CompletedTurn]) -> None:
            if not task.cancelled():
                task.exception()

        completion.add_done_callback(observe_completion)

        async def await_completion() -> CompletedTurn:
            return await completion

        return AcceptedTurn(
            identifiers=identifiers,
            complete=await_completion,
            events=ClaudeLiveEventStream(events),
            interrupt=ClaudeInterrupt(self),
        )


class ClaudeLiveEventStream(EventStream):
    """Expose SDK partial-message events separately from completed replay."""

    def __init__(self, events: asyncio.Queue[TurnEvent | None]) -> None:
        self.queue = events
        self.consumed = False

    async def iterate(self) -> AsyncIterator[TurnEvent]:
        if self.consumed:
            raise RuntimeError("live event stream can only be consumed once")
        self.consumed = True
        while (event := await self.queue.get()) is not None:  # lup: ignore[dict-get]
            yield event

    def events(self) -> AsyncIterator[TurnEvent]:
        return self.iterate()


class ClaudeTurnToolBinder(TurnToolBinder):
    """Reconnect on every binding so schema and handler state are both current."""

    def __init__(self, state: ClaudeConversationState) -> None:
        self.state = state

    async def bind[T: BaseModel](self, binding: TurnToolBinding[T] | None) -> None:
        if binding is None and self.state.binding is None:
            return
        await self.state.disconnect()
        if binding is None:
            self.state.binding = None
            return

        async def gate(
            value: BaseModel,  # lup: ignore[bare-basemodel] — adapter-local generic erasure
        ) -> SubmissionDecision:
            if binding.gate is None:
                return SubmissionDecision(accepted=True)
            typed = binding.output_type.model_validate(value.model_dump(mode="json"))
            return await binding.gate(typed)

        self.state.binding = TurnToolBinding[BaseModel](
            output_type=binding.output_type,
            store=binding.store,
            gate=gate if binding.gate is not None else None,
        )


class ClaudeInterrupt(Interrupt):
    """Interrupt the currently connected Claude turn."""

    def __init__(self, state: ClaudeConversationState) -> None:
        self.state = state

    async def interrupt(self) -> None:
        if self.state.client is not None:
            await self.state.client.interrupt()


class ClaudeFork(ForkSession):
    """Fork the latest persisted Claude transcript into a new typed session."""

    def __init__(self, state: ClaudeConversationState) -> None:
        self.state = state

    def fork(
        self, at: TurnId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_fork(at)

    @asynccontextmanager
    async def open_fork(self, at: TurnId | None) -> AsyncGenerator[SessionHandle]:
        if at is not None:
            raise ValueError("Claude transcript forking supports the latest turn only")
        import claude_agent_sdk as claude

        directory = (
            str(self.state.config.cwd) if self.state.config.cwd is not None else None
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await asyncio.get_running_loop().run_in_executor(
                executor,
                claude.fork_session,
                self.state.session_id,
                directory,
            )
        factory = ClaudeSessionFactory(self.state.config)
        async with factory.open(SessionId(value=result.session_id)) as handle:
            yield handle


class ClaudeSessionFactory(SessionFactory):
    """Open independently configured reconnecting Claude sessions."""

    def __init__(self, config: ClaudeSessionConfig) -> None:
        self.config = config

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_session(resume)

    @asynccontextmanager
    async def open_session(
        self, resume: SessionId | None
    ) -> AsyncGenerator[SessionHandle]:
        state = ClaudeConversationState(self.config, resume)
        session = ComposedSession(
            starter=state.start_turn,
            binder=ClaudeTurnToolBinder(state),
            gate_resolver=self.config.submission_gate_resolver,
        )
        try:
            yield SessionHandle(session=session, fork=ClaudeFork(state))
        finally:
            try:
                await session.abort_active()
            finally:
                await state.disconnect()


def create_claude_session_factory(
    config: ClaudeSessionConfig,
) -> SessionFactory:
    """Create the named Claude runtime composition root."""
    return ClaudeSessionFactory(config)


def build_submission_server(
    binding: TurnToolBinding[BaseModel],
) -> LupMcpServerConfig:
    """Build an exact-schema MCP server whose handler closes over this turn."""
    server = Server("lup-output", version="1")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="submit_output",
                description="Submit the final validated result for this turn.",
                inputSchema=binding.output_type.model_json_schema(),
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: JsonObject) -> CallToolResult:
        if name != "submit_output":
            raise ValueError(f"unknown output tool {name!r}")
        response = await submit_output(binding, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=response.message)],
            isError=not response.accepted,
        )

    return LupMcpServerConfig(
        name="lup-output",
        server=server,
        tool_names=["submit_output"],
    )


def build_claude_options(
    config: ClaudeSessionConfig,
    *,
    binding: TurnToolBinding[BaseModel] | None,
    resume: str | None,
    session_id: str | None,
) -> "claude.ClaudeAgentOptions":
    """Build SDK options lazily and never enable native structured output."""
    import claude_agent_sdk as claude
    from claude_agent_sdk import types as claude_types
    from lup.adapters.claude.hooks import lup_hooks_to_claude

    servers = dict(config.tool_servers)
    allowed = list(config.allowed_tools)
    if binding is not None:
        servers["lup-output"] = build_submission_server(binding)
        allowed.append("mcp__lup-output__submit_output")

    def native_server(server: McpServerEntry) -> "claude_types.McpServerConfig":
        match server:
            case LupMcpServerConfig():
                return claude_types.McpSdkServerConfig(
                    type="sdk", name=server.name, instance=server.server
                )
            case _:
                return server

    sandbox = (
        claude_types.SandboxSettings(
            enabled=config.sandbox.enabled,
            autoAllowBashIfSandboxed=config.sandbox.auto_allow_bash_if_sandboxed,
            allowUnsandboxedCommands=config.sandbox.allow_unsandboxed_commands,
        )
        if config.sandbox is not None
        else None
    )
    system_prompt: str | claude_types.SystemPromptPreset | None = (
        {
            "type": "preset",
            "preset": "claude_code",
            "append": config.system_prompt,
        }
        if config.coding_harness_preset
        else config.system_prompt or None
    )
    return claude.ClaudeAgentOptions(
        model=config.model,
        system_prompt=system_prompt,
        tools=config.tools,
        allowed_tools=list(dict.fromkeys(allowed)),
        mcp_servers={name: native_server(server) for name, server in servers.items()},
        agents={
            spec.name: claude_types.AgentDefinition(
                description=spec.description,
                prompt=spec.prompt,
                tools=spec.tools,
                model=spec.model,
            )
            for spec in config.subagents
        }
        or None,
        permission_mode=config.permission_mode,
        max_turns=config.max_turns,
        max_thinking_tokens=config.max_thinking_tokens,
        effort=config.effort,
        cwd=config.cwd,
        add_dirs=[str(path) for path in config.add_dirs],
        env=config.environment,
        sandbox=sandbox,
        hooks=(
            lup_hooks_to_claude(config.hooks)
            if config.hooks is not None and config.hooks.by_event()
            else None
        ),
        include_partial_messages=True,
        resume=resume,
        session_id=session_id,
        output_format=None,
    )


def convert_claude_block(block: "claude.ContentBlock") -> TurnBlock:
    """Convert one SDK block directly into the portable runtime vocabulary."""
    import claude_agent_sdk as claude
    from claude_agent_sdk import types as claude_types

    match block:
        case claude.TextBlock(text=text):
            from lup.runtime.models import TurnTextBlock

            return TurnTextBlock(text=text)
        case claude.ThinkingBlock(thinking=thinking, signature=signature):
            from lup.runtime.models import TurnThinkingBlock

            return TurnThinkingBlock(
                thinking=thinking or "", redacted=not thinking and bool(signature)
            )
        case claude.ToolUseBlock(id=identifier, name=name, input=input_data):
            from lup.runtime.models import TurnToolCallBlock

            return TurnToolCallBlock(
                id=identifier, name=name, arguments=input_data or {}
            )
        case claude.ToolResultBlock(tool_use_id=identifier, content=content):
            from lup.runtime.models import TurnToolResultBlock

            rendered = (
                content
                if isinstance(content, str)
                else json.dumps(content, default=str)
            )
            return TurnToolResultBlock(
                tool_call_id=identifier,
                content=rendered or "",
            )
        case claude_types.ServerToolUseBlock(
            id=identifier, name=name, input=input_data
        ):
            from lup.runtime.models import TurnToolCallBlock

            return TurnToolCallBlock(
                id=identifier, name=name, arguments=input_data or {}
            )
        case claude_types.ServerToolResultBlock(
            tool_use_id=identifier, content=content
        ):
            from lup.runtime.models import TurnToolResultBlock

            return TurnToolResultBlock(
                tool_call_id=identifier,
                content=content if isinstance(content, str) else str(content),
            )
        case _:
            from lup.runtime.models import TurnTextBlock

            return TurnTextBlock(text=str(block))


def claude_usage(
    raw: Mapping[str, JsonValue] | None,
    *,
    total_cost_usd: float | None = None,
) -> Usage:
    """Normalize only the portable count fields from Claude's open payload."""
    if raw is None:
        return Usage(cost_usd=total_cost_usd)

    def count(name: str) -> int:
        value = raw.get(name)  # lup: ignore[dict-get] -- vendor payload
        return value if isinstance(value, int) else 0

    return Usage(
        cost_usd=total_cost_usd,
        input_tokens=count("input_tokens")
        + count("cache_read_input_tokens")
        + count("cache_creation_input_tokens"),
        output_tokens=count("output_tokens"),
        cache_read_input_tokens=count("cache_read_input_tokens"),
        cache_creation_input_tokens=count("cache_creation_input_tokens"),
    )
