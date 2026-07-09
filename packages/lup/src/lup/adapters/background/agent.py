"""The composing background agent: SDK-free wake/debounce scaffolding.

:class:`BackgroundAgent` is the concrete agent consumers hold. It owns
the asyncio task, the wake event, and the debounced turn stream, and
runs an engine's
:class:`~lup.adapters.background.BackgroundDriver.BackgroundDriver` over
that stream. Engines build one from a
:class:`~lup.adapters.background.params.BackgroundAgentParams` in
``Engine.background``.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable

from lup.adapters.background.BackgroundDriver import BackgroundDriver


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
