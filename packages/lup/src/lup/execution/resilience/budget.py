"""A request budget per key, summed across every process that shares a directory.

A :class:`~lup.execution.resilience.throttle.Throttle` spaces the requests of
one event loop. Three sessions in three worktrees each keeping to a polite
rate is still three times the rate the operator sees, and the repository this
grew out of got a host to block it exactly that way — so the budget an
operator is owed has to be counted where every session of one repository
meets, which is the shared git directory :mod:`lup.coordination` already
keeps its roster under.

**One file per key, holding the moments of the requests still inside the
window.** A reservation reads the file under an exclusive lock, drops the
moments older than the window, and either appends its own and returns, or
reports how long until the oldest leaves the window and the caller sleeps
and asks again. The lock is held for the read and the write and never across
the sleep, so a waiting process delays nobody else's reservation. The file
is JSON and never truncated below what the window holds, so a process that
crashes mid-request has still been counted, which is the safe direction.

The key is the caller's — a host, a queue, an account — and the budget is
per key rather than per file, so two keys never contend.
"""

import asyncio
import fcntl
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter

type Clock = Callable[[], float]
"""Seconds since the epoch, as the budget's window is cut against."""


def utc_seconds() -> float:
    return datetime.now(UTC).timestamp()


class Reservation(BaseModel, frozen=True):
    """One attempt to take a slot: taken now, or how long until one frees."""

    taken: bool
    wait_seconds: float = Field(ge=0)
    inside: int = Field(ge=0)
    """How many requests the window held after this attempt, this one included where taken."""


class SharedBudget:
    """Requests per window per key, counted across every process sharing ``directory``."""

    def __init__(
        self, directory: Path, window_seconds: float = 60.0, clock: Clock = utc_seconds
    ) -> None:
        self.directory = directory
        self.window_seconds = window_seconds
        self.clock = clock

    def path(self, key: str) -> Path:
        """Where one key's window is kept; the key is spelled safely as a file name."""
        safe = "".join(char if char.isalnum() or char in "-._" else "_" for char in key)
        return self.directory / f"{safe or 'default'}.json"

    def reserve(self, key: str, per_window: int) -> Reservation:
        """Take one slot for ``key`` if the window has room, under the shared lock.

        Read, prune and append in one locked pass, because two processes that
        each read a window with one slot left would both take it. A budget of
        zero never has room, so a caller that reserves against a closed key
        is told to wait a whole window, which is the honest answer to a
        request that must not go out at all.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        moments = TypeAdapter(list[float])
        now = self.clock()

        def decided(inside: list[float]) -> Reservation:
            """Take the slot where the window has room, else say how long until it has."""
            if per_window <= 0:
                return Reservation(
                    taken=False, wait_seconds=self.window_seconds, inside=len(inside)
                )
            if len(inside) < per_window:
                inside.append(now)
                return Reservation(taken=True, wait_seconds=0.0, inside=len(inside))
            return Reservation(
                taken=False,
                wait_seconds=max(inside[0] + self.window_seconds - now, 0.0),
                inside=len(inside),
            )

        with self.path(key).open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                content = handle.read()
                held = moments.validate_json(content) if content.strip() else []
                inside = sorted(
                    moment for moment in held if now - moment < self.window_seconds
                )
                reservation = decided(inside)
                handle.seek(0)
                handle.truncate()
                handle.write(json.dumps(inside))
                handle.write("\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return reservation

    def inside(self, key: str) -> int:
        """How many requests the window currently holds for ``key``, without taking one."""
        moments = TypeAdapter(list[float])
        try:
            content = self.path(key).read_text(encoding="utf-8")
        except OSError:
            return 0
        held = moments.validate_json(content) if content.strip() else []
        now = self.clock()
        return sum(1 for moment in held if now - moment < self.window_seconds)

    @asynccontextmanager
    async def slot(self, key: str, per_window: int) -> AsyncGenerator[Reservation]:
        """Hold the body until the window has room for one more request under ``key``.

        Sleeps outside the lock for as long as the reservation said, then asks
        again, because the window may have been taken by another process in
        the meantime and a slot promised is not a slot held.
        """
        while True:
            reservation = self.reserve(key, per_window)
            if reservation.taken:
                break
            await asyncio.sleep(reservation.wait_seconds)
        yield reservation
