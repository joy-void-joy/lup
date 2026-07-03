"""The ``claude`` engine: the Claude Agent SDK behind the neutral seam.

Runs Anthropic models with the full scaffolding — in-process MCP
servers, permission hooks, native subagents, the SDK sandbox. Four
sections, in order:

- engine construction — :class:`ClaudeEngine` and the neutral→native
  option translation (:func:`build_claude_options`);
- SDK adaptation — hook, subagent, block, message, MCP-server, and tool
  conversion between lup types and SDK types;
- sessions and clients — :class:`ResponseCollector`,
  :class:`ClaudeSession`, and :class:`ClaudeClient`, the run path;
- background agents — :class:`ClaudeBackgroundAgent`.

``claude-compat`` (:mod:`lup.adapters.claude_compat`) points this same
scaffolding at Anthropic-protocol-compatible endpoints.
"""

import asyncio
import copy
import json
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
)
from contextlib import asynccontextmanager
from typing import Any  # lup: ignore — confined to SdkDict, the SDK's payload type

from pydantic import BaseModel

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContentBlock,
    HookInput,
    Message,
    SdkMcpTool,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    AgentDefinition,
    AssistantMessage,
    EffortLevel,
    HookContext,
    HookEvent,
    HookMatcher,
    McpSdkServerConfig,
    PreToolUseHookSpecificOutput,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    SyncHookJSONOutput,
    SystemMessage,
    SystemPromptPreset,
    UserMessage,
)

from lup.adapters.common import Client, Engine, Session
from lup.background import BackgroundAgentParams, BaseBackgroundAgent
from lup.mcp import (
    LupMcpServerConfig,
    LupMcpTool,
    LupToolHandler,
    McpServerEntry,
    RawMcpServerConfig,
)
from lup.options import LupAgentOptions
from lup.trace import TraceLogger, print_message
from lup.types import (
    JsonObject,
    JsonValue,
    LupAssistantMessage,
    LupContentBlock,
    LupDoneEvent,
    LupEvent,
    LupHookEvent,
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    LupMessage,
    LupResponse,
    LupResultMessage,
    LupSystemMessage,
    LupTextBlock,
    LupTextEvent,
    LupThinkingBlock,
    LupThinkingEvent,
    LupToolResultBlock,
    LupToolResultEvent,
    LupToolUseBlock,
    LupToolUseEvent,
    LupUserMessage,
    SubagentSpec,
    Usage,
    extract_token_usage,
    normalize_effort,
    safe_normalize_usage,
)

logger = logging.getLogger(__name__)

HARNESS_THINKING_TOKENS = 128_000 - 1
"""Session-grade thinking default: as hard as the API allows. Applied only
under ``harness_prompt`` — a nested call keeps the SDK default."""


def server_to_claude(
    entry: McpServerEntry,
) -> McpSdkServerConfig | RawMcpServerConfig:
    """Narrow one neutral MCP entry to its Claude SDK form.

    An in-process ``LupMcpServerConfig`` becomes an SDK ``sdk`` server wrapping
    its live instance; an external transport config passes straight through.
    """
    match entry:
        case LupMcpServerConfig():
            return lup_server_to_claude(entry)
        case _:
            return entry


def claude_effort(reasoning_effort: str | None) -> EffortLevel | None:
    """Map a generic effort level to the Claude SDK's ``EffortLevel``.

    The normalized value is matched against the literal's members, so an
    unrecognized effort is dropped rather than smuggled through with a cast.
    """
    match normalize_effort(reasoning_effort, "claude"):
        case "low" | "medium" | "high" | "xhigh" | "max" as level:
            return level
        case _:
            return None


