"""The event loop a promise's runs are made on: what runs next is chosen, and time is a number.

asyncio's own loop runs what's ready in the order it became ready, and waits on
the machine's clock for its timers, so a run depends on how loaded the machine
is. This loop keeps what's ready and the timers itself: wherever more than one
thing could run next, it asks whoever runs it which (hypothesis, in the gate),
and when nothing is ready it moves its clock to the next timer at once, so an
hour's `asyncio.sleep` passes instantly. Its first choice is always asyncio's
own (first ready, first run, a timer when nothing else can), so a run shrinks
towards what asyncio would do anyway (`lup/testing/README.md`, *Invariants*).

It runs no I/O and starts no process: what a promise runs is lup in this
process, through its doors. Work handed to a thread (`asyncio.to_thread`), as
code moving blocking file work off the loop does, runs as a task of this loop,
in its thread, taking no time on its clock.
"""

import asyncio
import heapq
from asyncio import events
from typing import TYPE_CHECKING, override

from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from concurrent.futures import Executor
    from contextvars import Context


class StuckError(LupError):
    """A run can't go on: every task in it waits on something nothing will do, or it ran past its ceiling of slices."""


class Failure(Model, arbitrary_types_allowed=True):
    """What asyncio tells its loop of an error it found nobody to raise to."""

    message: str = ""
    exception: BaseException | None = None
    handle: asyncio.Handle | None = None
    """The handle whose callback raised it, where one did: a slice that
    failed, rather than a task's error nobody collected."""


