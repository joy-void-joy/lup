"""Codex SDK background agent implementation."""

import asyncio
import logging
from collections.abc import Callable

from lup.background import BaseBackgroundAgent

logger = logging.getLogger(__name__)


class CodexBackgroundAgent(BaseBackgroundAgent):
    """Background agent running via an independent Codex thread.

    Codex threads are inherently persistent and concurrent — each
    background agent gets its own thread that runs alongside the main
    agent thread. Communication is through shared Python-level state.
    """

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        build_message: Callable[[], str | None],
        start_message: str = "",
        model: str,
        debounce_seconds: float = 3.0,
        on_response: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            build_message=build_message,
            start_message=start_message,
            model=model,
            debounce_seconds=debounce_seconds,
        )
        self.on_response = on_response

    async def run_loop(self) -> None:
        """Run independent Codex thread for background work."""
        try:
            from openai_codex import AsyncCodex

            async with AsyncCodex() as codex:
                thread = await codex.thread_start(
                    model=self.model,
                    developer_instructions=self.system_prompt,
                )

                async for content in self.message_stream():
                    result = await thread.run(content)
                    if self.on_response and result.final_response:
                        self.on_response(result.final_response)

        except asyncio.CancelledError:
            logger.debug("Codex background agent '%s' cancelled", self.name)
        # Task supervisor: a background crash must be logged but never
        # propagate into (or kill) the main session.
        except Exception:
            logger.exception("Codex background agent '%s' crashed", self.name)
