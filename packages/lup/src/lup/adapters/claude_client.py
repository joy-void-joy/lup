# claude: This really screams "we're implementing an ABC", but there's no ABC to be seen. This seems dangerous.
# claude: query and collector should be interfaces already specified, that it just satisfies one way or another

"""Centralized Agent SDK client creation and response collection.

All Agent SDK client construction goes through this module to ensure
consistent defaults (session persistence disabled for nested agent calls).

Exports:
- ResponseCollector — response accumulator with .text and .output(T) accessors
- build_client() — AsyncContextManager[ClaudeSDKClient] with defaults
- query(prompt, ...) — build + query + collect; returns ResponseCollector or T

Examples:
    One-shot query (text result)::

        >>> collector = await query("Summarize this text", model="opus")
        >>> collector.text
        'Here is the summary...'

    Structured output via ``output_type`` (returns the model directly)::

        >>> from pydantic import BaseModel
        >>> class Summary(BaseModel):
        ...     title: str
        ...     points: list[str]
        >>> result = await query("Summarize X", output_type=Summary)
        >>> result.title
        'Summary of X'

    Nested agent with tools::

        >>> collector = await query(
        ...     "Review this code",
        ...     tools=["Read", "Grep"],
        ...     model="opus",
        ...     permission_mode="bypassPermissions",
        ...     max_turns=5,
        ... )
        >>> collector.text
        'The code looks correct...'

    Streaming with ``async for`` for per-message handling::

        >>> async with build_client(tools=["Read"], model="opus") as client:
        ...     await client.query("Analyze main.py")
        ...     collector = ResponseCollector(client)
        ...     async for message in collector:
        ...         print_message(message)  # display as they arrive
        ...     # after iteration, all state is available
        ...     print(len(collector.blocks), "content blocks")
        ...     print(len(collector.tool_results), "tool results")

    Accessing collector state after ``query``::

        >>> collector = await query(
        ...     "List files", tools=["Bash"], max_turns=3,
        ... )
        >>> collector.text                  # concatenated assistant text
        >>> collector.blocks                # all ContentBlock objects
        >>> collector.tool_results          # tool result blocks from UserMessages
        >>> collector.messages              # full AssistantMessage/UserMessage list
        >>> collector.result                # final ResultMessage (or None)
        >>> collector.result.usage          # token usage from the session
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, overload

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContentBlock,
    Message,
    TextBlock,
)
from claude_agent_sdk.types import (
    AgentDefinition,
    AssistantMessage,
    HookEvent,
    HookMatcher,
    McpServerConfig,
    ResultMessage,
    SystemMessage,
    SystemPromptPreset,
    ToolsPreset,
    UserMessage,
)
from pydantic import BaseModel

from lup.adapters.claude import claude_message_to_lup, collect_lup_response
from lup.adapters.common import PermissionMode
from lup.trace import TraceLogger, print_message
from lup.types import LupResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output format types
# ---------------------------------------------------------------------------

JsonSchema = dict[str, object]  # claude: ignore — JSON Schema is an open document
"""Type alias for JSON Schema payloads (from ``BaseModel.model_json_schema()``)."""

OutputFormat = dict[str, str | JsonSchema]
"""SDK output format dict (e.g. ``{"type": "json_schema", "schema": ...}``)."""


# ---------------------------------------------------------------------------
# Response collector
# ---------------------------------------------------------------------------


class ResponseCollector:
    """Collects, displays, and logs agent response messages.

    Supports two usage patterns:

    **async for** — iterate messages yourself, no automatic display::

        collector = ResponseCollector(client, trace_logger=trace_logger)
        async for message in collector:
            print_message(message)

    **collect()** — drain all messages with automatic display and tracing::

        collector = ResponseCollector(client, trace_logger=trace_logger)
        result = await collector.collect()

    After iteration, access accumulated state:
    ``collector.blocks``, ``collector.tool_results``,
    ``collector.messages``, ``collector.result``.
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
        """Concatenated text from all assistant text blocks.

        Returns ``None`` when no text blocks were produced.  Access
        after ``collect()`` (called automatically by ``query()``).
        """
        texts = [b.text for b in self.blocks if isinstance(b, TextBlock)]
        return "\n\n".join(texts) if texts else None

    def output[T: BaseModel](self, output_type: type[T]) -> T | None:
        """Extract structured output as a validated Pydantic model.

        Returns ``None`` when the agent produced no structured output.
        """
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


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


