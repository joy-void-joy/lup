"""One run lease across execution and bounded waits for its host."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from lup.channels.models import publish_atomic, utc_now
from lup.resolver.contracts import ResolverEnvironmentFault
from lup.resolver.state import ResolverStateRepository


class HostWait(BaseModel, frozen=True):
    """Why a live driver is waiting, and when it will try the host again."""

    cause: str
    retry_at: datetime
    mode: Literal["retry", "credential-probe"] = "retry"


class HostWaitStore:
    """The driver's current wait; meaningful as live only while its lease is held."""

    def __init__(self, root: Path) -> None:
        self.path = root / "host-wait.json"

    def read(self) -> HostWait | None:
        try:
            return HostWait.model_validate_json(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return None

    def publish(self, wait: HostWait) -> None:
        publish_atomic(self.path, wait)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


async def drive_with_host_retries(
    drive: Callable[[], Awaitable[None]],
    repository: ResolverStateRepository,
    *,
    retries: int,
    retry_delay: Callable[[int], float | None],
    auth_probe_delay: float,
    needs_a_person: Callable[[str], bool],
    may_be_a_rotation: Callable[[str], bool],
    announce: Callable[[HostWait], None],
) -> None:
    """Drive through transient host refusals without releasing run ownership.

    ``drive`` uses the core's already-exclusive operations. This lease covers
    every retry and sleep, so status and competing mutations agree about who
    owns the run even when no actor turn is advancing.
    """
    waiting = HostWaitStore(repository.root)
    with repository.exclusive():
        waiting.clear()
        probed: str | None = None
        try:
            for attempt in range(retries + 1):
                try:
                    await drive()
                    return
                except ResolverEnvironmentFault as fault:
                    human = needs_a_person(fault.cause)
                    if human:
                        if probed == fault.cause or not may_be_a_rotation(fault.cause):
                            raise
                        probed = fault.cause
                        delay = auth_probe_delay
                    else:
                        probed = None
                        delay = retry_delay(attempt)
                        if delay is None:
                            raise
                    if attempt == retries:
                        raise
                    wait = HostWait(
                        cause=fault.cause,
                        retry_at=utc_now() + timedelta(seconds=delay),
                        mode="credential-probe" if human else "retry",
                    )
                    waiting.publish(wait)
                    announce(wait)
                    await asyncio.sleep(delay)
                    waiting.clear()
        finally:
            waiting.clear()
