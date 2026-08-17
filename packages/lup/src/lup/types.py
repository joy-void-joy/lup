"""Internal content block, message, and response types.

These types are the shared vocabulary for all consumer code — the
application's orchestration, the trace logger, the tools. SDK-specific
adapters convert to/from these types at the boundary — consumer code
never imports from SDK packages directly. The hook vocabulary lives in
:mod:`lup.hooks`, not here.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    model_validator,
)


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

type StringMap = dict[str, str]  # lup: ignore[dict-str-payload] — open string map
"""Any other open map of strings to strings — a reason table, response headers.

The same shape as ``EnvVars`` and deliberately a separate name: what makes
these keys open differs, and a header map annotated as environment variables
reads as a mistake even where the checker cannot see one. Reach for it when
the keys are data rather than a schema; a fixed set of fields is a
``TypedDict`` or a model, not this."""

type Namespace = dict[str, object]  # lup: ignore[dict-str-object] — live objects
"""A live Python namespace: names bound to whatever objects they name.

The one shape ``object`` is honest for, because the values genuinely are
arbitrary objects rather than data with a schema somewhere — a module, a
builtin, a class. Reach for ``JsonObject`` for anything that will be
serialized; this is for what an interpreter holds."""

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


def normalize_content(content: str | Sequence[object] | None) -> str:
    """Flatten tool-result content — MCP block list or scalar — to a string."""
    if content is None:
        return "(empty)"
    if isinstance(content, list):
        texts: list[str] = []  # lup: ignore[empty-collection] — block fold
        for item in content:
            match item:
                case {"type": "text", "text": text}:
                    texts.append(str(text))
        return "\n".join(texts)
    return str(content)


class BlockDisplay(BaseModel, frozen=True):
    """What a console, a trace, or a transcript needs to know about a block.

    One shape rather than a question per kind, because these are asked of a
    block whose kind the caller does not know: a walk collecting spoken prose
    reaches every kind that voices any, including kinds written long after it
    was. A kind that carries none of something leaves the default, which is
    what makes omission safe.
    """

    emoji: str = "❓"
    """The glyph a console leads this block with."""

    label: str = "Unknown"
    """The short name a console and a trace heading give this block."""

    markdown_fence: str | None = None
    """The code-fence language a markdown trace wraps the body in, if any."""

    spoken_text: str | None = None
    """Prose the assistant voiced, if this block voices any."""

    opens_pairing: str | None = None
    """The id this block opens, which a later block closes."""

    closes_pairing: str | None = None
    """The id this block closes, opened by an earlier block."""

    tool_call_name: str | None = None
    """The tool this block invokes, if it invokes one."""

    result_payload: str | Sequence[object] | None = None
    """Raw tool output this block carries, for a caller that reformats it."""


class LupContentBlock(ABC):
    """One block of a message, answering every question about itself.

    Three projections and no state: how a surface should show it, its content
    as one readable string, and the one line a stream log gives it. A new kind
    of block is one class rather than an edit to every walk that would have to
    notice it.
    """

    @abstractmethod
    def display(self) -> BlockDisplay:
        """How a surface shows this block, for a caller not knowing its kind."""

    @abstractmethod
    def body(self) -> str:
        """This block's content as one readable string."""

    @abstractmethod
    def log_summary(self, body: str) -> str:
        """One stream-log line for this block, given its rendered `body`."""


class LupTextBlock(LupContentBlock):
    """Text content from the assistant."""

    def __init__(self, text: str) -> None:
        self.text = text

    def display(self) -> BlockDisplay:
        return BlockDisplay(emoji="💬", label="Response", spoken_text=self.text)

    def body(self) -> str:
        return self.text

    def log_summary(self, body: str) -> str:
        return f"RESPONSE: {body}"


class LupThinkingBlock(LupContentBlock):
    """Extended thinking / reasoning content."""

    def __init__(self, thinking: str = "", redacted: bool = False) -> None:
        self.thinking = thinking
        self.redacted = redacted

    def display(self) -> BlockDisplay:
        return BlockDisplay(emoji="💭", label="Thinking")

    def body(self) -> str:
        return "[redacted]" if self.redacted else self.thinking

    def log_summary(self, body: str) -> str:
        return f"THINKING: {body}"


class LupToolUseBlock(LupContentBlock):
    """A tool invocation by the agent."""

    def __init__(self, id: str, name: str, input: JsonObject | None = None) -> None:
        self.id = id
        self.name = name
        self.input = input

    def display(self) -> BlockDisplay:
        return BlockDisplay(
            emoji="🔧",
            label=f"Tool: {self.name}",
            markdown_fence="json",
            opens_pairing=self.id,
            tool_call_name=self.name,
        )

    def body(self) -> str:
        return json.dumps(self.input, indent=2) if self.input else ""

    def log_summary(self, body: str) -> str:
        arguments = json.dumps(self.input) if self.input else ""
        return f"TOOL_USE [{self.id}] {self.name}: {arguments}"


class LupToolResultBlock(LupContentBlock):
    """Result returned from a tool invocation."""

    def __init__(
        self, tool_use_id: str, content: str | Sequence[object] | None = None
    ) -> None:
        self.tool_use_id = tool_use_id
        self.content = content

    def display(self) -> BlockDisplay:
        return BlockDisplay(
            emoji="📋",
            label="Result",
            markdown_fence="",
            closes_pairing=self.tool_use_id,
            result_payload=self.content,
        )

    def body(self) -> str:
        return normalize_content(self.content)

    def log_summary(self, body: str) -> str:
        return f"TOOL_RESULT [{self.tool_use_id}]: {body}"


# ---------------------------------------------------------------------------
# Subagent specification
# ---------------------------------------------------------------------------


class SubagentSpec(BaseModel):
    """Provider-neutral subagent definition used by injected factory recipes."""

    name: str
    description: str
    prompt: str
    tools: list[str] = []
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


class LupMessage(BaseModel, arbitrary_types_allowed=True):
    """One transcript message, answering every question about itself.

    A walk that wants the blocks of a message asks :attr:`content_blocks`
    rather than naming the kinds of message that carry them, so a kind added
    later is reached by every existing walk and a kind that carries none — a
    status line — declines once, here.

    It is a field rather than a member because what a message carries is data:
    a kind that holds blocks fills it as it is built, and one that holds none
    takes the empty default without answering anything.
    """

    content_blocks: list[LupContentBlock] = []
    """The blocks this message carries, empty when it carries none."""


class LupAssistantMessage(LupMessage):
    """Message from the assistant containing content blocks."""

    role: Literal["assistant"] = "assistant"
    content: list[LupContentBlock]

    @model_validator(mode="after")
    def blocks_are_its_content(self) -> "LupAssistantMessage":
        """Carry the content as blocks, so a walk needs no per-kind knowledge."""
        self.content_blocks = list(self.content)
        return self


class LupUserMessage(LupMessage):
    """Message from the user or tool results."""

    role: Literal["user"] = "user"
    content: list[LupContentBlock] | str

    @model_validator(mode="after")
    def blocks_are_its_content(self) -> "LupUserMessage":
        """Prose carries no blocks; a content list carries its own."""
        carried = () if isinstance(self.content, str) else self.content
        self.content_blocks = list(carried)
        return self


class LupSystemMessage(LupMessage):
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