@asynccontextmanager
async def build_client(
    *,
    options: ClaudeAgentOptions | None = None,
    model: str | None = None,
    system_prompt: str | SystemPromptPreset | None = None,
    tools: list[str] | ToolsPreset | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"]
    | None = None,
    mcp_servers: dict[str, McpServerConfig] | str | Path | None = None,
    agents: dict[str, AgentDefinition] | None = None,
    max_thinking_tokens: int | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    output_format: OutputFormat | None = None,
    extra_args: dict[str, str | None] | None = None,
    hooks: dict[HookEvent, list[HookMatcher]] | None = None,
) -> AsyncIterator[ClaudeSDKClient]:
    """Return a configured ClaudeSDKClient with project-wide defaults.

    Pass ``options`` (pre-built) to use as-is, or keyword arguments to
    construct ClaudeAgentOptions.  When using keyword arguments, always
    injects ``no-session-persistence`` into extra_args (caller wins on
    conflict).

    Combining a pre-built ``options`` with other keyword arguments
    raises ValueError — they would otherwise be silently ignored.
    Set them on the options object instead.
    """
    if options is not None:
        ignored = [
            name
            for name, value in (
                ("model", model),
                ("system_prompt", system_prompt),
                ("tools", tools),
                ("allowed_tools", allowed_tools),
                ("permission_mode", permission_mode),
                ("mcp_servers", mcp_servers),
                ("agents", agents),
                ("max_thinking_tokens", max_thinking_tokens),
                ("max_turns", max_turns),
                ("max_budget_usd", max_budget_usd),
                ("output_format", output_format),
                ("extra_args", extra_args),
                ("hooks", hooks),
            )
            if value is not None
        ]
        if ignored:
            raise ValueError(
                "build_client: a pre-built options object was given together "
                f"with keyword arguments {ignored}, which would be silently "
                "ignored — set them on the options object instead."
            )
    else:
        merged_extra: dict[str, str | None] = {
            "no-session-persistence": None,
            **(extra_args or {}),
        }
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            allowed_tools=allowed_tools if allowed_tools is not None else [],
            permission_mode=permission_mode,
            mcp_servers=mcp_servers if mcp_servers is not None else {},
            agents=agents,
            max_thinking_tokens=max_thinking_tokens,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            output_format=output_format,
            extra_args=merged_extra,
            hooks=hooks,
        )

    async with ClaudeSDKClient(options=options) as client:
        yield client


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def prepare_output_format(
    *,
    output_type: type[BaseModel] | None,
    output_format: OutputFormat | None,
    options: ClaudeAgentOptions | None,
) -> OutputFormat | None:
    """Resolve the structured-output format for :func:`query`.

    Computes a ``json_schema`` format from *output_type* when no explicit
    *output_format* is given, and injects the result into a pre-built
    *options* object — ``build_client`` uses pre-built options as-is, so
    a format left in keyword arguments would be silently dropped and the
    structured output would come back ``None``.

    Returns:
        The output format to pass to ``build_client`` as a keyword
        argument, or ``None`` when it was injected into *options*
        (or no structured output was requested).

    Raises:
        ValueError: If *options* already sets ``output_format`` and
            *output_type* or an explicit *output_format* is also given.
    """
    if output_type is not None and output_format is None:
        output_format = {
            "type": "json_schema",
            "schema": output_type.model_json_schema(),
        }
    if options is None or output_format is None:
        return output_format
    if options.output_format is not None:
        raise ValueError(
            "options.output_format is already set — pass either the pre-built "
            "format or output_type/output_format, not both."
        )
    options.output_format = output_format
    return None


@overload
async def query(
    prompt: str,
    *,
    options: ClaudeAgentOptions | None = ...,
    prefix: str = ...,
    trace_logger: TraceLogger | None = ...,
    model: str | None = ...,
    system_prompt: str | SystemPromptPreset | None = ...,
    tools: list[str] | ToolsPreset | None = ...,
    allowed_tools: list[str] | None = ...,
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"]
    | None = ...,
    mcp_servers: dict[str, McpServerConfig] | str | Path | None = ...,
    agents: dict[str, AgentDefinition] | None = ...,
    max_thinking_tokens: int | None = ...,
    max_turns: int | None = ...,
    max_budget_usd: float | None = ...,
    output_format: OutputFormat | None = ...,
    extra_args: dict[str, str | None] | None = ...,
    hooks: dict[HookEvent, list[HookMatcher]] | None = ...,
) -> ResponseCollector: ...


