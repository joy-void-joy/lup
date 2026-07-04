"""The ``claude`` engine: the Claude Agent SDK behind the neutral seam.

Runs Anthropic models with the full scaffolding — in-process MCP
servers, permission hooks, native subagents, the SDK sandbox. Three
sections, in order:

- construction — :func:`create_claude` and the neutral→native option
  translation (:func:`build_claude_options`), shared with
  ``claude-compat`` (:mod:`lup.adapters.clients.claude_compat`);
- SDK adaptation — hook, subagent, block, message, and tool conversion
  between lup types and SDK types;
- sessions and clients — :class:`ResponseCollector`, :class:`ClaudeSession`,
  and :class:`ClaudeClient`, the run path.

The SDK is imported as a qualified namespace (``claude`` for the package,
``claude_types`` for its ``types`` submodule) so every SDK type reads with
its origin visible at the use site.
"""
#lup: What's not clear here is: Where is background/claude.py, profiles/claude.py, etc... initiated and used. They should all converge somewhere. We should use deeper nested folder

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

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types
from pydantic import BaseModel

from lup.adapters.clients.common import (
    Client,
    Session,
    extract_token_usage,
    query_via_session,
    refuse_unconsumed,
    safe_normalize_usage,
)
from lup.adapters.common import LupAgentOptions
from lup.hooks import (
    LupHookEvent,
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
)
from lup.mcp import (
    LupMcpServerConfig,
    LupMcpTool,
    LupToolHandler,
    RawMcpServerConfig,
)
from lup.paths import extract_glob_dir
from lup.trace import TraceLogger, print_message
from lup.types import (
    JsonObject,
    JsonValue,
    LupAssistantMessage,
    LupContentBlock,
    LupDoneEvent,
    LupEvent,
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
)

logger = logging.getLogger(__name__)

HARNESS_THINKING_TOKENS = 128_000 - 1
"""Session-grade thinking default: as hard as the API allows. Applied only
under ``harness_preset`` — a nested call keeps the SDK default."""


def build_claude_options(opts: LupAgentOptions) -> claude.ClaudeAgentOptions:
    """Assemble the native ``ClaudeAgentOptions`` from neutral options.

    ``harness_preset`` selects the session-grade shape: the ``claude_code``
    preset wraps the system prompt and the harness policy defaults apply —
    think as hard as the API allows, bypass per-call permission prompts
    (enforcement is the hook layer the options carry). Without it the
    prompt is used raw and SDK defaults stand: the shape of a nested LLM
    call.

    Shared by :func:`create_claude` and
    :func:`~lup.adapters.clients.claude_compat.create_claude_compat`, which
    reads ``base_url`` onto the native env afterward.
    """
    system_prompt: str | claude_types.SystemPromptPreset | None
    max_thinking = opts.max_thinking_tokens
    permission_mode = opts.permission_mode
    if opts.harness_preset:
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

    mcp_servers: dict[str, claude_types.McpSdkServerConfig | RawMcpServerConfig] = {}
    for name, server in opts.tool_servers.items():
        match server:
            case LupMcpServerConfig():
                mcp_servers[name] = claude_types.McpSdkServerConfig(
                    type="sdk", name=server.name, instance=server.server
                )
            case _:
                mcp_servers[name] = server
    subagents = {spec.name: spec_to_claude(spec) for spec in opts.subagents}

    # Claude's SDK effort levels are low/medium/high/max; the neutral
    # ``xhigh`` maps onto ``max``, and an unknown value is dropped.
    effort: claude_types.EffortLevel | None = None
    match opts.reasoning_effort:
        case "low" | "medium" | "high" | "max" as level:
            effort = level
        case "xhigh":
            effort = "max"

    return claude.ClaudeAgentOptions(
        model=opts.model,
        system_prompt=system_prompt,
        tools=opts.tools,
        max_thinking_tokens=max_thinking,
        permission_mode=permission_mode,
        extra_args=extra_args,
        hooks=lup_hooks_to_claude(opts.hooks) if opts.hooks.by_event() else None,
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
        effort=effort,
        output_format=(
            {"type": "json_schema", "schema": opts.output_schema}
            if opts.output_schema
            else None
        ),
    )


