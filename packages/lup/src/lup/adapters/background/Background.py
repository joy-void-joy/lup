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
composition, not inheritance:
:class:`~lup.adapters.background.wakeloop.WakeLoop` is the concrete
turn-driving machinery every engine shares, and :class:`BaseBackgroundAgent`
is the pure per-engine contract (identity plus the abstract ``run_loop``)
that holds a wake loop rather than subclassing one.

See ``src/lup_template/agent/tools/realtime.py`` for example integration
with the persistent agent pattern (observer example).

Dispatch is the engine's: each :class:`~lup.adapters.Engine.Engine`
builds its own background agent from a :class:`BackgroundAgentParams`,
owning the validation and defaults that are properties of its backend
(Codex rejects tools and requires an explicit model; Claude defaults to
an opus-class model and can act through tools).

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

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable

from pydantic import BaseModel

from lup.adapters.background.wakeloop import WakeLoop
from lup.mcp import LupMcpTool


# lup: There's really a problem in this ABC spec. Reread tacocast again: Either a class is purely ABC and has a simple run/... method to implement, or ir has scaffolding that uses one such ABC as an inner component. Never both at the same time.
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
