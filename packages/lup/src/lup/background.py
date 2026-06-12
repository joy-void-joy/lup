"""Background agents for persistent sessions.

A background agent runs alongside a main agent for the entire session
lifetime. It has its own SDK client, tools, and system prompt, and
communicates with the main agent through shared mutable state.

Use cases:
- Observation: summarize conversations as they unfold
- Research: fetch and process data while the main agent continues
- Execution: run long-running tool calls without blocking
- Multiple agents can coexist in a single session

The pattern:
1. Create a BackgroundAgent with tools and a ``build_message`` callback
2. Start it — it runs as an asyncio task until stopped
3. Wake it when new data is available
4. It processes data via tool calls that write to shared state
5. The main agent reads results through its own tools

See ``src/lup_template/agent/tools/realtime.py`` for example integration with
the persistent agent pattern (observer example).

Examples:
    Create an observer that maintains conversation notes::

        >>> from lup.background import create_background_agent
        >>> notes: list[str] = []
        >>> agent = create_background_agent(
        ...     "claude",
        ...     name="observer",
        ...     system_prompt="Summarize conversations...",
        ...     tools=create_observer_tools(notes=notes),
        ...     build_message=build_observer_message,
        ...     allowed_tools=["mcp__observer__notes"],
        ... )
        >>> agent.start()
        >>> agent.wake()  # signal new data
        >>> await agent.stop()

    Run multiple background agents in parallel::

        >>> observer = create_background_agent("claude", name="observer", ...)
        >>> researcher = create_background_agent(
        ...     "claude",
        ...     name="researcher",
        ...     builtin_tools=["Read", "Grep", "WebFetch"],
        ...     ...
        ... )
        >>> observer.start()
        >>> researcher.start()
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from lup.mcp import LupMcpTool

logger = logging.getLogger(__name__)


class BaseBackgroundAgent(ABC):
    """Base class for background agents running alongside a main session."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        build_message: Callable[[], str | None],
        start_message: str = "",
        model: str,
        debounce_seconds: float = 3.0,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.build_message = build_message
        self.start_message = start_message or f"[{name} started]"
        self.model = model
        self.debounce_seconds = debounce_seconds

        self.runner: asyncio.Task[None] | None = None
        self.wake_event: asyncio.Event = asyncio.Event()
        self.running = False

    def start(self) -> None:
        """Start the background agent as an asyncio task."""
        if self.runner and not self.runner.done():
            return
        self.running = True
        self.runner = asyncio.create_task(self.run_loop())

    def wake(self) -> None:
        """Signal that new data is available for processing."""
        self.wake_event.set()

    async def stop(self) -> None:
        """Cancel the background agent and wait for cleanup."""
        self.running = False
        if self.runner and not self.runner.done():
            self.runner.cancel()
            try:
                await self.runner
            except asyncio.CancelledError:
                pass
        self.runner = None

    @abstractmethod
    async def run_loop(self) -> None:
        """SDK-specific run loop. Implemented by each adapter."""
        ...


def create_background_agent(
    sdk: str,
    *,
    name: str,
    system_prompt: str,
    build_message: Callable[[], str | None],
    start_message: str = "",
    model: str | None = None,
    debounce_seconds: float = 3.0,
    tools: list[LupMcpTool] | None = None,
    builtin_tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    on_response: Callable[[object], None] | None = None,
) -> BaseBackgroundAgent:
    """Factory for creating SDK-appropriate background agents.

    Tool support differs by backend: background tools communicate with
    the main session through shared in-process state, which cannot
    cross the Codex subprocess boundary — requesting tools with
    ``sdk="codex"`` raises. Claude backgrounds default to an opus-class
    model because they can act through tools; Codex backgrounds are
    prompt-in/text-out summarizers and require an explicit model —
    Codex accounts accept only their own model list, so there is no
    safe default.

    Args:
        sdk: "claude" or "codex".
        name: Agent identifier.
        system_prompt: System prompt for the background agent.
        build_message: Callable that returns the next message or None.
        start_message: Initial message when agent starts.
        model: Model override (defaults vary by SDK).
        debounce_seconds: Batch rapid wakes.
        tools: LupMcpTool instances (Claude only).
        builtin_tools: Built-in SDK tools (Claude only).
        allowed_tools: Tool allowlist (Claude only).
        on_response: Callback for responses.
    """
    match sdk:
        case "claude":
            from lup.adapters.claude_background import ClaudeBackgroundAgent

            return ClaudeBackgroundAgent(
                name=name,
                system_prompt=system_prompt,
                tools=tools or [],
                build_message=build_message,
                start_message=start_message,
                model=model or "claude-opus-4-6",
                debounce_seconds=debounce_seconds,
                builtin_tools=builtin_tools,
                allowed_tools=allowed_tools,
                on_response=on_response,
            )
        case "codex":
            if tools or builtin_tools or allowed_tools:
                raise ValueError(
                    "Codex background agents cannot use tools: background "
                    "tools share in-process state with the main session, "
                    "which cannot cross the Codex subprocess boundary. "
                    "Use sdk='claude' for tool-using background agents."
                )
            if model is None:
                raise ValueError(
                    "Codex background agents need an explicit model: Codex "
                    "accounts accept only their own model list (e.g. "
                    "gpt-5.5), so there is no safe default."
                )
            from lup.adapters.codex_background import CodexBackgroundAgent

            return CodexBackgroundAgent(
                name=name,
                system_prompt=system_prompt,
                build_message=build_message,
                start_message=start_message,
                model=model,
                debounce_seconds=debounce_seconds,
                on_response=on_response,
            )
        case _:
            raise ValueError(f"Unknown SDK: {sdk}")
