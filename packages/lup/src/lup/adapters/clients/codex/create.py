"""The Codex engine's construction door: ``create_codex`` + the composition.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.codex.translate`, then composes the runtime's
components into the one client shape — the recipe below is the whole
composition, every slot named.
"""

from lup.adapters.clients.Client import Client
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.sessions import CodexSessions
from lup.adapters.clients.codex.translate import build_codex_native
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.clients.sessions.budget import BudgetedSessions
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.sessions.timeout import TimeoutSessions
from lup.adapters.options import LupAgentOptions


def create_codex(options: LupAgentOptions) -> Client:
    """Build a Codex-runtime client from neutral options.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots) and ignores the in-process ones (hooks, tool
    servers — enforcement here is the runtime's native sandbox) and the
    Claude-only ``coding_harness_preset``/``sdk_sandbox`` shape flags. Subagent
    specs are served through the ``run_subagent`` tool group rather than
    run natively.
    """
    return compose_codex(refuse_unconsumed("codex", options, build_codex_native))


def compose_codex(native: CodexNativeConfig) -> ComposedClient:
    """Compose the Codex runtime's components into the one client shape.

    Codex contributes only its sessions — the runtime reports a turn only
    once complete, so the stream slot is left to the replay gap-filler —
    and the turn governance the runtime lacks is composed over them: a
    wall clock per turn when ``turn_timeout_seconds`` is set, and cost
    metering (with the budget refusal) when ``usage_cost`` prices the
    token counts — cumulative, because Codex usage reports thread
    totals. ``openai-compat`` reuses this composition over its own
    translation.
    """
    sessions: Sessions = CodexSessions(native)
    if native.turn_timeout_seconds is not None:
        sessions = TimeoutSessions(sessions, seconds=native.turn_timeout_seconds)
    if native.usage_cost is not None:
        sessions = BudgetedSessions(
            sessions,
            usage_cost=native.usage_cost,
            max_budget_usd=native.max_budget_usd,
            cumulative=True,
        )
    return ComposedClient(sessions)
