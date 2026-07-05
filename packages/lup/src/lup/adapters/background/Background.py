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
1. Create a background agent with tools and a ``build_message`` callback
2. Start it — it runs as an asyncio task until stopped
3. Wake it when new data is available
4. It processes data via tool calls that write to shared state
5. The main agent reads results through its own tools

The wake/debounce machinery and the per-engine contract are split by
composition, not inheritance: :class:`WakeLoop` is the concrete
turn-driving machinery every engine shares, and :class:`BaseBackgroundAgent`
is the pure per-engine contract (identity plus the abstract ``run_loop``)
that holds a :class:`WakeLoop` rather than subclassing one.

See ``src/lup_template/agent/tools/realtime.py`` for example integration
with the persistent agent pattern (observer example).

Examples:
    Create an observer that maintains conversation notes::

        >>> from lup.adapters.background.Background import create_background_agent
        >>> notes: list[str] = []
        >>> agent = create_background_agent(
        ...     engine_id,  # a shipped engine id or an Engine instance
        ...     name="observer",
        ...     system_prompt="Summarize conversations...",
        ...     tools=create_observer_tools(notes=notes),
        ...     build_message=build_observer_message,
        ...     allowed_tools=["mcp__observer__notes"],
        ... )
        >>> agent.start()
        >>> agent.wake()  # signal new data
        >>> await agent.stop()
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable, Coroutine

from pydantic import BaseModel

from lup.mcp import LupMcpTool

logger = logging.getLogger(__name__)


class WakeLoop:
    """The concrete wake/debounce/message-stream machinery.

    Composed into each engine's background agent rather than inherited: it
    owns the asyncio task, the wake event, and the debounced turn stream,
    and knows nothing about any SDK. The agent supplies its own
    ``run_loop`` coroutine to :meth:`start`.
    """

    def __init__(
        self,
        *,
        name: str,
        build_message: Callable[[], str | None],
        start_message: str,
        debounce_seconds: float,
    ) -> None:
        self.name = name
        self.build_message = build_message
        self.start_message = start_message or f"[{name} started]"
        self.debounce_seconds = debounce_seconds

        self.runner: asyncio.Task[None] | None = None
        self.wake_event: asyncio.Event = asyncio.Event()
        self.running = False

    def start(self, run_loop: Callable[[], Coroutine[object, object, None]]) -> None:
        """Start the agent's run loop as an asyncio task."""
        if self.runner and not self.runner.done():
            return
        self.running = True
        self.runner = asyncio.create_task(run_loop())

    def wake(self) -> None:
        """Signal that new data is available for processing."""
        self.wake_event.set()

    async def stop(self) -> None:
        """Cancel the run loop and wait for cleanup."""
        self.running = False
        if self.runner and not self.runner.done():
            self.runner.cancel()
            try:
                await self.runner
            except asyncio.CancelledError:
                pass
        self.runner = None

    async def message_stream(self) -> AsyncGenerator[str, None]:
        """Yield the start message, then one message per debounced wake.

        Block until :meth:`wake` fires, absorb rapid wakes for
        ``debounce_seconds``, then ask ``build_message`` for the turn
        (``None`` means nothing to say — keep waiting). Engine run loops
        consume this stream and speak their own wire format.
        """
        yield self.start_message

        while self.running:
            await self.wake_event.wait()
            self.wake_event.clear()

            while True:
                try:
                    await asyncio.wait_for(
                        self.wake_event.wait(), timeout=self.debounce_seconds
                    )
                    self.wake_event.clear()
                except TimeoutError:
                    break

            content = self.build_message()
            if content is None:
                continue

            yield content


class BaseBackgroundAgent(ABC):
    """The per-engine background contract: identity plus a run loop.

    Holds a :class:`WakeLoop` for the shared machinery (composition) and
    adds only :meth:`run_loop` — the SDK-specific turn driver each engine
    implements. ``start``/``wake``/``stop``/``message_stream`` delegate to
    the loop.
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
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.loop = WakeLoop(
            name=name,
            build_message=build_message,
            start_message=start_message,
            debounce_seconds=debounce_seconds,
        )

    def start(self) -> None:
        """Start the background agent's run loop."""
        self.loop.start(self.run_loop)

    def wake(self) -> None:
        """Signal that new data is available."""
        self.loop.wake()

    async def stop(self) -> None:
        """Cancel the background agent and wait for cleanup."""
        await self.loop.stop()

    def message_stream(self) -> AsyncGenerator[str, None]:
        """The debounced turn stream the engine run loop consumes."""
        return self.loop.message_stream()

    @abstractmethod
    async def run_loop(self) -> None:
        """SDK-specific run loop. Implemented by each engine's agent."""


class BackgroundAgentParams(BaseModel):
    """The request a background-agent builder receives, before engine dispatch."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    system_prompt: str
    build_message: Callable[[], str | None]
    start_message: str = ""
    model: str | None = None
    debounce_seconds: float = 3.0
    tools: list[LupMcpTool] | None = None
    builtin_tools: list[str] | None = None
    allowed_tools: list[str] | None = None
    on_response: Callable[[object], None] | None = None


type BackgroundFactory = Callable[[BackgroundAgentParams], BaseBackgroundAgent]
"""One engine's background builder: params in, a configured agent out."""


def claude_background(params: BackgroundAgentParams) -> BaseBackgroundAgent:
    from lup.adapters.background.claude import build_claude_background

    return build_claude_background(params)


def codex_background(params: BackgroundAgentParams) -> BaseBackgroundAgent:
    from lup.adapters.background.codex import build_codex_background

    return build_codex_background(params)


BACKGROUNDS: dict[str, BackgroundFactory] = {
    "claude": claude_background,
    "claude-compat": claude_background,
    "codex": codex_background,
    "openai-compat": codex_background,
}
"""Engine id → background builder. The compat engines share their base
engine's background (Claude scaffolding or the Codex runtime); engines
absent here have no background support."""


def create_background_agent(
    engine: str,
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
    """Build the engine's background agent.

    Delegates to the engine's :data:`BACKGROUNDS` builder — each owns the
    validation and defaults that are properties of its backend (Codex
    rejects tools and requires an explicit model; Claude defaults to an
    opus-class model and can act through tools).

    Args:
        engine: A shipped engine id or an ``Engine`` instance.
        name: Agent identifier.
        system_prompt: System prompt for the background agent.
        build_message: Callable that returns the next message or None.
        start_message: Initial message when agent starts.
        model: Model override (defaults vary by engine).
        debounce_seconds: Batch rapid wakes.
        tools: LupMcpTool instances (tool-capable engines only).
        builtin_tools: Built-in SDK tools (tool-capable engines only).
        allowed_tools: Tool allowlist (tool-capable engines only).
        on_response: Callback for responses.
    """
    try:
        factory = BACKGROUNDS[engine]
    except KeyError:
        raise ValueError(
            f"Unknown engine {engine!r}. Background agents run on: "
            f"{', '.join(BACKGROUNDS)}."
        ) from None

    return factory(
        BackgroundAgentParams(
            name=name,
            system_prompt=system_prompt,
            build_message=build_message,
            start_message=start_message,
            model=model,
            debounce_seconds=debounce_seconds,
            tools=tools,
            builtin_tools=builtin_tools,
            allowed_tools=allowed_tools,
            on_response=on_response,
        )
    )