def build_claude_options(opts: LupAgentOptions) -> ClaudeAgentOptions:
    """Assemble the native ``ClaudeAgentOptions`` from neutral options.

    ``harness_prompt`` selects the session-grade shape: the ``claude_code``
    preset wraps the system prompt and the harness policy defaults apply —
    think as hard as the API allows, bypass per-call permission prompts
    (enforcement is the hook layer the options carry). Without it the
    prompt is used raw and SDK defaults stand: the shape of a nested LLM
    call.
    """
    system_prompt: str | SystemPromptPreset | None
    max_thinking = opts.max_thinking_tokens
    permission_mode = opts.permission_mode
    if opts.harness_prompt:
        system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": opts.system_prompt,
        }
        max_thinking = HARNESS_THINKING_TOKENS if max_thinking is None else max_thinking
        permission_mode = permission_mode or "bypassPermissions"
    else:
        system_prompt = opts.system_prompt or None

    extra_args: dict[str, str | None] = {}
    if not opts.persist_session:
        extra_args["no-session-persistence"] = None

    mcp_servers = {
        name: server_to_claude(server) for name, server in opts.tool_servers.items()
    }
    subagents = {spec.name: spec_to_claude(spec) for spec in opts.subagents}

    return ClaudeAgentOptions(
        model=opts.model,
        system_prompt=system_prompt,
        tools=opts.tools,
        max_thinking_tokens=max_thinking,
        permission_mode=permission_mode,
        extra_args=extra_args,
        hooks=lup_hooks_to_claude(opts.hooks) if opts.hooks else None,
        sandbox=(
            {
                "enabled": True,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
            }
            if opts.sdk_sandbox
            else None
        ),
        mcp_servers=mcp_servers,
        agents=subagents or None,
        add_dirs=[str(d) for d in opts.add_dirs],
        allowed_tools=opts.allowed_tools,
        max_turns=opts.max_turns,
        max_budget_usd=opts.max_budget_usd,
        effort=claude_effort(opts.reasoning_effort),
        output_format=(
            {"type": "json_schema", "schema": opts.output_schema}
            if opts.output_schema
            else None
        ),
    )


class ClaudeEngine(Engine):
    """Anthropic models on the Claude Agent SDK.

    Consumes the in-process mechanism payloads (hooks, tool servers,
    native subagent definitions); ignores the subprocess ones (served
    tool groups, the ``codex`` block).
    """

    id = "claude"

    unsupported = ("turn_timeout_seconds",)
    """The one intent knob the SDK has no lever for: a client-side turn
    timeout."""

    def native_options(self, opts: LupAgentOptions) -> ClaudeAgentOptions:
        """Translate neutral options to the SDK's — the compat seam."""
        return build_claude_options(opts)

    def client(self, opts: LupAgentOptions) -> Client:
        return ClaudeClient(self.native_options(self.enforce(opts)))

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        """Claude backgrounds can act through tools; opus-class by default."""
        return ClaudeBackgroundAgent(
            name=params.name,
            system_prompt=params.system_prompt,
            tools=params.tools or [],
            build_message=params.build_message,
            start_message=params.start_message,
            model=params.model or "claude-opus-4-6",
            debounce_seconds=params.debounce_seconds,
            builtin_tools=params.builtin_tools,
            allowed_tools=params.allowed_tools,
            on_response=params.on_response,
        )


type ClaudeHooksConfig = dict[HookEvent, list[HookMatcher]]


def build_claude_hook_handler(
    lup_matcher: LupHookMatcher,
    *,
    event: LupHookEvent,
) -> Callable[[HookInput, str | None, HookContext], Awaitable[SyncHookJSONOutput]]:
    """Build a Claude SDK hook handler from a LupHookMatcher.

    ``event`` is the hook event this handler is registered under — the
    output conversion depends on it (permission decisions exist only on
    PreToolUse).
    """
    hook_fn = lup_matcher.hook

    async def claude_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        lup_input = LupHookInput(
            hook_event_name=input_data.get("hook_event_name", ""),
            tool_name=input_data.get("tool_name", ""),
            tool_input=input_data.get("tool_input", {}),
        )
        if "stop_hook_active" in input_data:
            lup_input["stop_hook_active"] = input_data["stop_hook_active"]
        if "tool_response" in input_data:
            response = input_data["tool_response"]
            lup_input["tool_result"] = (
                response
                if isinstance(response, str)
                else json.dumps(response, default=str)
            )

        lup_output = await hook_fn(lup_input)
        return lup_hook_output_to_claude(lup_output, event=event)

    return claude_hook


