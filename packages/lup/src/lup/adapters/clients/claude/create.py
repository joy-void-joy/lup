"""The Claude engine's construction door: ``create_claude`` + the composition.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.claude.translate`, then composes the engine's
components — :class:`~lup.adapters.clients.claude.sessions.ClaudeSessions`
and the live :class:`~lup.adapters.clients.claude.stream.ClaudeLiveStream`
— into the one client shape.
"""

import claude_agent_sdk as claude

from lup.adapters.clients.claude.translate import build_claude_options
from lup.adapters.clients.claude.sessions import ClaudeSessions
from lup.adapters.clients.claude.stream import ClaudeLiveStream
from lup.adapters.clients.Client import Client
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.options import LupAgentOptions


def create_claude(options: LupAgentOptions) -> Client:
    """Build a Claude Agent SDK client from neutral options.

    Consumes the in-process mechanism payloads (hooks, tool servers,
    native subagent definitions) and ignores the subprocess ones (served
    tool groups, writable roots). The one intent knob the SDK has no lever
    for is ``turn_timeout_seconds`` — the SDK exposes no client-side
    per-turn wall-clock cap (checked against claude-agent-sdk's
    ``ClaudeAgentOptions``: ``max_turns`` and ``max_budget_usd`` exist,
    nothing bounds a single turn's duration), so it is left unread and
    refused.
    """
    return compose_claude(refuse_unconsumed("claude", options, build_claude_options))


def compose_claude(native: claude.ClaudeAgentOptions) -> ComposedClient:
    """Compose the Claude engine's components into the one client shape.

    Claude contributes both verbs — its sessions and a live event stream —
    so nothing is gap-filled. ``claude-compat`` reuses this composition
    over its own translation.
    """
    return ComposedClient(ClaudeSessions(native), streams=ClaudeLiveStream(native))
