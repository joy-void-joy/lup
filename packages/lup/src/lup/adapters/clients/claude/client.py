"""The Claude engine's run path: ``create_claude``, sessions, composition.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.claude.options`, then composes the engine's
components — :class:`ClaudeSessions` and the live
:class:`~lup.adapters.clients.claude.stream.ClaudeLiveStream` — into the
one client shape; the session path drains every turn through the
collector in :mod:`lup.adapters.clients.claude.collector`.
"""

import copy
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import claude_agent_sdk as claude

from lup.adapters.clients.claude.collector import (
    ClaudeResponseCollector,
    ClaudeUsageNormalizer,
)
from lup.adapters.clients.claude.options import build_claude_options
from lup.adapters.clients.claude.stream import ClaudeLiveStream
from lup.adapters.clients.Client import Client
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.usage import extract_token_usage
from lup.adapters.options import LupAgentOptions
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse


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


class ClaudeSession(Session):
    """Multi-turn conversation via the Claude Agent SDK.

    ``id`` carries the SDK session id: seeded when the session was opened
    with ``resume=``, refreshed from each turn's result otherwise.
    """

    def __init__(
        self,
        client: claude.ClaudeSDKClient,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
        resumed: str | None = None,
    ) -> None:
        self.client = client
        self.usage_normalizer = usage_normalizer
        self.id = resumed

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        await self.client.query(prompt)
        collector = ClaudeResponseCollector(
            self.client,
            usage_normalizer=self.usage_normalizer,
            trace_logger=trace_logger,
            prefix=prefix,
        )
        response = await collector.collect()
        self.id = response.session_id or self.id
        return response

    async def interrupt(self) -> None:
        await self.client.interrupt()


class ClaudeSessions(Sessions):
    """Opens Claude Agent SDK sessions.

    Args:
        options: Native SDK options built by
            :func:`~lup.adapters.clients.claude.options.build_claude_options`.
        usage_normalizer: Transforms the raw SDK usage payload into a
            ``Usage`` (or subclass, for vendor-specific fields).
    """

    def __init__(
        self,
        options: claude.ClaudeAgentOptions,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    ) -> None:
        self.options = options
        self.usage_normalizer = usage_normalizer

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        options = self.options
        if resume:
            options = copy.copy(self.options)
            options.resume = resume
        async with claude.ClaudeSDKClient(options=options) as client:
            yield ClaudeSession(
                client, usage_normalizer=self.usage_normalizer, resumed=resume
            )