def create_claude(options: LupAgentOptions) -> Client:
    """Build a Claude Agent SDK client from neutral options.

    Consumes the in-process mechanism payloads (hooks, tool servers,
    native subagent definitions) and ignores the subprocess ones (served
    tool groups, writable roots). The one intent knob the SDK has no lever
    for is ``turn_timeout_seconds`` — the SDK exposes no client-side
    per-turn wall-clock cap (checked against claude-agent-sdk's
    ``ClaudeAgentOptions``: ``max_turns`` and ``max_budget_usd`` exist,
    nothing bounds a single turn's duration), so it is left unread and
    refused.
    """
    return ClaudeClient(refuse_unconsumed("claude", options, build_claude_options))


type ClaudeHooksConfig = dict[claude_types.HookEvent, list[claude_types.HookMatcher]]


def claude_hook_tool_path(tool_name: str, tool_input: JsonObject) -> str:
    """Resolve the directory a path-bearing Claude tool acts on.

    Write/Edit/Read carry ``file_path``; Grep carries ``path``; Glob carries
    ``path`` or, failing that, the directory prefix of its ``pattern``. Every
    other tool resolves to ``""``. This is the single place a native tool
    payload becomes the normalized ``LupHookInput.tool_path`` the backend-neutral
    hook factories read.
    """
    match tool_name:
        case "Write" | "Edit" | "Read":
            return str(tool_input.get("file_path", ""))
        case "Grep":
            return str(tool_input.get("path", ""))
        case "Glob":
            path = str(tool_input.get("path", ""))
            return path or extract_glob_dir(str(tool_input.get("pattern", "")))
        case _:
            return ""


def build_claude_hook_handler(
    lup_matcher: LupHookMatcher,
    *,
    event: LupHookEvent,
) -> Callable[
    [claude.HookInput, str | None, claude_types.HookContext],
    Awaitable[claude_types.SyncHookJSONOutput],
]:
    """Build a Claude SDK hook handler from a LupHookMatcher.

    ``event`` is the hook event this handler is registered under — it seeds
    the normalized :class:`LupHookInput` and drives the output conversion
    (permission decisions exist only on PreToolUse).
    """
    hook_fn = lup_matcher.hook

    async def claude_hook(
        input_data: claude.HookInput,
        _tool_use_id: str | None,
        _context: claude_types.HookContext,
    ) -> claude_types.SyncHookJSONOutput:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_result = ""
        if "tool_response" in input_data:
            response = input_data["tool_response"]
            tool_result = (
                response
                if isinstance(response, str)
                else json.dumps(response, default=str)
            )
        stop_hook_active = (
            input_data["stop_hook_active"]
            if "stop_hook_active" in input_data
            else False
        )
        lup_input = LupHookInput(
            event=event,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_path=claude_hook_tool_path(tool_name, tool_input),
            tool_result=tool_result,
            stop_hook_active=stop_hook_active,
        )
        lup_output = await hook_fn(lup_input)
        return lup_hook_output_to_claude(lup_output, event=event)

    return claude_hook


def lup_hooks_to_claude(hooks: LupHooksConfig) -> ClaudeHooksConfig:
    """Convert SDK-agnostic LupHooksConfig to Claude SDK hook format."""
    result: ClaudeHooksConfig = {}

    for event_name, matchers in hooks.by_event():
        claude_matchers: list[claude_types.HookMatcher] = []
        for lup_matcher in matchers:
            handler = build_claude_hook_handler(lup_matcher, event=event_name)
            if lup_matcher.matcher:
                claude_matchers.append(
                    claude_types.HookMatcher(
                        matcher=lup_matcher.matcher, hooks=[handler]
                    )
                )
            else:
                claude_matchers.append(claude_types.HookMatcher(hooks=[handler]))

        result[event_name] = claude_matchers

    return result