class Simulation(asyncio.AbstractEventLoop):
    """An event loop whose order and time are chosen: what's ready runs in the order `choose` picks, and its clock moves only to the next timer.

    Before each slice it runs, it calls `watch` with the handle about to run,
    and after it, what `watch` returned: how the harness checks every invariant over
    every slice of a call.
    """

    def __init__(
        self,
        choose: Callable[[int], int],
        watch: Callable[[asyncio.Handle], Callable[[], None] | None],
        *,
        ceiling: int = 100_000,
    ) -> None:
        """Run what's ready in the order `choose` picks among as many choices as it's given, watching each slice with `watch`, for `ceiling` slices at most."""
        self.choose = choose
        self.watch = watch
        self.ceiling = ceiling
        self.ready: list[asyncio.Handle] = []
        self.timers: list[asyncio.TimerHandle] = []
        self.now = 0.0
        self.running = False
        self.closed = False
        self.failed: Failure | None = None

    @override
    def time(self) -> float:
        """Return the loop's clock: seconds since it started, moved only by its timers."""
        return self.now

    @override
    def call_soon[*A, R](
        self,
        callback: Callable[[*A], R],
        *args: *A,
        context: Context | None = None,
    ) -> asyncio.Handle:
        """Make `callback` ready to run."""
        handle = asyncio.Handle(callback, args, self, context)
        self.ready.append(handle)
        return handle

    @override
    def call_at[*A, R](
        self,
        when: float,
        callback: Callable[[*A], R],
        *args: *A,
        context: Context | None = None,
    ) -> asyncio.TimerHandle:
        """Run `callback` once the clock reaches `when`."""
        handle = asyncio.TimerHandle(when, callback, args, self, context)
        heapq.heappush(self.timers, handle)
        return handle

    @override
    def call_later[*A, R](
        self,
        delay: float,
        callback: Callable[[*A], R],
        *args: *A,
        context: Context | None = None,
    ) -> asyncio.TimerHandle:
        """Run `callback` once the clock has moved `delay` seconds on."""
        return self.call_at(self.now + delay, callback, *args, context=context)

    # lup: ignore("private-name", why="asyncio's `TimerHandle.cancel` calls this name on its loop, which every loop answers")
    def _timer_handle_cancelled(self, handle: asyncio.TimerHandle) -> None:
        """Leave a cancelled timer where it is: it's skipped when it comes up."""

    @override
    def create_future(self) -> asyncio.Future[None]:
        """Return a future of this loop."""
        return asyncio.Future(loop=self)

    @override
    def create_task[T](
        self,
        coro: Coroutine[None, None, T],
        *,
        name: str | None = None,
        context: Context | None = None,
        eager_start: bool | None = None,
    ) -> asyncio.Task[T]:
        """Return a task of this loop running `coro`."""
        return asyncio.Task(
            coro, loop=self, name=name, context=context, eager_start=bool(eager_start)
        )

    @override
    def run_in_executor[*A, R](
        self,
        executor: Executor | None,
        func: Callable[[*A], R],
        *args: *A,
    ) -> asyncio.Future[R]:
        """Run `func` in this thread, as a task of this loop, which gives what it gives and raises what it raises where it's awaited: a thread's work, as `asyncio.to_thread` hands it, is a slice of its own, taking no time on this loop's clock."""
        del executor

        async def worked() -> R:
            return func(*args)

        return self.create_task(worked())

    @override
    def get_debug(self) -> bool:
        """Say it isn't in asyncio's debug mode."""
        return False

    @override
    def is_running(self) -> bool:
        """Say whether it's running a run."""
        return self.running

    @override
    def is_closed(self) -> bool:
        """Say whether it's closed."""
        return self.closed

    @override
    def close(self) -> None:
        """Close it."""
        self.closed = True

    @override
    # lup: ignore("bare-object", why="asyncio's error context holds anything it found: an exception, a message, a task")
    def call_exception_handler(self, context: dict[str, object]) -> None:
        """Keep an error a slice raised, which fails the run once the slice ends; leave one a task's left nobody to collect, which its run's outcome already says."""
        failure = Failure.model_validate(context)
        if failure.handle is not None:
            self.failed = self.failed or failure

    @override
    # lup: ignore("bare-object", why="asyncio's error context holds anything it found: an exception, a message, a task")
    def default_exception_handler(self, context: dict[str, object]) -> None:
        """Handle an error as `call_exception_handler` does."""
        self.call_exception_handler(context)

    @override
    def run_until_complete[T](self, future: Awaitable[T]) -> T:
        """Run until `future` is done, and return what it gives; however it ends, every task it left is cancelled.

        Raise `StuckError` where nothing can run and it isn't done, or past the
        ceiling of slices.
        """
        task = asyncio.ensure_future(future, loop=self)
        # lup: ignore("SLF001", why="asyncio names the loop that's running with this, which it exports for a loop of another kind to call, as this one is")
        before = events._get_running_loop()
        # lup: ignore("SLF001", why="asyncio names the loop that's running with this, which it exports for a loop of another kind to call, as this one is")
        events._set_running_loop(self)
        self.running = True
        try:
            slices = 0
            while not task.done():
                if slices >= self.ceiling:
                    message = f"the run didn't end within {self.ceiling} slices"
                    raise StuckError(message)
                self.slice()
                slices += 1
        finally:
            self.drained()
            # lup: ignore("SLF001", why="asyncio names the loop that's running with this, which it exports for a loop of another kind to call, as this one is")
            events._set_running_loop(before)
            self.running = False
        return task.result()

    def slice(self) -> None:
        """Run one thing: what `choose` picks among what's ready, or the next timer, its clock moved there.

        The last choice, where a timer waits, is the timer, as though what's
        ready took that long; with nothing ready, it's the only one.
        """
        self.timers = [each for each in self.timers if not each.cancelled()]
        heapq.heapify(self.timers)
        choices = len(self.ready) + (1 if self.timers else 0)
        if choices == 0:
            message = (
                "the run can't go on: every task waits on something nothing will do"
            )
            raise StuckError(message)
        chosen = self.choose(choices) if choices > 1 else 0
        if chosen < len(self.ready):
            handle = self.ready.pop(chosen)
        else:
            handle = heapq.heappop(self.timers)
            self.now = max(self.now, handle.when())
        if handle.cancelled():
            return
        watched = self.watch(handle)
        # lup: ignore("SLF001", why="a handle is run by its loop through this, as asyncio's own loops run theirs")
        handle._run()
        if watched is not None:
            watched()
        failed, self.failed = self.failed, None
        if failed is not None:
            if failed.exception is not None:
                raise failed.exception
            raise StuckError(failed.message)

    def drained(self) -> None:
        """Cancel every task the run left, and run what that makes ready, unwatched, so nothing it started is left unfinished."""
        for task in asyncio.all_tasks(self):
            task.cancel()
        slices = 0
        while self.ready and slices < self.ceiling:
            handle = self.ready.pop(0)
            if not handle.cancelled():
                # lup: ignore("SLF001", why="a handle is run by its loop through this, as asyncio's own loops run theirs")
                handle._run()
            slices += 1
        self.failed = None
