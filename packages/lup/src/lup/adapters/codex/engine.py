"""The Codex engines: the OpenAI Codex runtime behind the Engine seam.

``CodexEngine`` runs OpenAI models on the Codex app-server; the runtime is
a subprocess, so tools are served externally (``served_tool_groups``),
writes are confined natively (``writable_roots``), and persistent mode
rides the file-relay mailbox. ``OpenAICompatEngine`` fronts any
OpenAI-protocol endpoint by defining a custom Codex provider from
``opts.compat``.
"""

import logging
from contextlib import AbstractContextManager, nullcontext

from lup.adapters.codex.adapter import CodexClient
from lup.adapters.codex.openai_compat import OpenAICompatClient
from lup.adapters.common import Client
from lup.adapters.engine import Engine, enforce_supported
from lup.background import BackgroundAgentParams, BaseBackgroundAgent
from lup.options import LupAgentOptions
from lup.realtime_relay import RealtimeMailbox

logger = logging.getLogger(__name__)

CODEX_UNSUPPORTED: tuple[str, ...] = (
    "max_turns",
    "max_thinking_tokens",
    "permission_mode",
    "tools",
)
"""Intent knobs the Codex runtime has no lever for: no per-session turn
cap, no thinking-token budget, no permission modes, no builtin-toolset
restriction."""


def subprocess_sandbox_cleanup(
    opts: LupAgentOptions,
) -> AbstractContextManager[object]:
    """Guarantee the session's subprocess sandbox container dies on exit.

    The Codex/OpenAI tool subprocess may be killed before it can clean up its
    own container; the parent removes it. A no-op without the docker extra, or
    when the build names no session.
    """
    codex = opts.codex
    if codex.session_id is None or codex.shared_dir is None:
        return nullcontext()
    try:
        from lup.sandbox import sandbox_cleanup
    except ImportError:
        return nullcontext()
    return sandbox_cleanup(session_id=codex.session_id, shared_dir=codex.shared_dir)


class CodexEngine(Engine):
    """OpenAI models on the Codex runtime.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots, the ``codex`` block); ignores the in-process
    ones (hooks, tool servers — enforcement here is the runtime's native
    sandbox) and the Claude-only ``harness_prompt``/``sdk_sandbox`` shape
    flags (the runtime always applies its own harness and sandbox).
    Subagent specs are served through the ``run_subagent`` tool group
    rather than run natively.
    """

    id = "codex"

    def enforce(self, opts: LupAgentOptions) -> LupAgentOptions:
        """Apply the on_unsupported policy to this runtime's blind spots.

        A budget without caller-supplied rates joins the unsupported set:
        the runtime reports token counts, never cost, so there is nothing
        to enforce the budget against.
        """
        unsupported = list(CODEX_UNSUPPORTED)
        if opts.max_budget_usd is not None and opts.usage_cost is None:
            unsupported.append("max_budget_usd")
        return enforce_supported(opts, engine=self.id, unsupported=tuple(unsupported))

    def build(self, opts: LupAgentOptions) -> CodexClient:
        """Construct the client — the compat subclass swaps the class."""
        codex = opts.codex
        return CodexClient(
            model=opts.model,
            system_prompt=opts.system_prompt,
            output_schema=opts.output_schema,
            sandbox=codex.sandbox,
            effort=opts.reasoning_effort,
            approval_policy=codex.approval_policy,
            mcp_tools=bool(opts.served_tool_groups),
            mcp_env=dict(codex.mcp_env),
            writable_roots=list(codex.writable_roots),
            mcp_servers=opts.served_tool_groups,
            max_budget_usd=opts.max_budget_usd,
            usage_cost=opts.usage_cost,
            turn_timeout_seconds=opts.turn_timeout_seconds,
            cleanup=subprocess_sandbox_cleanup(opts),
        )

    def client(self, opts: LupAgentOptions) -> Client:
        opts = self.enforce(opts)
        client = self.build(opts)
        if opts.realtime and opts.codex.realtime_dir is not None:
            client.mailbox = RealtimeMailbox(opts.codex.realtime_dir)
        return client

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        """Codex backgrounds are text-only summarizers with explicit models.

        Tool support is a property of this engine: background tools share
        in-process state with the main session, which cannot cross the
        Codex subprocess boundary, so a tool request fails loudly. Codex
        accounts accept only their own model list, so there is no safe
        default model.
        """
        if params.tools or params.builtin_tools or params.allowed_tools:
            raise ValueError(
                "Codex background agents cannot use tools: background "
                "tools share in-process state with the main session, "
                "which cannot cross the Codex subprocess boundary. "
                "Use the claude engine for tool-using background agents."
            )
        if params.model is None:
            raise ValueError(
                "Codex background agents need an explicit model: Codex "
                "accounts accept only their own model list (e.g. "
                "gpt-5.5), so there is no safe default."
            )
        from lup.adapters.codex.background import CodexBackgroundAgent

        return CodexBackgroundAgent(
            name=params.name,
            system_prompt=params.system_prompt,
            build_message=params.build_message,
            start_message=params.start_message,
            model=params.model,
            debounce_seconds=params.debounce_seconds,
            on_response=params.on_response,
        )


class OpenAICompatEngine(CodexEngine):
    """Any OpenAI-protocol endpoint through the Codex runtime.

    Identical to :class:`CodexEngine` except construction: the client
    carries ``opts.compat`` (base URL, key, provider id) and defines a
    custom Codex provider from it. Anthropic-protocol endpoints belong on
    ``claude-compat`` instead, which keeps the Claude scaffolding.
    """

    id = "openai-compat"

    def build(self, opts: LupAgentOptions) -> CodexClient:
        codex = opts.codex
        return OpenAICompatClient(
            model=opts.model,
            system_prompt=opts.system_prompt,
            base_url=opts.compat.base_url,
            api_key=opts.compat.api_key,
            model_provider=opts.compat.model_provider,
            output_schema=opts.output_schema,
            sandbox=codex.sandbox,
            effort=opts.reasoning_effort,
            approval_policy=codex.approval_policy,
            mcp_tools=bool(opts.served_tool_groups),
            mcp_env=dict(codex.mcp_env),
            writable_roots=list(codex.writable_roots),
            mcp_servers=opts.served_tool_groups,
            max_budget_usd=opts.max_budget_usd,
            usage_cost=opts.usage_cost,
            turn_timeout_seconds=opts.turn_timeout_seconds,
            cleanup=subprocess_sandbox_cleanup(opts),
        )