@overload
async def query[T: BaseModel](
    prompt: str,
    *,
    output_type: type[T],
    options: ClaudeAgentOptions | None = ...,
    prefix: str = ...,
    trace_logger: TraceLogger | None = ...,
    model: str | None = ...,
    system_prompt: str | SystemPromptPreset | None = ...,
    tools: list[str] | ToolsPreset | None = ...,
    allowed_tools: list[str] | None = ...,
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"]
    | None = ...,
    mcp_servers: dict[str, McpServerConfig] | str | Path | None = ...,
    agents: dict[str, AgentDefinition] | None = ...,
    max_thinking_tokens: int | None = ...,
    max_turns: int | None = ...,
    max_budget_usd: float | None = ...,
    output_format: OutputFormat | None = ...,
    extra_args: dict[str, str | None] | None = ...,
    hooks: dict[HookEvent, list[HookMatcher]] | None = ...,
) -> T | None: ...


async def query(
    prompt: str,
    *,
    output_type: type[BaseModel] | None = None,
    options: ClaudeAgentOptions | None = None,
    prefix: str = "",
    trace_logger: TraceLogger | None = None,
    model: str | None = None,
    system_prompt: str | SystemPromptPreset | None = None,
    tools: list[str] | ToolsPreset | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"]
    | None = None,
    mcp_servers: dict[str, McpServerConfig] | str | Path | None = None,
    agents: dict[str, AgentDefinition] | None = None,
    max_thinking_tokens: int | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    output_format: OutputFormat | None = None,
    extra_args: dict[str, str | None] | None = None,
    hooks: dict[HookEvent, list[HookMatcher]] | None = None,
) -> ResponseCollector | BaseModel | None:
    """Query an SDK client and collect the full response.

    Without ``output_type``: returns a ``ResponseCollector`` with
    ``.text``, ``.output(T)``, ``.blocks``, ``.messages``, ``.result``.

    With ``output_type``: returns a validated Pydantic model (or ``None``
    if the agent produced no structured output).

    Pass ``options`` (pre-built) to use as-is, or keyword arguments to
    construct ``ClaudeAgentOptions``. ``output_type`` works with both:
    for pre-built options the computed format is injected into them
    (ValueError if they already set ``output_format``).
    """
    output_format = prepare_output_format(
        output_type=output_type, output_format=output_format, options=options
    )

    if options is not None and (output_type is not None or output_format is not None):
        raise ValueError(
            "query() received a pre-built options object together with "
            "output_type/output_format; the structured-output schema cannot "
            "be applied because build_client uses pre-built options as-is. "
            "Set output_format on the options object instead, or omit options."
        )

    async with build_client(
        options=options,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        mcp_servers=mcp_servers,
        agents=agents,
        max_thinking_tokens=max_thinking_tokens,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        output_format=output_format,
        extra_args=extra_args,
        hooks=hooks,
    ) as client:
        await client.query(prompt)
        collector = ResponseCollector(client, prefix=prefix, trace_logger=trace_logger)
        await collector.collect()

    if output_type is not None:
        return collector.output(output_type)
    return collector


async def claude_query(
    prompt: str,
    *,
    model: str = "claude-opus-4-6",
    system_prompt: str | None = None,
    output_schema: dict[str, object] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_budget_usd: float | None = None,
) -> LupResponse:
    """One-shot query via the Claude Agent SDK, returning LupResponse.

    The lup-typed counterpart of :func:`query` — the anthropic backend
    of ``lup.adapters.common.query`` dispatches here.
    """
    async with build_client(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        max_thinking_tokens=max_thinking_tokens,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        output_format=(
            {"type": "json_schema", "schema": output_schema} if output_schema else None
        ),
    ) as client:
        await client.query(prompt)
        return await collect_lup_response(
            client, trace_logger=trace_logger, prefix=prefix
        )
