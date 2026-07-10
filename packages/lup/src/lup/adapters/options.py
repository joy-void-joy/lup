"""The backend-neutral construction vocabulary: :class:`LupAgentOptions`.

A caller assembles one options object — its domain work: which tools,
which hooks, which subagents, the model knobs — and hands it to
:func:`lup.adapters.wiring.create_client`. Engines translate it into
their native option objects; no consumer names a backend or touches a
native option type.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from lup.hooks import LupHooksConfig
from lup.mcp import LupMcpServerConfig, McpServerEntry, server_tool_names
from lup.types import (
    JsonObject,
    PermissionMode,
    SubagentSpec,
    UsageCost,
)


class LupAgentOptions(BaseModel):
    """Everything an engine needs to construct a client, in neutral terms.

    A caller assembles one of these (its domain work: which tools, which
    hooks, which subagents, the model knobs) and hands it to
    :func:`~lup.adapters.wiring.create_client`; the engine's factory translates
    it into its native option object. No consumer names a backend or touches a
    native option type. Each engine consumes the mechanism payloads that belong
    to it (in-process hooks and tool servers on Claude; served groups, env
    relay, and writable roots on Codex) and ignores the others'. Intent
    knobs an engine cannot honor (thinking tokens on the Codex runtime,
    turn timeouts on Claude) follow ``on_unsupported``: refused at
    construction, or cleared with a log line.
    """

    # ``usage_cost`` is a bare Callable, which pydantic only accepts under
    # arbitrary types; every other field is a model, TypedDict, or scalar.
    model_config = {"arbitrary_types_allowed": True}

    model: str
    system_prompt: str = ""
    coding_harness_preset: bool = False
    """Wrap ``system_prompt`` in the engine's coding-harness preset (Claude's
    ``claude_code`` preset + append). ``False`` — the default — sends the
    prompt verbatim. Engines without such a preset (Codex) ignore it. Thinking
    budget and permission handling are the separate ``max_thinking_tokens`` and
    ``permission_mode`` knobs."""

    tool_servers: dict[str, McpServerEntry] = Field(default_factory=dict)
    subagents: list[SubagentSpec] = Field(default_factory=list)
    hooks: LupHooksConfig = Field(default_factory=LupHooksConfig)
    allowed_tools: list[str] = Field(default_factory=list)
    """Tool names the agent may call. The ``mcp__{server}__{tool}`` name of
    every in-process tool server's tools is added automatically — those
    tools are the agent's own — so this field carries only the extras
    (builtins like ``Read``, framework tools). Policy exclusions are the
    caller's to apply before construction; they cannot be derived here."""
    tools: list[str] | None = None
    """Base builtin toolset restriction (``None`` = the engine's default set)."""
    served_tool_groups: list[str] = Field(default_factory=list)
    """Tool-group names served to subprocess engines out of process. Not
    derived from ``tool_servers``: the served set is the caller's group
    registry (it can include groups with no in-process server, e.g. a
    sandbox served only externally), so the caller names it."""
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
    """Token→USD estimator that makes ``max_budget_usd`` enforceable on
    runtimes that report tokens but not cost (Codex). The mechanism behind
    the budget intent, not itself an intent knob."""

    persist_session: bool = True
    """Keep the engine's SDK session alive across turns, vs a one-shot nested
    call that does not persist. Purely about session persistence — the
    session-grade behavior defaults are the separate ``session_defaults`` knob."""
    session_defaults: bool = True
    """Apply the engine's session-grade defaults for intent knobs left unset —
    on Claude, an unset ``max_thinking_tokens`` runs as hard as the API allows
    and an unset ``permission_mode`` bypasses per-call prompts. A full agent
    session wants these; a nested one-shot sets it ``False``. Independent of
    ``persist_session`` so persistence and behavior-defaults stay separate axes."""
    sdk_sandbox: bool = True
    """Enable the engine's own OS sandbox where it has one (Claude SDK)."""
    realtime: bool = False
    on_unsupported: Literal["raise", "drop"] = "raise"
    """What an engine does with intent knobs it cannot honor: refuse the
    construction (sessions fail fast) or clear them with a log line (the
    one-shot ``query()`` degrades)."""

    base_url: str | None = None
    """An OpenAI/Anthropic-compatible endpoint, unset for vendor-served
    models. ``openai-compat`` defines a Codex custom provider from it;
    ``claude-compat`` points the Claude scaffolding at it via
    ``ANTHROPIC_BASE_URL``."""
    api_key: str | None = None
    model_provider: str | None = None
    auth_style: Literal["auth_token", "api_key"] = "auth_token"
    """Which header carries ``api_key`` on a claude-compat endpoint: bearer
    ``ANTHROPIC_AUTH_TOKEN`` (hosted gateways) or native ``x-api-key`` via
    ``ANTHROPIC_API_KEY`` (local servers)."""
    map_model_aliases: bool = True
    """Point Claude's opus/sonnet/haiku aliases at ``model`` on a claude-compat
    endpoint, so a single-model endpoint is never asked for an alias it does
    not serve."""

    codex_sandbox: str | None = None
    """Codex-runtime sandbox mode (named to avoid colliding with
    ``sdk_sandbox``, the Claude SDK's OS sandbox flag)."""
    approval_policy: str | None = None
    mcp_env: dict[str, str] = Field(  # lup: ignore[dict-str-payload] — env map
        default_factory=dict
    )
    writable_roots: list[Path] = Field(default_factory=list)

    session_id: str | None = None
    """Session-wiring trio (``session_id``, ``shared_dir``,
    ``realtime_dir``) mirroring :class:`lup.workspace.context.SessionContext`. Supplied
    by the session builder rather than derived: the on-disk session layout
    (where the shared sandbox dir lives, what the session is named) is the
    caller's to define, not the adapter's."""
    shared_dir: Path | None = None
    realtime_dir: Path | None = None

    @model_validator(mode="after")
    def add_owned_tools_to_allowlist(self) -> "LupAgentOptions":
        """Auto-allow every in-process tool server's own tools.

        The ``mcp__{server}__{tool}`` name of each :class:`LupMcpServerConfig`
        tool joins ``allowed_tools`` (deduped, explicit extras kept first).
        External transport configs cannot be introspected offline, so they
        contribute nothing.
        """
        owned = [
            f"mcp__{name}__{tool}"
            for name, server in self.tool_servers.items()
            if isinstance(server, LupMcpServerConfig)
            for tool in server_tool_names(server)
        ]
        if owned:
            self.allowed_tools = list(dict.fromkeys([*self.allowed_tools, *owned]))
        return self
