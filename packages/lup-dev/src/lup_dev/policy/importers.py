"""The background pass re-checking the files that import what a checkpoint accepted.

The rules read only the changed files, so their findings come at the edit; the
files importing them are re-checked for type errors in the background, and their
errors arrive at the next checkpoint (`docs/judging-writes.md`, *The engine*,
question 5). One pass at a time per worktree, and the turn's end waits for it, so
no type error surfaces after the session.
"""

import sys
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import sh
from filelock import FileLock, Timeout

from lup.types import Model, MutableModel
from lup_dev.codescan.contract import Checker, FileReport
from lup_dev.layout import StoreLayout
from lup_dev.policy.store import read_model, write_model

if TYPE_CHECKING:
    from lup_dev.clock import Clock


class Spawner(ABC):
    """Starts the background importers pass of a worktree."""

    @abstractmethod
    def spawn(self, worktree: Path, log: Path) -> None:
        """Start the pass for the worktree at `worktree`, printing to `log`."""


class BackgroundSpawner(Spawner):
    """Starts the pass as its own process, detached from the hook that asks for it."""

    @override
    def spawn(self, worktree: Path, log: Path) -> None:
        log.parent.mkdir(parents=True, exist_ok=True)
        sh.Command(sys.executable)(
            "-m",
            "lup_dev.cli",
            "importers",
            str(worktree),
            _bg=True,
            _bg_exc=False,
            _new_session=True,
            _out=str(log),
            _err=str(log),
        )


class ImportersState(MutableModel):
    """What the background importers pass has left to do, and what it found."""

    pending: list[Path] = []
    """Files changed since the pass took its last batch."""
    found: list[FileReport] = []
    """What the pass found, waiting for the next checkpoint."""


class ImportersPass(Model):
    """One worktree's background pass re-checking the files importing what changed.

    One pass at a time. The pass holds a lock for its whole life, which the system
    frees however the process ends; a change while it runs adds to what it does
    next. It stops only once nothing is pending, releasing its lock before the
    state's, so a request never finds it gone with work left behind.
    """

    layout: StoreLayout
    root: Path

    def guard(self) -> FileLock:
        """Return the lock guarding the pass's state."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.layout.importers_lock)

    def runner(self) -> FileLock:
        """Return the lock a running pass holds."""
        self.layout.home.mkdir(parents=True, exist_ok=True)
        return FileLock(self.layout.importers_run, timeout=0)

    def state(self) -> ImportersState:
        """Read the pass's state; hold its guard."""
        return read_model(self.layout.importers, ImportersState) or ImportersState()

    def running(self) -> bool:
        """Say whether a pass is running: whether its lock is held."""
        probe = self.runner()
        try:
            probe.acquire()
        except Timeout:
            return True
        probe.release()
        return False

    def request(self, changed: list[Path], spawner: Spawner) -> None:
        """Ask for the files importing `changed` to be re-checked.

        Starts a pass unless one runs; one that runs takes these next.
        """
        if not changed:
            return
        with self.guard():
            state = self.state()
            state.pending = list(dict.fromkeys([*state.pending, *changed]))
            write_model(self.layout.importers, state)
            if self.running():
                return
        spawner.spawn(self.root, self.layout.importers_log)

    def run(self, checker: Checker) -> None:
        """Run the pass until nothing is pending; return at once if another runs."""
        runner = self.runner()
        try:
            runner.acquire()
        except Timeout:
            return
        try:
            while self.step(checker, runner):
                pass
        finally:
            if runner.is_locked:
                runner.release()

    def step(self, checker: Checker, runner: FileLock) -> bool:
        """Re-check one batch; say whether to look for another."""
        with self.guard():
            state = self.state()
            batch = state.pending
            if not batch:
                runner.release()
                return False
            state.pending = []
            write_model(self.layout.importers, state)
        found = checker.importers(self.root, batch)
        with self.guard():
            state = self.state()
            state.found = [*state.found, *found]
            write_model(self.layout.importers, state)
        return True

    def collect(self) -> list[FileReport]:
        """Take what the pass found since the last collection."""
        with self.guard():
            state = self.state()
            found = state.found
            state.found = []
            write_model(self.layout.importers, state)
        return found

    def wait(
        self,
        checker: Checker,
        clock: Clock,
        patience: timedelta = timedelta(minutes=10),
        poll: timedelta = timedelta(seconds=1),
    ) -> None:
        """Wait for the pass to finish, so no type error surfaces after the turn.

        Work left pending with no pass running (one that failed as it started)
        is done here.
        """
        deadline = clock.now() + patience
        while self.running() and clock.now() < deadline:
            clock.sleep(poll.total_seconds())
        if not self.running():
            self.run(checker)
