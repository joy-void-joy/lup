"""The background pass re-checking the files that import what a checkpoint accepted.

The rules read only the changed files, so their findings come at the edit; the
files importing them are re-checked for type errors in the background, and their
errors arrive at the next checkpoint (`docs/judging-writes.md`, *The engine: one
typed tree*). One pass at a time per worktree, and the turn's end waits for it, so
no type error surfaces after the session.

Each request names the conversations that wrote what changed, and what the pass
finds comes back with them, so a conversation's end holds only on what their own
changes broke (#41). The pass re-checks what's pending as one batch, so what it
finds goes to every conversation that wrote into that batch.
"""

import sys
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from filelock import FileLock, Timeout

from lup.programs import detached
from lup.types import Model, MutableModel
from lup_dev.codescan.contract import Checker, FileReport
from lup_dev.layout import StoreLayout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from lup_dev.clock import Clock
    from lup_dev.declaration.runner import Runner


class Spawner(ABC):
    """Starts a worktree's background importers pass."""

    @abstractmethod
    def spawn(self, worktree: Path, log: Path) -> None:
        """Start the pass for the worktree at `worktree`, printing to `log`."""


class BackgroundSpawner(Spawner, Model):
    """Starts the pass as its own process, detached from the process that asks for it."""

    command: list[str] = ["importers"]
    """The hidden `lup-dev` command that runs the pass, given the worktree."""
    environments: Path | None = None
    """The launch's own environments, where the hook asking for the pass is of
    a room that has them: the pass reads the worktree's there, as the hook's
    judge does, so the two share one engine."""

    @override
    def spawn(self, worktree: Path, log: Path) -> None:
        reading = (
            []
            if self.environments is None
            else ["--environments", str(self.environments)]
        )
        detached(
            sys.executable,
            "-m",
            "lup_dev.cli",
            *self.command,
            str(worktree),
            *reading,
            log=log,
        )


class Conversation(Model):
    """One conversation of a session: their own, or one of their subagents'."""

    session: str
    agent: str = ""
    """Empty for the session's own conversation, else a subagent's id."""


class Found(Model):
    """What the pass found since the last collection, and whose changes it re-checked."""

    reports: list[FileReport] = []
    writers: list[Conversation] = []


class ImportersState(MutableModel):
    """What the background importers pass has left to do, and what it found."""

    pending: list[Path] = []
    """Files changed since the pass took its last batch."""
    pending_writers: list[Conversation] = []
    """The conversations that wrote them."""
    found: list[FileReport] = []
    """What the pass found, waiting for the next checkpoint."""
    found_writers: list[Conversation] = []
    """The conversations that wrote what the pass re-checked to find it."""


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

    def request(
        self, changed: list[Path], writers: list[Conversation], spawner: Spawner
    ) -> None:
        """Ask for the files importing `changed`, which `writers` wrote, to be re-checked.

        Starts a pass unless one runs; one that runs takes these next.
        """
        if not changed:
            return
        with self.guard():
            state = self.state()
            state.pending = list(dict.fromkeys([*state.pending, *changed]))
            state.pending_writers = list(
                dict.fromkeys([*state.pending_writers, *writers])
            )
            write_model(self.layout.importers, state)
            if self.running():
                return
        spawner.spawn(self.root, self.layout.importers_log)

    def run(self, checker: Checker, runner: Runner) -> None:
        """Run the pass until nothing is pending; return at once if another runs.

        The engine reads types in the environment the project's `runner` gives
        the worktree, as the judge's checks do.
        """
        held = self.runner()
        try:
            held.acquire()
        except Timeout:
            return
        try:
            while self.step(checker, runner, held):
                pass
        finally:
            if held.is_locked:
                held.release()

    def step(self, checker: Checker, runner: Runner, held: FileLock) -> bool:
        """Re-check one batch; say whether to look for another.

        `held` is the lock the running pass holds, released once nothing is left.
        """
        with self.guard():
            state = self.state()
            batch = state.pending
            writers = state.pending_writers
            if not batch:
                held.release()
                return False
            state.pending = []
            state.pending_writers = []
            write_model(self.layout.importers, state)
        found = checker.importers(self.root, batch, runner)
        with self.guard():
            state = self.state()
            state.found = [*state.found, *found]
            state.found_writers = list(dict.fromkeys([*state.found_writers, *writers]))
            write_model(self.layout.importers, state)
        return True

    def collect(self) -> Found:
        """Take what the pass found since the last collection, with its writers."""
        with self.guard():
            state = self.state()
            found = Found(reports=state.found, writers=state.found_writers)
            state.found = []
            state.found_writers = []
            write_model(self.layout.importers, state)
        return found

    def wait(
        self,
        checker: Checker,
        runner: Runner,
        clock: Clock,
        patience: timedelta = timedelta(minutes=10),
        poll: timedelta = timedelta(seconds=1),
    ) -> None:
        """Wait for the pass to finish, so no type error surfaces after the turn.

        Work left pending with no pass running (one that failed as it started)
        is done here, with the project's `runner`.
        """
        deadline = clock.now() + patience
        while self.running() and clock.now() < deadline:
            clock.sleep(poll.total_seconds())
        if not self.running():
            self.run(checker, runner)
