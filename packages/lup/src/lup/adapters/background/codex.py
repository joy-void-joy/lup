"""Codex-runtime background agent.

Codex threads are inherently persistent and concurrent — each background
agent gets its own thread running alongside the main agent thread.
Communication is through shared Python-level state. Codex backgrounds are
text-only summarizers with an explicit model: their tools would share
in-process state the subprocess boundary cannot cross, and Codex accounts
accept only their own model list, so there is no safe default.
"""

import asyncio
import logging
from collections.abc import Callable

from lup.adapters.background.common import BackgroundAgentParams, BaseBackgroundAgent

logger = logging.getLogger(__name__)


def build_codex_background(params: BackgroundAgentParams) -> BaseBackgroundAgent:
    """Build a Codex background agent — text-only, explicit model required.

    Tool support is a property of this engine: background tools share
    in-process state with the main session, which cannot cross the Codex
    subprocess boundary, so a tool request fails loudly. Codex accounts
    accept only their own model list, so there is no safe default model.
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
    return CodexBackgroundAgent(
        name=params.name,
        system_prompt=params.system_prompt,
        build_message=params.build_message,
        start_message=params.start_message,
        model=params.model,
        debounce_seconds=params.debounce_seconds,
        on_response=params.on_response,
    )


class CodexBackgroundAgent(BaseBackgroundAgent):
    """Background agent running via an independent Codex thread."""

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
            import openai_codex as codex

            async with codex.AsyncCodex() as codex_client:
                thread = await codex_client.thread_start(
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
