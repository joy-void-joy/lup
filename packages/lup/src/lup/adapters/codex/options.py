"""Translate neutral :class:`~lup.options.LupAgentOptions` into a Codex adapter.

The one place the fragmented Codex construction lives: budget rates, the
workspace-write roots, the served tool groups, and — for the OpenAI-compatible
endpoint — the custom provider. Realtime is just ``opts.realtime``: it adds the
file-relay mailbox to the returned bundle. The session's container cleanup is
the bundle's ``lifecycle``. The template hands over an assembled
:class:`~lup.options.LupAgentOptions` and never names ``CodexAdapter``.
"""

from contextlib import AbstractContextManager, nullcontext

from lup.adapters.codex.adapter import CodexAdapter
from lup.adapters.codex.openai_compat import OpenAICompatibleAdapter
from lup.adapters.common import OneShotRequest
from lup.options import BuiltAdapter, LupAgentOptions
from lup.realtime_relay import RealtimeMailbox


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


def build_codex_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Build a :class:`~lup.adapters.codex.adapter.CodexAdapter` from neutral options."""
    codex = opts.codex
    adapter = CodexAdapter(
        model=opts.model,
        system_prompt=opts.system_prompt,
        sandbox=codex.sandbox,
        effort=opts.reasoning_effort,
        approval_policy=codex.approval_policy,
        mcp_tools=True,
        mcp_env=dict(codex.mcp_env),
        writable_roots=list(codex.writable_roots),
        mcp_servers=opts.served_tool_groups,
        max_budget_usd=opts.max_budget_usd,
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
    )
    mailbox = (
        RealtimeMailbox(codex.realtime_dir)
        if opts.realtime and codex.realtime_dir is not None
        else None
    )
    return BuiltAdapter(
        adapter=adapter,
        lifecycle=subprocess_sandbox_cleanup(opts),
        mailbox=mailbox,
    )


def build_openai_adapter(opts: LupAgentOptions) -> BuiltAdapter:
    """Build an :class:`~lup.adapters.codex.openai_compat.OpenAICompatibleAdapter`."""
    codex = opts.codex
    adapter = OpenAICompatibleAdapter(
        model=opts.model,
        system_prompt=opts.system_prompt,
        base_url=codex.openai_base_url,
        api_key=codex.openai_api_key,
        model_provider=codex.openai_model_provider,
        sandbox=codex.sandbox,
        effort=opts.reasoning_effort,
        approval_policy=codex.approval_policy,
        mcp_tools=True,
        mcp_env=dict(codex.mcp_env),
        writable_roots=list(codex.writable_roots),
        mcp_servers=opts.served_tool_groups,
        max_budget_usd=opts.max_budget_usd,
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
    )
    mailbox = (
        RealtimeMailbox(codex.realtime_dir)
        if opts.realtime and codex.realtime_dir is not None
        else None
    )
    return BuiltAdapter(
        adapter=adapter,
        lifecycle=subprocess_sandbox_cleanup(opts),
        mailbox=mailbox,
    )


def build_codex_one_shot(request: OneShotRequest) -> CodexAdapter:
    """Build the adapter for a one-shot query on the Codex runtime.

    No tool subprocesses: a one-shot has no session context to serve, so
    MCP stays off and the runtime's own toolset is what the model gets.
    """
    return CodexAdapter(
        model=request.model,
        system_prompt=request.system_prompt or "",
        output_schema=request.output_schema,
        mcp_tools=False,
    )


def build_openai_one_shot(request: OneShotRequest) -> OpenAICompatibleAdapter:
    """Build the one-shot adapter for an OpenAI-compatible endpoint.

    Endpoint configuration (base URL, provider) comes from the caller's
    ambient Codex config — a one-shot request carries none.
    """
    return OpenAICompatibleAdapter(
        model=request.model,
        system_prompt=request.system_prompt or "",
        output_schema=request.output_schema,
        mcp_tools=False,
    )
