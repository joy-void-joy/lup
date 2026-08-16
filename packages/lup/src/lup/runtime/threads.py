"""Async access to blocking callables without loop-owned executor shutdown.

:func:`asyncio.to_thread` hands work to the running loop's *default* executor,
which the loop shuts down as it closes. A blocking call still outstanding at
that moment — a native process being waited on while the session tears down —
outlives the executor meant to be running it, and the awaiting task never
resolves. The executor here belongs to the process instead, so a call already
in flight is unaffected by any one loop ending.

Awaiting the executor future directly would re-attach the wait to that loop, so
the future is polled instead: the awaiting task stays on ordinary sleeps, which
remain cancellable and carry no claim on the loop's own executor.
"""

import asyncio
import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

THREAD_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="lup")
THREAD_WAKE_INTERVAL_SECONDS = 0.01


async def run_sync[**P, R](
    function: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Run blocking work with context propagation on Lup's shared executor.

    The caller's :mod:`contextvars` context is copied into the worker thread,
    so anything the call reads from context — a trace's current span, a
    session identifier — resolves to what the awaiting side had.
    """
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = partial(context.run, function, *args, **kwargs)
    future = loop.run_in_executor(THREAD_EXECUTOR, call)
    while not future.done():
        await asyncio.sleep(THREAD_WAKE_INTERVAL_SECONDS)
    return future.result()
