"""The concrete wake/debounce/message-stream machinery for backgrounds.

Composed into each engine's background agent rather than inherited (see
:class:`~lup.adapters.background.Background.BaseBackgroundAgent`): the
loop owns the asyncio task, the wake event, and the debounced turn
stream, and knows nothing about any SDK.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine


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
