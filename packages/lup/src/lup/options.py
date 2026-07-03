"""Backend-agnostic options — the one shape that crosses into the engines.

A caller assembles a :class:`LupAgentOptions` (its domain work: which
tools, which hooks, which subagents, the model knobs) and hands it to
``lup.adapters.common.create_client``; the engine translates it into its
native option object. No consumer names a backend or touches a native
option type. Each engine consumes the mechanism payloads that belong to
it and ignores the others'; intent knobs it cannot honor follow the
``on_unsupported`` policy.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lup.mcp import McpServerEntry
from lup.types import (
    JsonObject,
    LupHooksConfig,
    PermissionMode,
    SubagentSpec,
    UsageCost,
)


class CompatOptions(BaseModel):
    """An OpenAI-compatible endpoint, engine-neutral.

    Consumed by whichever engine fronts the endpoint: ``openai-compat``
    defines a Codex custom provider from it, ``claude-compat`` points the
    Claude scaffolding at it via ``ANTHROPIC_BASE_URL``. Unset for models
    served by their own vendor.
    """

    base_url: str | None = None
    api_key: str | None = None
    model_provider: str | None = None


class CodexOptions(BaseModel):
    """Codex-runtime construction inputs that have no Claude analogue.

    The Codex app-server is a subprocess: it cannot take in-process tools, so
    tools are served externally (``LupAgentOptions.served_tool_groups`` names
    the groups, and ``mcp_env`` relays the session context the subprocess
    needs), and writes are confined natively to ``writable_roots`` instead of by
    a permission hook. ``session_id``/``shared_dir`` drive the parent-side
    container cleanup. A Claude session leaves this at its defaults.
    """

    model_config = {"arbitrary_types_allowed": True}

    sandbox: str | None = None
    approval_policy: str | None = None
    mcp_env: dict[str, str] = Field(default_factory=dict)
    writable_roots: list[Path] = Field(default_factory=list)

    session_id: str | None = None
    shared_dir: Path | None = None
    realtime_dir: Path | None = None


class LupAgentOptions(BaseModel):
    """Everything an engine needs to construct a client, in neutral terms.

    Each engine maps these onto its native option object. Mechanism
    payloads (hooks and tool servers; served groups and the ``codex``
    block) are consumed by the engine they belong to and ignored by the
    others. Intent knobs an engine cannot honor (thinking tokens on the
    Codex runtime, turn timeouts on Claude) follow ``on_unsupported``:
    refused at construction, or cleared with a log line.
    """

    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str = ""
    harness_prompt: bool = True
    """Wrap the system prompt in the engine's coding-harness preset
    (Claude's ``claude_code`` preset + append). ``False`` uses it raw —
    the shape of a nested LLM call rather than an agent session."""

    tool_servers: dict[str, McpServerEntry] = Field(default_factory=dict)
    subagents: list[SubagentSpec] = Field(default_factory=list)
    hooks: LupHooksConfig = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    """Base builtin toolset restriction (``None`` = the engine's default set)."""
    served_tool_groups: tuple[str, ...] = ()
    add_dirs: list[Path] = Field(default_factory=list)
    output_schema: JsonObject | None = None
    """JSON Schema the final response must satisfy (structured output)."""

    permission_mode: PermissionMode | None = None
    max_turns: int | None = None
    max_thinking_tokens: int | None = None
    reasoning_effort: str | None = None
    max_budget_usd: float | None = None
    turn_timeout_seconds: float | None = None
    usage_cost: UsageCost | None = None

    persist_session: bool = True
    sdk_sandbox: bool = True
    """Enable the engine's own OS sandbox where it has one (Claude SDK)."""
    realtime: bool = False
    on_unsupported: Literal["raise", "drop"] = "raise"
    """What an engine does with intent knobs it cannot honor: refuse the
    construction (sessions fail fast) or clear them with a log line (the
    one-shot ``query()`` degrades)."""

    codex: CodexOptions = Field(default_factory=CodexOptions)
    compat: CompatOptions = Field(default_factory=CompatOptions)