def lup_hooks_to_claude(hooks: LupHooksConfig) -> ClaudeHooksConfig:
    """Convert SDK-agnostic LupHooksConfig to Claude SDK hook format."""
    result: ClaudeHooksConfig = {}

    for event_name, matchers in hooks.items():
        claude_matchers: list[HookMatcher] = []
        for lup_matcher in matchers:
            handler = build_claude_hook_handler(lup_matcher, event=event_name)
            if lup_matcher.matcher:
                claude_matchers.append(
                    HookMatcher(matcher=lup_matcher.matcher, hooks=[handler])
                )
            else:
                claude_matchers.append(HookMatcher(hooks=[handler]))

        result[event_name] = claude_matchers

    return result


def lup_hook_output_to_claude(
    output: LupHookOutput,
    *,
    event: LupHookEvent = "PreToolUse",
) -> SyncHookJSONOutput:
    """Convert a LupHookOutput to Claude SDK SyncHookJSONOutput.

    Permission decisions (``allow``/``deny``) exist only on PreToolUse;
    on every other event a denial converts to the generic ``block``
    decision, and an allow is a no-op output.
    """
    decision = output.get("decision")
    reason = output.get("reason", "")
    system_message = output.get("system_message")

    match event, decision:
        case ("PreToolUse", "allow"):
            return SyncHookJSONOutput(
                hookSpecificOutput=PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="allow",
                )
            )
        case ("PreToolUse", "deny"):
            return SyncHookJSONOutput(
                hookSpecificOutput=PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="deny",
                    permissionDecisionReason=reason,
                )
            )
        case (_, "deny" | "block"):
            return SyncHookJSONOutput(decision="block", reason=reason)
        case _:
            if system_message:
                return SyncHookJSONOutput(systemMessage=system_message)
            return SyncHookJSONOutput()


def spec_to_claude(spec: SubagentSpec) -> AgentDefinition:
    """Convert a SubagentSpec to a Claude AgentDefinition.

    ``AgentDefinition.model`` is ``str | None`` and accepts both the
    short aliases (``sonnet``/``opus``/``haiku``) and full model IDs
    (``claude-opus-4-6``), so the spec's model passes straight through
    rather than collapsing unknown IDs to the inherited main-loop model.
    A spec without a model (``None``) inherits the main-loop model —
    the same semantics ``run_subagent`` gives it on other backends.
    """
    return AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,
        tools=spec.tools,
        model=spec.model,
    )


def claude_block_to_lup(block: ContentBlock) -> LupContentBlock:
    """Convert a Claude SDK ContentBlock to a LupContentBlock."""
    if hasattr(block, "type") and getattr(block, "type", None) == "redacted_thinking":
        return LupThinkingBlock(thinking="", redacted=True)

    match block:
        case ThinkingBlock():
            is_redacted = not block.thinking and bool(block.signature)
            return LupThinkingBlock(thinking=block.thinking or "", redacted=is_redacted)
        case TextBlock():
            return LupTextBlock(text=block.text)
        case ToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case ToolResultBlock():
            return LupToolResultBlock(
                tool_use_id=block.tool_use_id, content=block.content
            )
        case ServerToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case ServerToolResultBlock():
            content = (
                block.content if isinstance(block.content, str) else str(block.content)
            )
            return LupToolResultBlock(tool_use_id=block.tool_use_id, content=content)
        case _:
            return LupTextBlock(text=str(block))


