"""The neutral seam: every engine behind ``create_client()`` and ``query()``.

An engine is one backend, complete: a ``create_*`` factory that turns
neutral :class:`LupAgentOptions` into a :class:`~lup.adapters.clients.Client.Client`,
and the client opens :class:`~lup.adapters.clients.Client.Session`\\ s.
``query()`` is the self-contained one-shot (opens, sends, closes —
nothing to leak); ``session()`` is the explicit multi-turn context,
resumable across process runs via ``session(resume=...)`` and
``Session.id``.

This module is SDK-free. Two plain routers relate names to engine
factories, and both keep their values lazy — thin module-level wrappers
that import the engine module only when called — so ``import lup`` works
with neither SDK installed and each engine pulls in only its own:

- :data:`ENGINES` maps each shipped engine id to its factory. Insertion
  order is the capability-table display order; anything needing the
  shipped ids iterates it.
- :data:`MODEL_ROUTES` maps a model-name regex to a factory, first match
  wins. The keys are regexes (not prefixes) so a future route can
  deconstruct a model name via named groups into subparams — e.g. a
  ``r"(?P<family>gpt)-(?P<size>\\d+)"`` key could read ``family``/``size``
  off the match. No route does that today; the shape is ready for it.

There is no registry to mutate and no capability declarations to branch
on: a custom backend is a factory callable passed as ``engine=``, an
engine refuses intent knobs it cannot honor (``UnsupportedOptionsError``;
``query()`` drops them with a log line), unsupported operations raise
``UnsupportedOperationError`` at the point of use, and the devtools
capability table is probed from that behavior rather than declared.
"""

import logging
import re
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, model_validator

from lup.hooks import LupHooksConfig
from lup.mcp import LupMcpServerConfig, McpServerEntry, server_tool_names
from lup.telemetry.trace import TraceLogger
from lup.types import (
    JsonObject,
    LupResponse,
    PermissionMode,
    SubagentSpec,
    UsageCost,
)

if TYPE_CHECKING:
    from lup.adapters.clients.Client import Client

logger = logging.getLogger(__name__)


class LupAgentOptions(BaseModel):
    """Everything an engine needs to construct a client, in neutral terms.

    A caller assembles one of these (its domain work: which tools, which
    hooks, which subagents, the model knobs) and hands it to
    :func:`create_client`; the engine's factory translates it into its
    native option object. No consumer names a backend or touches a native
    option type. Each engine consumes the mechanism payloads that belong
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

    tool_servers: dict[str, McpServerEntry] = {}
    subagents: list[SubagentSpec] = []
    hooks: LupHooksConfig = LupHooksConfig()
    allowed_tools: list[str] = []
    """Tool names the agent may call. The ``mcp__{server}__{tool}`` name of
    every in-process tool server's tools is added automatically — those
    tools are the agent's own — so this field carries only the extras
    (builtins like ``Read``, framework tools). Policy exclusions are the
    caller's to apply before construction; they cannot be derived here."""
    tools: list[str] | None = None
    """Base builtin toolset restriction (``None`` = the engine's default set)."""
    served_tool_groups: list[str] = []
    """Tool-group names served to subprocess engines out of process. Not
    derived from ``tool_servers``: the served set is the caller's group
    registry (it can include groups with no in-process server, e.g. a
    sandbox served only externally), so the caller names it."""
    add_dirs: list[Path] = []
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
    mcp_env: dict[str, str] = {}
    writable_roots: list[Path] = []

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


class UnsupportedOperationError(NotImplementedError):
    """The engine behind this client cannot perform the requested operation.

    Raised at the point of use — ``interrupt()`` on a runtime with no
    interruption support, ``session(resume=...)`` on an engine that cannot
    restore threads. A ``NotImplementedError`` subclass, so generic
    ``except NotImplementedError`` handlers also catch it.
    """


