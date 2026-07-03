"""The Claude engines: the Claude Agent SDK behind the Engine seam.

``ClaudeEngine`` runs Anthropic models with the full scaffolding —
in-process MCP servers, permission hooks, native subagents, the SDK
sandbox. ``ClaudeCompatEngine`` points the same scaffolding at any
Anthropic-protocol-compatible endpoint (GLM and friends), so open models
get hooks, permission modes, and native subagents instead of the bare
Codex runtime.
"""

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import EffortLevel, McpSdkServerConfig, SystemPromptPreset

from lup.adapters.claude.adapter import (
    ClaudeClient,
    lup_hooks_to_claude,
    lup_server_to_claude,
    spec_to_claude,
)
from lup.adapters.common import Client
from lup.adapters.engine import Engine, enforce_supported
from lup.background import BackgroundAgentParams, BaseBackgroundAgent
from lup.mcp import LupMcpServerConfig, McpServerEntry, RawMcpServerConfig
from lup.options import LupAgentOptions
from lup.types import normalize_effort

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
    tool groups, the ``codex`` block). The one intent knob it cannot
    honor is a client-side turn timeout.
    """

    id = "claude"

    def native_options(self, opts: LupAgentOptions) -> ClaudeAgentOptions:
        """Translate neutral options to the SDK's — the compat seam."""
        return build_claude_options(opts)

    def client(self, opts: LupAgentOptions) -> Client:
        opts = enforce_supported(
            opts, engine=self.id, unsupported=("turn_timeout_seconds",)
        )
        return ClaudeClient(self.native_options(opts))

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        """Claude backgrounds can act through tools; opus-class by default."""
        from lup.adapters.claude.background import ClaudeBackgroundAgent

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


class ClaudeCompatEngine(ClaudeEngine):
    """Anthropic-protocol-compatible endpoints through the Claude scaffolding.

    Points the Claude SDK at ``opts.compat.base_url`` via the SDK
    subprocess environment (``ANTHROPIC_BASE_URL``/``ANTHROPIC_AUTH_TOKEN``),
    so open models served behind an Anthropic-style API (GLM et al.) keep
    hooks, permission modes, and native subagents. Everything else —
    option translation, backgrounds, unsupported knobs — is inherited.
    """

    id = "claude-compat"

    def native_options(self, opts: LupAgentOptions) -> ClaudeAgentOptions:
        if not opts.compat.base_url:
            raise ValueError(
                "the claude-compat engine needs compat.base_url — the "
                "Anthropic-compatible endpoint the Claude scaffolding "
                "should talk to (OPENAI_BASE_URL / CompatOptions)."
            )
        native = super().native_options(opts)
        native.env["ANTHROPIC_BASE_URL"] = opts.compat.base_url
        if opts.compat.api_key:
            native.env["ANTHROPIC_AUTH_TOKEN"] = opts.compat.api_key
        return native
