"""MCP server factory with proper is_error propagation.

Creates in-process MCP servers from ``LupMcpTool`` definitions. The
``create_mcp_server`` function returns an ``LupMcpServerConfig`` that
each SDK adapter converts to its native server configuration.

Tool naming convention:
    After registration, tools are named: mcp__{server_name}__{tool_name}
    Example: mcp__my-server__my_tool

Examples:
    Define a tool with typed input/output using the ``lup_tool`` decorator::

        >>> from pydantic import BaseModel, Field
        >>> class SearchInput(BaseModel):
        ...     query: str = Field(description="Search query")
        >>> class SearchOutput(BaseModel):
        ...     results: list[str]
        >>> @lup_tool("Search the knowledge base.", tags=["search"])
        ... async def search(params: SearchInput) -> SearchOutput:
        ...     return SearchOutput(results=["result1", "result2"])

    Create an MCP server from tools::

        >>> tools = [search, another_tool]
        >>> server = create_mcp_server("my-server", tools=tools)
"""

import asyncio
import inspect
import json
import logging
import signal
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, NotRequired, TypedDict, cast, get_type_hints

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent, Tool
from pydantic import BaseModel, ValidationError

from lup.types import JsonObject

logger = logging.getLogger(__name__)


class ToolResponse(TypedDict, total=False):
    """Shape of the dict returned by MCP tool handlers."""

    content: list[dict[str, str]]
    is_error: bool


def mcp_response(text: str, *, is_error: bool = False) -> ToolResponse:
    """Create an MCP response with text content."""
    response = ToolResponse(content=[{"type": "text", "text": text}])
    if is_error:
        response["is_error"] = True
    return response


class CallToolResultWithAlias(CallToolResult):
    """CallToolResult with snake_case alias for SDK compatibility.

    Some SDK query runners check ``is_error`` (snake_case) but MCP's
    CallToolResult uses ``isError`` (camelCase). This subclass adds a
    property alias so both work.
    """

    @property
    def is_error(self) -> bool:
        """Snake_case alias for isError."""
        return self.isError


# MCP hands an arbitrary JSON args object validated by the per-tool BaseModel.
type LupToolHandler = Callable[[JsonObject], Awaitable[ToolResponse]]


class LupMcpServerConfig(BaseModel):
    """SDK-agnostic MCP server configuration.

    Wraps an ``mcp.server.Server`` instance. Each adapter converts
    this to its native server config at build time.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str
    server: Server
    tool_names: list[str] = []


class RawStdioServerConfig(TypedDict):
    """An external MCP server launched as a stdio subprocess."""

    type: NotRequired[Literal["stdio"]]
    command: str
    args: NotRequired[list[str]]
    env: NotRequired[dict[str, str]]


class RawSseServerConfig(TypedDict):
    """An external MCP server reached over Server-Sent Events."""

    type: Literal["sse"]
    url: str
    headers: NotRequired[dict[str, str]]


class RawHttpServerConfig(TypedDict):
    """An external MCP server reached over streamable HTTP."""

    type: Literal["http"]
    url: str
    headers: NotRequired[dict[str, str]]


type RawMcpServerConfig = (
    RawStdioServerConfig | RawSseServerConfig | RawHttpServerConfig
)
"""An MCP server the framework does not host: a transport config, no instance."""

type McpServerEntry = LupMcpServerConfig | RawMcpServerConfig
"""One MCP server in a session: an in-process ``LupMcpServerConfig`` carrying a
live ``Server`` instance, or a transport config for an external one. An adapter
narrows by ``isinstance(entry, LupMcpServerConfig)`` — the in-process case has a
``.server`` to register, the external case is passed to the SDK as-is."""


def create_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: Sequence["LupMcpTool"] | None = None,
) -> LupMcpServerConfig:
    """Create an in-process MCP server with proper is_error handling.

    Args:
        name: Unique identifier for the server.
        version: Server version string.
        tools: List of LupMcpTool instances created with the @lup_tool decorator.

    Returns:
        LupMcpServerConfig for adapter conversion.

    A server built without tools still registers its handlers and
    advertises an empty tool list — selecting an unpopulated group is a
    valid (if useless) session, not a protocol error.
    """
    server = Server(name, version=version)
    registered = list(tools or [])
    tool_map = {tool_def.name: tool_def for tool_def in registered}

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available tools."""
        tool_list: list[Tool] = []
        for tool_def in registered:
            tool_list.append(
                Tool(
                    name=tool_def.name,
                    description=tool_def.description,
                    inputSchema=tool_def.input_schema,
                )
            )
        return tool_list

    @server.call_tool()
    async def call_tool(name: str, arguments: JsonObject) -> CallToolResult:
        """Execute a tool by name with given arguments."""
        if name not in tool_map:
            raise ValueError(f"Tool '{name}' not found")

        tool_def = tool_map[name]
        result = await tool_def.handler(arguments)

        is_error = result.get("is_error", False)

        content: list[TextContent | ImageContent] = []
        if "content" in result:
            for item in result["content"]:
                match item.get("type"):
                    case "text":
                        content.append(TextContent(type="text", text=item["text"]))
                    case "image":
                        content.append(
                            ImageContent(
                                type="image",
                                data=item["data"],
                                mimeType=item["mimeType"],
                            )
                        )

        return CallToolResultWithAlias(
            content=cast(list[ContentBlock], content), isError=is_error
        )

    return LupMcpServerConfig(
        name=name,
        server=server,
        tool_names=[t.name for t in registered],
    )