class UnsupportedOptionsError(ValueError):
    """The engine cannot honor intent knobs the options carry.

    Raised at construction (``on_unsupported="raise"``, the session
    default), so a session that asked for, say, ``max_turns`` on a runtime
    without turn caps fails before it starts. ``fields`` names the
    offenders. With ``on_unsupported="drop"`` the engine clears them and
    logs instead — the one-shot ``query()`` policy.
    """

    def __init__(self, engine: str, fields: list[str]) -> None:
        self.engine = engine
        self.fields = sorted(fields)
        super().__init__(
            f"options {self.fields} are not supported on the {engine} engine; "
            "unset them or run on an engine that honors them."
        )


class TurnTimeoutError(RuntimeError):
    """A turn exceeded its wall-clock timeout and was cancelled client-side.

    Raised by engines that enforce ``turn_timeout_seconds`` when a single
    turn runs past it. The backend thread's state is undefined afterwards
    — close the session rather than sending further turns on it.
    """


class BudgetExceededError(RuntimeError):
    """A session refused to start a turn: accumulated cost reached the budget.

    Raised between turns by engines that enforce ``max_budget_usd``
    through their own usage accounting (the Codex runtime reports token
    counts, not cost). The turn that crossed the budget has already
    completed — this error stops the *next* one.
    """


type ClientFactory = Callable[[LupAgentOptions], "Client"]
"""One engine, as the seam sees it: neutral options in, a configured
:class:`~lup.adapters.clients.Client.Client` out. The shipped engines'
factories live in ``lup.adapters.clients.*``; a custom backend is any
callable of this shape passed as ``engine=``."""


def lazy_engine(module: str, factory: str) -> ClientFactory:
    """Build one engine's factory: the single object both routers key on by identity.

    The returned callable imports ``module``'s ``create_*`` only when first
    invoked, so ``import lup`` needs no SDK installed and each engine pulls in
    only its own optional dependency. Bind the result to one module-level name
    and reference that same object from both :data:`ENGINES` and
    :data:`MODEL_ROUTES`: :func:`engine_id_of` recovers an engine's id by object
    identity, so a per-engine factory must stay one object, never two lambdas.
    """

    def create(options: LupAgentOptions) -> "Client":
        create_native: ClientFactory = getattr(import_module(module), factory)
        return create_native(options)

    return create


claude_engine = lazy_engine("lup.adapters.clients.claude", "create_claude")
claude_compat_engine = lazy_engine(
    "lup.adapters.clients.claude_compat", "create_claude_compat"
)
codex_engine = lazy_engine("lup.adapters.clients.codex", "create_codex")
openai_compat_engine = lazy_engine(
    "lup.adapters.clients.openai_compat", "create_openai_compat"
)


ENGINES: dict[str, ClientFactory] = {
    "claude": claude_engine,
    "codex": codex_engine,
    "openai-compat": openai_compat_engine,
    "claude-compat": claude_compat_engine,
}
"""The id router: every shipped engine's factory, in display order. The
capability table renders one column per entry, in this order."""

MODEL_ROUTES: dict[str, ClientFactory] = {
    r"^claude-|^(?:haiku|sonnet|opus)$": claude_engine,
    r"^gpt-|^o\d+-|^codex-": codex_engine,
    r"": openai_compat_engine,
}
"""The model-name router: a regex per engine, first match wins. A
``claude-`` prefix and the bare aliases route to ``claude``; a
``gpt-``/``o<digit>-``/``codex-`` prefix routes to ``codex``; the empty
pattern matches anything left over, landing unknown models on
``openai-compat``. ``claude-compat`` is never inferred — open models
behind an Anthropic-style endpoint name it explicitly."""


def factory_for_model(model: str) -> ClientFactory:
    """The engine factory a model name infers to — first :data:`MODEL_ROUTES` match."""
    for pattern, factory in MODEL_ROUTES.items():
        if re.search(pattern, model):
            return factory
    return openai_compat_engine


def engine_id_of(factory: ClientFactory) -> str:
    """The :data:`ENGINES` id for a factory, for display and family checks.

    The routers share one factory object per engine, so a factory pulled
    out of :data:`MODEL_ROUTES` finds its id here by identity.
    """
    for engine_id, engine_factory in ENGINES.items():
        if engine_factory is factory:
            return engine_id
    raise ValueError(f"factory {factory!r} is not a shipped engine")


