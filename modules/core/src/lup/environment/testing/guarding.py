"""The gate's guard on how long a check takes, measured so that no verdict depends on how loaded the machine is: by whether anything in it runs, and by the processor's time it takes, never by the clock alone.

A check's verdict is its tree's alone (`lup/testing/README.md`, *Checking*). A
loaded machine makes a check take longer by the clock, but barely changes the
processor's time it takes, and never stops it running. So the guard:
- fails a check in which nothing has run for `Limits.stalled`: a call that
  blocks on a lock nothing releases, or a program that never ends;
- fails a check that has taken more of the processor's time than
  `Limits.ceiling`, as a search too big for a promise;
- flags a check that took more than `Limits.slow`, which passes still, so it's
  fixed rather than blocking anyone.

A check it fails is raised `HaltedError` in the main thread, woken by a signal
from where it blocks, so it fails at the line it's stuck on. Where that doesn't
end it, as with a thread that never wakes, the guard writes every thread's
stack and ends the process, which a run on several workers reports as the check
that crashed its worker. It guards the run's end the same way, since a thread
left stuck holds the process there.
"""

import faulthandler
import os
import signal
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import Field

from lup.types import Model, MutableModel

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import FrameType


# lup: ignore("error-root", why="a halted check must get past hypothesis, which takes every `Exception` for a broken promise and would run the halted check again to shrink it")
class HaltedError(BaseException):
    """A check the gate's guard halted: nothing in it ran for as long as it allows, or it took more of the processor's time than its ceiling."""

    def __init__(self, why: str, where: str) -> None:
        """Say why the check was halted, and where each thread was."""
        super().__init__(f"{why}. Where each thread was:\n{where}")
        self.why = why
        """Why it was halted, in a line."""


class Limits(Model):
    """How long a check may take, by whether anything in it runs and by the processor's time, neither of which a loaded machine changes much."""

    stalled: timedelta = timedelta(seconds=30)
    """How long a check may go with nothing in it running before it fails as
    stuck, and how long a check halted has to end before the process is."""
    slow: timedelta = timedelta(seconds=15)
    """How much of the processor's time a check may take before it's flagged
    to fix, passing still."""
    ceiling: timedelta = timedelta(seconds=120)
    """How much of the processor's time a check may take before it fails as
    too slow."""
    watching: timedelta = timedelta(seconds=1)
    """How often the guard looks at the processor's time a check has taken."""


class Guard(MutableModel, arbitrary_types_allowed=True):
    """What guards one process's checks: each check, and each slice a run of it runs, tells it so, and a thread of its own watches each check against its `limits`."""

    limits: Limits = Limits()
    waking: signal.Signals = signal.SIGUSR1
    """The signal that wakes the main thread to raise a halt there."""
    checking: str | None = None
    """The check it guards, by its name; none between checks."""
    beaten: float = 0.0
    """When something last ran in the check, by the monotonic clock."""
    began: float = 0.0
    """The process's time on the processor as the check began."""
    raised: float | None = None
    """When the check's halt was raised in the main thread, by the monotonic
    clock; none before."""
    why: str = ""
    """Why the check was halted, which its error says."""
    where: str = ""
    """Where each thread was as the check was halted, which its error says."""
    output: int | None = None
    """Where every thread's stack is written before the process ends: standard
    error as the guard started, opened apart from what captures it."""
    wakes: bool = False
    """Whether it can raise a halt in the main thread, which needs its signal
    handled there."""
    stopping: threading.Event = Field(default_factory=threading.Event)

    def started(self) -> None:
        """Start watching, from the main thread where it's called there, so a halt can be raised in it."""
        stream = sys.__stderr__
        self.output = None if stream is None else os.dup(stream.fileno())
        self.wakes = threading.current_thread() is threading.main_thread()
        if self.wakes:
            signal.signal(self.waking, self.woken)
        threading.Thread(target=self.watched, name="lup-guard", daemon=True).start()

    @contextmanager
    def guarding(self, name: str) -> Generator[None]:
        """Guard the check named `name` while it runs."""
        self.checking = name
        self.raised = None
        self.began = time.process_time()
        self.beat()
        try:
            yield
        finally:
            self.checking = None

    def beat(self) -> None:
        """Say something ran in the check it guards."""
        self.beaten = time.monotonic()

    def taken(self) -> timedelta:
        """Return how much of the processor's time the check it guards has taken so far."""
        return timedelta(seconds=time.process_time() - self.began)

    def paused(self) -> None:
        """Stop guarding the check that's running, as where a debugger takes over."""
        self.checking = None

    def ending(self) -> None:
        """Guard the run's end, which a thread left stuck holds: past `Limits.stalled`, the process is ended."""
        self.checking = "the run's end"
        self.raised = time.monotonic()

    def watched(self) -> None:
        """Watch each check until the process ends: raise its halt in the main thread where it's stuck or too slow, then end the process where that doesn't end the check."""
        while not self.stopping.wait(self.limits.watching.total_seconds()):
            if self.checking is None:
                continue
            now = time.monotonic()
            if self.raised is not None:
                if now - self.raised >= self.limits.stalled.total_seconds():
                    self.ended()
                continue
            why = self.overdue(timedelta(seconds=now - self.beaten), self.taken())
            if why is not None:
                self.halt(why)

    def overdue(self, idle: timedelta, taken: timedelta) -> str | None:
        """Say why the check it guards is to be halted, having run nothing for `idle` and taken `taken` of the processor's time; none where it's within its limits."""
        if idle >= self.limits.stalled:
            return (
                f"it went {seconds(self.limits.stalled)} without a run of it moving "
                "on from one `await` to the next: stuck, or spinning in one place"
            )
        if taken >= self.limits.ceiling:
            return (
                f"it took {seconds(taken)} of the processor's time, past the "
                f"ceiling of {seconds(self.limits.ceiling)}: a search too big for "
                "a promise"
            )
        return None

    def halt(self, why: str) -> None:
        """Halt the check it guards, saying why: raised in the main thread where a signal wakes it, else the process ended."""
        self.why = f"`{self.checking}` halted: {why}"
        self.where = stacks()
        self.raised = time.monotonic()
        if not self.wakes:
            self.ended()
            return
        signal.pthread_kill(threading.main_thread().ident or 0, self.waking)

    def woken(self, signum: int, frame: FrameType | None) -> None:
        """Raise the check's halt in the main thread, where its signal wakes what blocks."""
        del signum, frame
        if self.checking is None:
            return
        raise HaltedError(self.why, self.where)

    def ended(self) -> None:
        """Write every thread's stack, saying which check was halted, and end the process."""
        if self.output is not None:
            said = (
                f"\n`{self.checking}` was halted and didn't end within "
                f"{seconds(self.limits.stalled)}; every thread's stack follows, and "
                "the process ends.\n"
            )
            os.write(self.output, said.encode())
            faulthandler.dump_traceback(file=self.output, all_threads=True)
        os._exit(1)


def seconds(duration: timedelta) -> str:
    """Say a duration in seconds, as a report does.

    >>> seconds(timedelta(seconds=30)), seconds(timedelta(seconds=12.345))
    ('30 s', '12.3 s')
    """
    return f"{duration.total_seconds():.3g} s"


def stacks() -> str:
    """Return every thread's stack, as `faulthandler` writes it: the innermost call first, each with its file and line."""
    with tempfile.TemporaryFile() as written:
        faulthandler.dump_traceback(file=written.fileno(), all_threads=True)
        written.seek(0)
        return written.read().decode(errors="replace")
