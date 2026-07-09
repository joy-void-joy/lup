"""The Claude engine's session implementation: one conversation, one opener.

``ClaudeSessions`` opens SDK sessions over the translated native options;
each ``ClaudeSession`` turn drains through the collector in
:mod:`lup.adapters.clients.claude.collector`. Construction and composition
live in :mod:`lup.adapters.clients.claude.create`.
"""

import copy
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import claude_agent_sdk as claude

from lup.adapters.clients.claude.collector import (
    ClaudeResponseCollector,
    ClaudeUsageNormalizer,
)
from lup.adapters.clients.display import console_tap
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.usage import extract_token_usage
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse


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
            tap=console_tap(prefix=prefix, trace_logger=trace_logger),
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
            :func:`~lup.adapters.clients.claude.translate.build_claude_options`.
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