def claude_message_to_lup(message: Message) -> LupMessage | None:
    """Convert a Claude SDK Message to a LupMessage.

    Returns None for message types that have no lup equivalent
    (e.g. stream events).
    """
    match message:
        case AssistantMessage():
            blocks = [claude_block_to_lup(b) for b in message.content]
            return LupAssistantMessage(content=blocks)
        case UserMessage():
            if isinstance(message.content, list):
                blocks = [claude_block_to_lup(b) for b in message.content]
                return LupUserMessage(content=blocks)
            return LupUserMessage(content=message.content)
        case SystemMessage():
            data = (
                json.dumps(message.data)
                if isinstance(message.data, dict)
                else str(message.data)
            )
            return LupSystemMessage(subtype=message.subtype, data=data)
        case ResultMessage():
            return None
        case _:
            return None


def lup_server_to_claude(config: LupMcpServerConfig) -> McpSdkServerConfig:
    """Convert a LupMcpServerConfig to a Claude SDK McpSdkServerConfig."""
    return McpSdkServerConfig(type="sdk", name=config.name, instance=config.server)


type SdkDict = dict[str, Any]  # lup: ignore — the SDK's tool-handler payload type


def lup_tools_to_sdk(
    tools: list[LupMcpTool],
) -> list[SdkMcpTool[JsonObject]]:
    """Convert LupMcpTool list to Claude SDK SdkMcpTool list.

    ``SdkMcpTool.handler`` must return the SDK's untyped dict. A
    ``ToolResponse`` is a dict at runtime, so each handler is adapted
    with a shallow copy instead of widening ``LupToolHandler`` itself.
    """

    def as_sdk(handler: LupToolHandler) -> Callable[[JsonObject], Awaitable[SdkDict]]:
        async def call(args: JsonObject) -> SdkDict:
            return dict(await handler(args))

        return call

    return [
        SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=as_sdk(t.handler),
        )
        for t in tools
    ]


type ClaudeUsageNormalizer = Callable[[Mapping[str, JsonValue]], Usage | None]
"""Transforms the raw Claude SDK usage payload into a (subclass of) Usage."""