def server_tool_names(server: object) -> list[str]:
    """List the tool names registered on an in-process MCP server.

    Servers built with :func:`create_mcp_server` carry their tool list on
    the config. Use this to compute the full ``mcp__{server}__{tool}``
    names the agent will see — e.g. when building a tool allowlist or an
    inspection display — without maintaining a second tool list that can
    drift. External server configs (stdio, SSE, HTTP) cannot be
    introspected without connecting, so they yield an empty list.
    """
    match server:
        case LupMcpServerConfig():
            return list(server.tool_names)
        case _:
            return []


def serve_stdio(config: LupMcpServerConfig) -> None:
    """Serve an in-process MCP server over stdio (blocking).

    The subprocess half of tool serving: backends that cannot host
    in-process servers launch a tool-server subprocess (``lup-devtools
    agent serve-tools``), which builds the same
    :func:`create_mcp_server` config the in-process path registers and
    exposes it here over a stdio transport — one server construction for
    every backend. SIGTERM raises ``SystemExit`` so ``atexit`` cleanup
    (sandbox teardown, metrics flush) runs when the parent stops the
    subprocess.
    """

    def terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)

    async def run() -> None:
        init_options = config.server.create_initialization_options()
        async with stdio_server() as (read_stream, write_stream):
            await config.server.run(read_stream, write_stream, init_options)

    asyncio.run(run())


class ToolError(Exception):
    """Raise in a tool handler to return an MCP error response."""


class LupMcpTool[I: BaseModel, O: BaseModel]: #lup: Why is this not a BaseModel?
    """MCP tool with typed input/output models for introspection.

    Stores the tool definition (name, description, schema, handler) directly.
    Devtools can inspect ``input_model`` / ``output_model`` for full JSON Schemas.
    Also callable directly with a typed model instance, bypassing MCP
    serialization.
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: JsonObject,
        handler: LupToolHandler,
        call_handler: Callable[[I], Awaitable[O]],
        input_model: type[I],
        output_model: type[O] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler
        self.call_handler = call_handler
        self.input_model = input_model
        self.output_model = output_model
        self.tags = tags or []

    async def __call__(self, params: I) -> O:
        return await self.call_handler(params)


def lup_tool[I: BaseModel, O: BaseModel](
    description: str,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | None = None,
    *,
    name: str | None = None,
    tags: list[str] | None = None,
) -> Callable[
    [Callable[[I], Awaitable[O]]],
    LupMcpTool[I, O],
]: #lup: Type is hard to read, surely there's a type to indicate "This is a decorator"? If not, we should create it
    """Decorator for defining MCP tools with typed input/output models.

    Infers input/output schemas from type annotations, auto-validates input,
    auto-serializes BaseModel output, and tracks call metrics.

    The handler receives a validated model instance, not a raw dict.
    The handler must return a BaseModel, which is auto-serialized via
    ``mcp_response(json.dumps(result.model_dump(), default=str))``.

    Raise ``ToolError`` in the handler to return an MCP error response.

    Args:
        description: What/when/why — the agent's only documentation for this tool.
        input_model: Pydantic BaseModel for the tool's input.
              Inferred from the handler's first parameter type if omitted.
        output_model: Pydantic BaseModel for the tool's output.
              Inferred from the handler's return type if omitted.
        name: Unique tool identifier (becomes ``mcp__{server}__{name}``).
              Defaults to the handler's function name.
        tags: Optional classification tags for tool policy filtering.

    Returns:
        A decorator that wraps the async handler into a ``LupMcpTool``.
    """
    from lup.metrics import collector

    def decorator(
        handler: Callable[[I], Awaitable[O]],
    ) -> LupMcpTool[I, O]:
        tool_name = name or handler.__name__

        resolved_input = input_model
        resolved_output = output_model

        if resolved_input is None or resolved_output is None:
            hints = get_type_hints(handler)
            if resolved_input is None:
                params = list(inspect.signature(handler).parameters.values())
                if not params:
                    msg = f"lup_tool '{tool_name}': handler has no parameters to infer input_model from"
                    raise TypeError(msg)
                param_type = hints.get(params[0].name)
                if isinstance(param_type, type) and issubclass(param_type, BaseModel):
                    resolved_input = param_type
            if resolved_output is None:
                return_type = hints.get("return")
                if isinstance(return_type, type) and issubclass(return_type, BaseModel):
                    resolved_output = return_type

        if resolved_input is None:
            msg = f"lup_tool '{tool_name}': cannot infer input_model from annotations"
            raise TypeError(msg)

        final_input = cast(type[I], resolved_input)

        async def wrapper(args: JsonObject) -> ToolResponse:
            start = time.perf_counter()
            is_error = False
            try:
                try:
                    params = final_input.model_validate(args)
                except ValidationError as e:
                    is_error = True
                    return mcp_response(f"Invalid input: {e}", is_error=True)
                try:
                    result = await handler(params)
                except ToolError as e:
                    is_error = True
                    return mcp_response(str(e), is_error=True)
                if not isinstance(result, BaseModel):
                    raise TypeError(
                        f"lup_tool '{tool_name}': handler must return a BaseModel, "
                        f"got {type(result).__name__}"
                    )
                if resolved_output is not None and not isinstance(
                    result, resolved_output
                ):
                    raise TypeError(
                        f"lup_tool '{tool_name}': expected {resolved_output.__name__}, "
                        f"got {type(result).__name__}"
                    )
                return mcp_response(json.dumps(result.model_dump(), default=str))
            except Exception:
                is_error = True
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                collector.record(tool_name, duration_ms, is_error)

        return LupMcpTool(
            name=tool_name,
            description=description,
            input_schema=final_input.model_json_schema(),
            handler=wrapper,
            call_handler=handler,
            input_model=final_input,
            output_model=cast(type[O] | None, resolved_output),
            tags=tags,
        )

    return decorator