def lup_hook_output_to_claude(
    output: LupHookOutput,
    *,
    event: LupHookEvent = "PreToolUse",
) -> claude_types.SyncHookJSONOutput:
    """Convert a LupHookOutput to Claude SDK SyncHookJSONOutput.

    Permission decisions (``allow``/``deny``) exist only on PreToolUse;
    on every other event a denial converts to the generic ``block``
    decision, and an allow is a no-op output.
    """
    decision = output.decision
    reason = output.reason
    system_message = output.system_message

    match event, decision:
        case ("PreToolUse", "allow"):
            return claude_types.SyncHookJSONOutput(
                hookSpecificOutput=claude_types.PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="allow",
                )
            )
        case ("PreToolUse", "deny"):
            return claude_types.SyncHookJSONOutput(
                hookSpecificOutput=claude_types.PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="deny",
                    permissionDecisionReason=reason,
                )
            )
        case (_, "deny" | "block"):
            return claude_types.SyncHookJSONOutput(decision="block", reason=reason)
        case _:
            if system_message:
                return claude_types.SyncHookJSONOutput(systemMessage=system_message)
            return claude_types.SyncHookJSONOutput()


def spec_to_claude(spec: SubagentSpec) -> claude_types.AgentDefinition:
    """Convert a SubagentSpec to a Claude AgentDefinition.

    ``AgentDefinition.model`` is ``str | None`` and accepts both the
    short aliases (``sonnet``/``opus``/``haiku``) and full model IDs
    (``claude-opus-4-6``), so the spec's model passes straight through
    rather than collapsing unknown IDs to the inherited main-loop model.
    A spec without a model (``None``) inherits the main-loop model —
    the same semantics ``run_subagent`` gives it on other backends.
    """
    return claude_types.AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,
        tools=spec.tools,
        model=spec.model,
    )


def claude_block_to_lup(block: claude.ContentBlock) -> LupContentBlock:
    """Convert a Claude SDK ContentBlock to a LupContentBlock."""
    if hasattr(block, "type") and getattr(block, "type", None) == "redacted_thinking":
        return LupThinkingBlock(thinking="", redacted=True)

    match block:
        case claude.ThinkingBlock():
            is_redacted = not block.thinking and bool(block.signature)
            return LupThinkingBlock(thinking=block.thinking or "", redacted=is_redacted)
        case claude.TextBlock():
            return LupTextBlock(text=block.text)
        case claude.ToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case claude.ToolResultBlock():
            return LupToolResultBlock(
                tool_use_id=block.tool_use_id, content=block.content
            )
        case claude_types.ServerToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case claude_types.ServerToolResultBlock():
            content = (
                block.content if isinstance(block.content, str) else str(block.content)
            )
            return LupToolResultBlock(tool_use_id=block.tool_use_id, content=content)
        case _:
            return LupTextBlock(text=str(block))


def claude_message_to_lup(message: claude.Message) -> LupMessage | None:
    """Convert a Claude SDK Message to a LupMessage.

    Returns None for message types that have no lup equivalent
    (e.g. stream events).
    """
    match message:
        case claude_types.AssistantMessage():
            blocks = [claude_block_to_lup(b) for b in message.content]
            return LupAssistantMessage(content=blocks)
        case claude_types.UserMessage():
            if isinstance(message.content, list):
                blocks = [claude_block_to_lup(b) for b in message.content]
                return LupUserMessage(content=blocks)
            return LupUserMessage(content=message.content)
        case claude_types.SystemMessage():
            data = (
                json.dumps(message.data)
                if isinstance(message.data, dict)
                else str(message.data)
            )
            return LupSystemMessage(subtype=message.subtype, data=data)
        case claude_types.ResultMessage():
            return None
        case _:
            return None


type SdkDict = dict[str, Any]  # lup: ignore — the SDK's tool-handler payload type


def lup_tools_to_sdk(
    tools: list[LupMcpTool],
) -> list[claude.SdkMcpTool[JsonObject]]:
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
        claude.SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=as_sdk(t.handler),
        )
        for t in tools
    ]


type ClaudeUsageNormalizer = Callable[[Mapping[str, JsonValue]], Usage | None]
"""Transforms the raw Claude SDK usage payload into a (subclass of) Usage."""