class ResponseCollector:
    """Drains a queried client's response stream, accumulating once.

    The single collector for the Claude path: ``async for`` over it yields
    each SDK message while accumulating state, ``collect()`` drains the rest
    with display/tracing, and ``to_lup_response()`` projects the accumulated
    SDK state into lup types. Every Claude run — session or one-shot —
    drains through it via ``ClaudeSession.send``, so there is one
    message-draining loop rather than two that can drift.

    After iteration, access the accumulated SDK state: ``blocks``,
    ``tool_results``, ``messages``, ``result``.
    """

    def __init__(
        self,
        client: ClaudeSDKClient,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> None:
        self.client = client
        self.blocks: list[ContentBlock] = []
        self.tool_results: list[ContentBlock] = []
        self.messages: list[AssistantMessage | UserMessage] = []
        self.result: ResultMessage | None = None
        self.trace_logger = trace_logger
        self.prefix = prefix

    @property
    def text(self) -> str | None:
        """Concatenated text from all assistant text blocks, or ``None``."""
        texts = [b.text for b in self.blocks if isinstance(b, TextBlock)]
        return "\n\n".join(texts) if texts else None

    def output[T: BaseModel](self, output_type: type[T]) -> T | None:
        """Extract structured output as a validated Pydantic model, or ``None``."""
        if self.result is not None and self.result.structured_output:
            return output_type.model_validate(self.result.structured_output)
        return None

    async def __aiter__(self) -> AsyncIterator[Message]:
        """Yield messages, accumulating state but not displaying.

        Raises RuntimeError on agent error results — after logging,
        tracing, and yielding the failing ResultMessage, so consumers
        see it and the trace records what went wrong.
        """
        async for message in self.client.receive_response():
            match message:
                case AssistantMessage():
                    self.messages.append(message)
                    for block in message.content:
                        self.blocks.append(block)

                case ResultMessage():
                    self.result = message
                    if message.is_error:
                        logger.error("Agent error result: %s", message.result)
                        if self.trace_logger:
                            self.trace_logger.log_text(
                                str(message.result), heading="Agent error result"
                            )

                case SystemMessage():
                    logger.info("System [%s]: %s", message.subtype, message.data)

                case UserMessage():
                    self.messages.append(message)
                    if isinstance(message.content, list):
                        for block in message.content:
                            self.tool_results.append(block)

            yield message

            if isinstance(message, ResultMessage) and message.is_error:
                raise RuntimeError(f"Agent error: {message.result}")

    async def collect(self) -> ResultMessage:
        """Drain all messages, displaying and tracing each one.

        Raises:
            RuntimeError: If the agent returns an error or no result.
        """
        async for message in self:
            lup_msg = claude_message_to_lup(message)
            if lup_msg is not None:
                print_message(lup_msg, prefix=self.prefix, trace=self.trace_logger)

        if self.result is None:
            raise RuntimeError("No result received from agent")
        return self.result

    def to_lup_response(
        self, usage_normalizer: "ClaudeUsageNormalizer" = extract_token_usage
    ) -> LupResponse:
        """Project the accumulated SDK state into a ``LupResponse``.

        Call after ``collect()``. ``usage_normalizer`` shapes the raw SDK usage
        payload — a subclass may carry vendor-specific fields.
        """
        response = LupResponse()
        for message in self.messages:
            match message:
                case AssistantMessage():
                    blocks = [claude_block_to_lup(b) for b in message.content]
                    response.messages.append(LupAssistantMessage(content=blocks))
                    response.blocks.extend(blocks)
                case UserMessage() if isinstance(message.content, list):
                    blocks = [claude_block_to_lup(b) for b in message.content]
                    response.messages.append(LupUserMessage(content=blocks))
                    response.tool_results.extend(blocks)
        if self.result is not None:
            response.session_id = self.result.session_id
            response.result = LupResultMessage(
                structured_output=self.result.structured_output,
                is_error=self.result.is_error,
                result=self.result.result,
                duration_ms=self.result.duration_ms,
                total_cost_usd=self.result.total_cost_usd,
                usage=safe_normalize_usage(usage_normalizer, self.result.usage),
            )
        return response


async def collect_lup_response(
    client: ClaudeSDKClient,
    *,
    usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> LupResponse:
    """Drain a queried client's response stream into a LupResponse.

    The lup-typed projection of :class:`ResponseCollector` —
    ``ClaudeSession.send`` collects through it. Displays and traces
    each message as it arrives, raises on agent errors and on streams that
    end without a result.
    """
    collector = ResponseCollector(client, trace_logger=trace_logger, prefix=prefix)
    await collector.collect()
    return collector.to_lup_response(usage_normalizer)


class ClaudeSession(Session):
    """Multi-turn conversation via the Claude Agent SDK.

    ``id`` carries the SDK session id: seeded when the session was opened
    with ``resume=``, refreshed from each turn's result otherwise.
    """

    def __init__(
        self,
        client: ClaudeSDKClient,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
        resumed: str | None = None,
    ) -> None:
        self.client = client
        self.usage_normalizer = usage_normalizer
        self.id = resumed

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        await self.client.query(prompt)
        response = await collect_lup_response(
            self.client,
            usage_normalizer=self.usage_normalizer,
            trace_logger=trace_logger,
            prefix=prefix,
        )
        self.id = response.session_id or self.id
        return response

    async def interrupt(self) -> None:
        await self.client.interrupt()


class ClaudeClient(Client):
    """Run prompts via the Claude Agent SDK.

    Args:
        options: Native SDK options built by the engine.
        usage_normalizer: Transforms the raw SDK usage payload into a
            ``Usage`` (or subclass, for vendor-specific fields).
    """

    def __init__(
        self,
        options: ClaudeAgentOptions,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    ) -> None:
        self.options = options
        self.usage_normalizer = usage_normalizer

    @asynccontextmanager
    async def session(
        self, *, resume: str | None = None
    ) -> AsyncGenerator[Session, None]:
        options = self.options
        if resume:
            options = copy.copy(self.options)
            options.resume = resume
        async with ClaudeSDKClient(options=options) as client:
            yield ClaudeSession(
                client, usage_normalizer=self.usage_normalizer, resumed=resume
            )

    async def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Stream events live from the Claude SDK."""
        collected: list[LupContentBlock] = []
        async with ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                lup_msg = claude_message_to_lup(message)
                if lup_msg is not None and trace_logger:
                    print_message(lup_msg, prefix=prefix, trace=trace_logger)

                match message:
                    case AssistantMessage():
                        for block in message.content:
                            collected.append(claude_block_to_lup(block))
                            match block:
                                case ThinkingBlock():
                                    if block.thinking:
                                        yield LupThinkingEvent(thinking=block.thinking)
                                case TextBlock():
                                    yield LupTextEvent(text=block.text)
                                case ToolUseBlock():
                                    yield LupToolUseEvent(id=block.id, name=block.name)
                    case UserMessage():
                        if isinstance(message.content, list):
                            for block in message.content:
                                if isinstance(block, ToolResultBlock):
                                    yield LupToolResultEvent(
                                        tool_use_id=block.tool_use_id,
                                        content=str(block.content),
                                    )
                    case ResultMessage():
                        yield LupDoneEvent(blocks=collected)
                        if message.is_error:
                            raise RuntimeError(f"Agent error: {message.result}")


class ClaudeBackgroundAgent(BaseBackgroundAgent):
    """Background agent running via the Claude Agent SDK.

    Runs an independent SDK client with its own MCP tools and system
    prompt. Communicates with the main agent through shared mutable
    state — the background agent's tools write to objects (lists, dicts)
    that the main agent's tools read.
    """

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: list[LupMcpTool],
        build_message: Callable[[], str | None],
        start_message: str = "",
        model: str = "claude-opus-4-6",
        max_thinking_tokens: int | None = None,
        debounce_seconds: float = 3.0,
        builtin_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        on_response: Callable[[AssistantMessage], None] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            build_message=build_message,
            start_message=start_message,
            model=model,
            debounce_seconds=debounce_seconds,
        )
        self.tools = tools
        # ThinkingConfigEnabled(budget_tokens=N) is the newer alternative
        self.max_thinking_tokens = max_thinking_tokens or (128_000 - 1)
        self.builtin_tools = builtin_tools
        self.allowed_tools = allowed_tools
        self.on_response = on_response

    async def sdk_message_stream(self) -> AsyncGenerator[JsonObject, None]:
        """Adapt the shared turn stream into the SDK's streaming-input dicts.

        The one place a turn becomes the SDK's ``connect`` wire shape (a
        JSON object) — the debounced loop lives on the base class, and only
        this boundary speaks the SDK's dict format.
        """
        async for content in self.message_stream():
            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
            }

    async def run_loop(self) -> None:
        """Create SDK client, connect with message generator, process responses."""
        sdk_tools = lup_tools_to_sdk(self.tools)
        server = create_sdk_mcp_server(
            name=self.name,
            version="1.0.0",
            tools=sdk_tools,
        )

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=self.system_prompt,
            max_thinking_tokens=self.max_thinking_tokens,
            permission_mode="bypassPermissions",
            tools=self.builtin_tools,
            mcp_servers={self.name: server},
            allowed_tools=self.allowed_tools or [],
            extra_args={"no-session-persistence": None},
        )

        try:
            client = ClaudeSDKClient(options=options)
            await client.connect(self.sdk_message_stream())
            try:
                async for msg in client.receive_messages():
                    self.handle_response(msg)
            finally:
                await client.disconnect()
        except asyncio.CancelledError:
            logger.debug("Background agent '%s' cancelled", self.name)
        except Exception:
            logger.exception("Background agent '%s' crashed", self.name)

    def handle_response(self, msg: object) -> None:
        """Route response messages for logging."""
        match msg:
            case AssistantMessage():
                if self.on_response:
                    self.on_response(msg)
            case ResultMessage():
                if msg.is_error:
                    logger.error(
                        "Background agent '%s' error: %s", self.name, msg.result
                    )
