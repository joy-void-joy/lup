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

Contract and scaffolding are separate objects, composed at construction:
:class:`BackgroundDriver` is the per-engine verb — drive turns against
the SDK from a message stream — and :class:`BackgroundAgent` is the
concrete agent consumers hold, owning the SDK-free wake/debounce
machinery and running a driver instance over its own stream.

See ``src/lup_template/agent/tools/realtime.py`` for example integration
with the persistent agent pattern (observer example).

Dispatch is the engine's: each :class:`~lup.adapters.Engine.Engine`
builds its driver from a :class:`BackgroundAgentParams` and composes it
into a :class:`BackgroundAgent`, owning the validation and defaults that
are properties of its backend (Codex rejects tools and requires an
explicit model; Claude defaults to an opus-class model and can act
through tools).

Examples:
    Create an observer that maintains conversation notes::

        >>> from lup.adapters.background.Background import BackgroundAgentParams
        >>> from lup.adapters.wiring import resolve_engine
        >>> notes: list[str] = []
        >>> agent = resolve_engine(engine_id).background(
        ...     BackgroundAgentParams(
        ...         name="observer",
        ...         system_prompt="Summarize conversations...",
        ...         tools=create_observer_tools(notes=notes),
        ...         build_message=build_observer_message,
        ...         allowed_tools=["mcp__observer__notes"],
        ...     )
        ... )
        >>> agent.start()
        >>> agent.wake()  # signal new data
        >>> await agent.stop()
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Callable

from pydantic import BaseModel

from lup.mcp import LupMcpTool


class BackgroundDriver(ABC):
    """The per-engine verb: drive turns against the SDK from a message stream.

    Implementations carry their own SDK state and identity (name, model,
    tools); :class:`BackgroundAgent` composes one over its debounced
    stream. A driver supervises itself: it logs a crash rather than
    letting it propagate into (or kill) the main session.
    """

    @abstractmethod
    async def run(self, messages: AsyncIterator[str]) -> None:
        """Consume turn messages, driving the SDK until cancelled."""


class BackgroundAgent:
    """The background agent consumers hold: wake machinery composing a driver.

    Owns the asyncio task, the wake event, and the debounced turn stream —
    all SDK-free — and runs the engine's :class:`BackgroundDriver` over
    that stream. :meth:`start` launches the task, :meth:`wake` signals new
    data, :meth:`stop` cancels and waits for cleanup.
    """

    def __init__(
        self,
        driver: BackgroundDriver,
        *,
        name: str,
        build_message: Callable[[], str | None],
        start_message: str = "",
        debounce_seconds: float = 3.0,
    ) -> None:
        self.driver = driver
        self.build_message = build_message
        self.start_message = start_message or f"[{name} started]"
        self.debounce_seconds = debounce_seconds

        self.runner: asyncio.Task[None] | None = None
        self.wake_event: asyncio.Event = asyncio.Event()
        self.running = False

    def start(self) -> None:
        """Run the driver over the debounced stream as an asyncio task."""
        if self.runner and not self.runner.done():
            return
        self.running = True
        self.runner = asyncio.create_task(self.driver.run(self.message_stream()))

    def wake(self) -> None:
        """Signal that new data is available for processing."""
        self.wake_event.set()

    async def stop(self) -> None:
        """Cancel the driver task and wait for cleanup."""
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
        (``None`` means nothing to say — keep waiting). The driver
        consumes this stream and speaks its own wire format.
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