def resolve_factory(
    engine: "str | ClientFactory | None", *, model: str
) -> ClientFactory:
    """Pick the engine factory: explicit callable > id in :data:`ENGINES` > model route."""
    match engine:
        case None:
            return factory_for_model(model)
        case str():
            try:
                return ENGINES[engine]
            except KeyError:
                raise ValueError(
                    f"Unknown engine {engine!r}. Shipped ids: "
                    f"{', '.join(ENGINES)}; pass a factory callable for a "
                    "custom backend."
                ) from None
        case _:
            return engine


def create_client(
    *,
    model: str | None = None,
    engine: "str | ClientFactory | None" = None,
    options: LupAgentOptions | None = None,
    system_prompt: str | None = None,
    output_type: type[BaseModel] | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    max_budget_usd: float | None = None,
    on_unsupported: Literal["raise", "drop"] = "raise",
) -> "Client":
    """Build a configured :class:`~lup.adapters.clients.Client.Client` — the one door to every engine.

    The keyword form is the nested-call tier: raw system prompt, nothing
    persists, no SDK sandbox — what a tool that needs an LLM call wants.
    Session-grade construction (harness preset, hooks, tool servers,
    persistence) passes a full ``options`` object instead; combining the
    two forms raises rather than silently ignoring keywords.

    Every argument is a construction knob, fixed for the client's
    lifetime; run-time arguments (the prompt, tracing) go to
    ``Client.query`` and ``Session.send``.

    ``engine`` accepts a shipped id, a custom factory callable, or ``None``
    to infer the engine from the model name.
    """
    keyword_form = {
        "model": model,
        "system_prompt": system_prompt,
        "output_type": output_type,
        "tools": tools,
        "allowed_tools": allowed_tools,
        "permission_mode": permission_mode,
        "max_turns": max_turns,
        "max_thinking_tokens": max_thinking_tokens,
        "max_budget_usd": max_budget_usd,
    }
    if options is not None:
        given = sorted(
            name for name, value in keyword_form.items() if value is not None
        )
        if given:
            raise ValueError(
                f"create_client: a full options object was given together with "
                f"keyword arguments {given}, which would be silently ignored — "
                "set them on the options object instead."
            )
        opts = options
    else:
        if model is None:
            raise ValueError(
                "create_client needs model=... (or a full options= object)."
            )
        opts = LupAgentOptions(
            model=model,
            system_prompt=system_prompt or "",
            persist_session=False,
            session_defaults=False,
            sdk_sandbox=False,
            output_schema=output_type.model_json_schema() if output_type else None,
            tools=tools,
            allowed_tools=allowed_tools or [],
            permission_mode=permission_mode,
            max_turns=max_turns,
            max_thinking_tokens=max_thinking_tokens,
            max_budget_usd=max_budget_usd,
            on_unsupported=on_unsupported,
        )
    return resolve_factory(engine, model=opts.model)(opts)


async def query(
    prompt: str,
    *,
    model: str = "claude-opus-4-6",
    engine: "str | ClientFactory | None" = None,
    system_prompt: str | None = None,
    output_type: type[BaseModel] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    max_budget_usd: float | None = None,
) -> LupResponse:
    """One-shot query — the one-liner for nested LLM calls inside tools.

    Sugar over :func:`create_client`: builds a call-tier client for the
    model's engine and runs a single self-contained query. Intent knobs
    the engine cannot honor are dropped with a log line rather than
    raising — a caller can express full intent and let the engine keep
    what it can.

    Returns a ``LupResponse`` — use ``.text`` for text or
    ``.output(MyModel)`` for structured output.
    """
    client = create_client(
        model=model,
        engine=engine,
        system_prompt=system_prompt,
        output_type=output_type,
        tools=tools,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        max_turns=max_turns,
        max_thinking_tokens=max_thinking_tokens,
        max_budget_usd=max_budget_usd,
        on_unsupported="drop",
    )
    return await client.query(prompt, trace_logger=trace_logger, prefix=prefix)
