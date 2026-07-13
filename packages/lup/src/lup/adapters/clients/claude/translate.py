"""Neutral→native option translation for the Claude engine.

:func:`build_claude_options` is the engine's whole translation — what it
reads off :class:`~lup.adapters.options.LupAgentOptions` is exactly what
the engine honors (see :mod:`lup.adapters.clients.refusal`) — including
each construction payload's adaption (:func:`spec_to_claude` for
subagents). The ``claude-compat`` engine reuses it and points the native
env at its endpoint afterward.
"""

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.clients.claude.hooks import lup_hooks_to_claude
from lup.adapters.options import LupAgentOptions
from lup.mcp import LupMcpServerConfig, RawMcpServerConfig
from lup.types import SubagentSpec

SESSION_THINKING_TOKENS = 128_000 - 1
"""The Claude engine's session-grade thinking default: as hard as the API
allows. A session (``session_defaults``) that leaves ``max_thinking_tokens``
unset runs at this; a nested one-shot keeps the SDK default."""

# CLI flag names to values: open, flag-shaped keys, filled conditionally.
type ExtraArgs = dict[str, str | None]  # lup: ignore[dict-str-payload] — open CLI flags
type ClaudeServerMap = dict[str, claude_types.McpSdkServerConfig | RawMcpServerConfig]


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


def build_claude_options(opts: LupAgentOptions) -> claude.ClaudeAgentOptions:
    """Assemble the native ``ClaudeAgentOptions`` from neutral options.

    ``coding_harness_preset`` wraps the system prompt in the ``claude_code``
    preset; otherwise the prompt is used raw. Independently, a session
    (``session_defaults``) takes the Claude engine's session-grade
    defaults for any intent knob left unset: an unset ``permission_mode``
    bypasses per-call prompts (enforcement is the hook layer the options
    carry) and an unset ``max_thinking_tokens`` runs as hard as the API
    allows. A nested one-shot keeps the SDK defaults.

    Shared by :func:`~lup.adapters.clients.claude.create.create_claude` and
    :func:`~lup.adapters.clients.claude.compat.create_claude_compat`, which
    reads ``base_url`` onto the native env afterward.
    """
    system_prompt: str | claude_types.SystemPromptPreset | None
    if opts.coding_harness_preset:
        system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": opts.system_prompt,
        }
    else:
        system_prompt = opts.system_prompt or None

    max_thinking = opts.max_thinking_tokens
    permission_mode = opts.permission_mode
    if opts.session_defaults:
        if max_thinking is None:
            max_thinking = SESSION_THINKING_TOKENS
        if permission_mode is None:
            permission_mode = "bypassPermissions"

    extra_args: ExtraArgs = {}
    if not opts.persist_session:
        extra_args["no-session-persistence"] = None

    def to_claude_server(
        server: LupMcpServerConfig | RawMcpServerConfig,
    ) -> claude_types.McpServerConfig:
        match server:
            case LupMcpServerConfig():
                return claude_types.McpSdkServerConfig(
                    type="sdk", name=server.name, instance=server.server
                )
            case _:
                return server

    mcp_servers: ClaudeServerMap = {
        name: to_claude_server(server) for name, server in opts.tool_servers.items()
    }
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
