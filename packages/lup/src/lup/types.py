"""Internal content block, message, and response types.

These types are the shared vocabulary for all consumer code — the
application's orchestration, the trace logger, the tools. SDK-specific
adapters convert to/from these types at the boundary — consumer code
never imports from SDK packages directly. The hook vocabulary lives in
:mod:`lup.hooks`, not here.
"""

from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


# ---------------------------------------------------------------------------
# JSON vocabulary
# ---------------------------------------------------------------------------

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
"""One JSON-decodable value — the shape ``json.loads`` yields.

The shared vocabulary for data whose schema is defined elsewhere (tool
arguments, JSON Schemas, vendor payloads): unlike ``object`` it stays
introspectable, and unlike ``Any`` it keeps the type checker honest.
"""

type JsonObject = dict[str, JsonValue]
"""A JSON object: tool inputs, JSON Schemas, structured outputs, session data."""

type EnvVars = dict[str, str]  # lup: ignore[dict-str-payload] — open env-var map
"""An environment-variable map — process env, dotenv values, MCP server env.

The keys are open and data-driven by nature (whatever variables exist), which
is exactly the shape the dict-str-payload rule otherwise flags: annotate env
maps with this alias instead of respelling ``dict[str, str]`` per site."""

type Decorator[T, R] = Callable[[T], R]
"""A decorator: applied with ``@`` to a `T`, yields an `R`. Names the intent
at a signature (``-> Decorator[Handler, Tool]``) where a bare ``Callable`` of
a callable reads as noise. ``R`` need not be ``T`` — a decorator may return a
different type than it wraps (a builder, a registration object)."""


# ---------------------------------------------------------------------------
# Tool vocabulary
# ---------------------------------------------------------------------------

type KnownToolName = Literal[
    "Agent",
    "AskUserQuestion",
    "Bash",
    "BashOutput",
    "Edit",
    "EnterWorktree",
    "ExitPlanMode",
    "ExitWorktree",
    "Glob",
    "Grep",
    "KillShell",
    "ListMcpResources",
    "MultiEdit",
    "NotebookEdit",
    "Read",
    "ReadMcpResource",
    "Skill",
    "SlashCommand",
    "StructuredOutput",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write",
]
"""The well-known built-in tool names — the framework's lingua franca.

Claude Code's tool vocabulary is adopted as the neutral spelling: adapters
translate their backend's native tool identities onto these names, so hooks,
policies, and harness declarations all read one vocabulary."""

type McpToolName = Annotated[
    str, StringConstraints(pattern=r"^mcp__[A-Za-z0-9_-]+(?:__[A-Za-z0-9_-]+)*$")
]
"""A dynamically registered MCP tool: ``mcp__<server>`` or ``mcp__<server>__<tool>``."""

type ToolName = KnownToolName | McpToolName
"""One tool identity: a well-known built-in or a registered ``mcp__*`` tool."""

type ScopedToolGrant = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*\([^()]+\)$")
]
"""A tool grant narrowed by a parenthesized specifier, e.g. ``Bash(git:*)``."""

type ToolGrant = ToolName | ScopedToolGrant
"""One entry of a declared tool grant list: a whole tool or a scoped rule."""


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


class LupTextBlock(BaseModel):
    """Text content from the assistant."""

    type: Literal["text"] = "text"
    text: str


class LupThinkingBlock(BaseModel):
    """Extended thinking / reasoning content."""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    redacted: bool = False


class LupToolUseBlock(BaseModel):
    """A tool invocation by the agent."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: JsonObject | None = None


class LupToolResultBlock(BaseModel):
    """Result returned from a tool invocation."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | Sequence[object] | None = None


type LupContentBlock = (
    LupTextBlock | LupThinkingBlock | LupToolUseBlock | LupToolResultBlock
)


# ---------------------------------------------------------------------------
# Subagent specification
# ---------------------------------------------------------------------------


class SubagentSpec(BaseModel):
    """Provider-neutral subagent definition used by injected factory recipes."""

    name: str
    description: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    model: str | None = Field(
        default=None,
        description="Model for this subagent; None inherits the session's "
        "main model on every backend",
    )
    max_turns: int | None = Field(
        default=None,
        description="Turn cap for delegated one-shot runs (None = backend default)",
    )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class LupAssistantMessage(BaseModel):
    """Message from the assistant containing content blocks."""

    role: Literal["assistant"] = "assistant"
    content: list[LupContentBlock]


class LupUserMessage(BaseModel):
    """Message from the user or tool results."""

    role: Literal["user"] = "user"
    content: list[LupContentBlock] | str


class LupSystemMessage(BaseModel):
    """System-level message (status updates, etc.)."""

    role: Literal["system"] = "system"
    subtype: str
    data: str


class Usage(BaseModel):
    """Portable token usage — the counts every backend can provide.

    Adapters produce this through a ``usage_normalizer`` callback supplied
    at construction, defaulting to each adapter's standard converter. A
    custom normalizer may return a *subclass* carrying vendor-specific
    fields (service tier, per-iteration costs, …); fields holding it are
    declared ``SerializeAsAny[Usage]`` so subclass data survives into
    session JSON.
    """

    input_tokens: int = Field(
        default=0,
        description=(
            "Complete input token count, cached reads and cache creation"
            " included; adapters normalize cache-exclusive native counts"
        ),
    )
    cost_usd: float | None = Field(
        default=None,
        description="Optional provider-reported complete cost for this usage span",
    )
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


type UsageCost = Callable[[Usage], float]
"""Estimates the USD cost of accumulated token usage.

Adapters that report token counts but no cost take one of these to enforce a
budget; build it with :func:`lup.runtime.usage.per_mtok_usage_cost`.
"""

type LupMessage = LupAssistantMessage | LupUserMessage | LupSystemMessage