class ResponseCollector: #lup: Feels like this should be an ABC implementation instead
    #lup: Allso feels like we're deduplicating work from trace.py
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
        client: claude.ClaudeSDKClient,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> None:
        self.client = client
        self.blocks: list[claude.ContentBlock] = []
        self.tool_results: list[claude.ContentBlock] = []
        self.messages: list[
            claude_types.AssistantMessage | claude_types.UserMessage
        ] = []
        self.result: claude_types.ResultMessage | None = None
        self.trace_logger = trace_logger
        self.prefix = prefix

    @property
    def text(self) -> str | None:
        """Concatenated text from all assistant text blocks, or ``None``."""
        texts = [b.text for b in self.blocks if isinstance(b, claude.TextBlock)]
        return "\n\n".join(texts) if texts else None

    def output[T: BaseModel](self, output_type: type[T]) -> T | None:
        """Extract structured output as a validated Pydantic model, or ``None``."""
        if self.result is not None and self.result.structured_output:
            return output_type.model_validate(self.result.structured_output)
        return None

    async def __aiter__(self) -> AsyncIterator[claude.Message]:
        """Yield messages, accumulating state but not displaying.

        Raises RuntimeError on agent error results — after logging,
        tracing, and yielding the failing ResultMessage, so consumers
        see it and the trace records what went wrong.
        """
        async for message in self.client.receive_response():
            match message:
                case claude_types.AssistantMessage():
                    self.messages.append(message)
                    for block in message.content:
                        self.blocks.append(block)

                case claude_types.ResultMessage():
                    self.result = message
                    if message.is_error:
                        logger.error("Agent error result: %s", message.result)
                        if self.trace_logger:
                            self.trace_logger.log_text(
                                str(message.result), heading="Agent error result"
                            )

                case claude_types.SystemMessage():
                    logger.info("System [%s]: %s", message.subtype, message.data)

                case claude_types.UserMessage():
                    self.messages.append(message)
                    if isinstance(message.content, list):
                        for block in message.content:
                            self.tool_results.append(block)

            yield message

            if isinstance(message, claude_types.ResultMessage) and message.is_error:
                raise RuntimeError(f"Agent error: {message.result}")

    async def collect(self) -> claude_types.ResultMessage:
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
                case claude_types.AssistantMessage():
                    blocks = [claude_block_to_lup(b) for b in message.content]
                    response.messages.append(LupAssistantMessage(content=blocks))
                    response.blocks.extend(blocks)
                case claude_types.UserMessage() if isinstance(message.content, list):
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
    client: claude.ClaudeSDKClient,
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
        client: claude.ClaudeSDKClient,
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
        options: Native SDK options built by :func:`build_claude_options`.
        usage_normalizer: Transforms the raw SDK usage payload into a
            ``Usage`` (or subclass, for vendor-specific fields).
    """

    def __init__(
        self,
        options: claude.ClaudeAgentOptions,
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
        async with claude.ClaudeSDKClient(options=options) as client:
            yield ClaudeSession(
                client, usage_normalizer=self.usage_normalizer, resumed=resume
            )

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        return await query_via_session(
            self, prompt, trace_logger=trace_logger, prefix=prefix
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
        async with claude.ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                lup_msg = claude_message_to_lup(message)
                if lup_msg is not None and trace_logger:
                    print_message(lup_msg, prefix=prefix, trace=trace_logger)

                match message:
                    case claude_types.AssistantMessage():
                        for block in message.content:
                            collected.append(claude_block_to_lup(block))
                            match block:
                                case claude.ThinkingBlock():
                                    if block.thinking:
                                        yield LupThinkingEvent(thinking=block.thinking)
                                case claude.TextBlock():
                                    yield LupTextEvent(text=block.text)
                                case claude.ToolUseBlock():
                                    yield LupToolUseEvent(id=block.id, name=block.name)
                    case claude_types.UserMessage():
                        if isinstance(message.content, list):
                            for block in message.content:
                                if isinstance(block, claude.ToolResultBlock):
                                    yield LupToolResultEvent(
                                        tool_use_id=block.tool_use_id,
                                        content=str(block.content),
                                    )
                    case claude_types.ResultMessage():
                        yield LupDoneEvent(blocks=collected)
                        if message.is_error:
                            raise RuntimeError(f"Agent error: {message.result}")
