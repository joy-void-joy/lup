"""The independently replaceable resolver capability contracts."""

from abc import ABC, abstractmethod
from pathlib import Path

from lup.resolver.models import (
    ConcernProgress,
    MaterialQuestion,
    ResolvePhase,
    RunTally,
)


class ResolverAwaitingAnswers(Exception):
    """A run parked on material questions no door answered in time.

    The resolver raises this rather than guessing: it records the affected
    concerns as waiting and surfaces every pending question, so one
    flag-carrying rerun can answer the complete set.
    """

    def __init__(self, pending: list[MaterialQuestion], problems: list[str]) -> None:
        super().__init__(f"resolver run is awaiting {len(pending)} material answer(s)")
        self.pending = pending
        self.problems = problems


class ResolverEnvironmentFault(Exception):
    """A run stopped because its host failed, not because its work did.

    A revoked credential, an exhausted allowance or a dead network reaches
    every concern in flight at once and says nothing about any of them. So
    this travels the way a park does rather than the way a failure does: no
    concern is transitioned, no outcome is written, and the run keeps every
    status it held. Resuming re-enters each concern exactly where it was.

    Kept apart from `ResolverAwaitingAnswers` because the two ask different
    things of a human. A park wants an answer; this wants the host fixed,
    and then the same command again.
    """

    def __init__(self, cause: str, concerns: list[str]) -> None:
        super().__init__(f"resolver run stopped on an environmental fault: {cause}")
        self.cause = cause
        self.concerns = concerns


class ResolverObserver(ABC):
    """Receive every durably recorded resolver transition as it lands.

    The resolver emits only after the state repository has saved, so an
    observer never reports a transition that a crash could roll back.
    """

    @abstractmethod
    def phase_changed(self, phase: ResolvePhase) -> None:
        """One run-level phase was recorded."""

    @abstractmethod
    def concern_changed(self, progress: ConcernProgress) -> None:
        """One concern status or reason was recorded."""

    @abstractmethod
    def tally_changed(self, tally: RunTally) -> None:
        """The run's aggregate progress moved.

        Per-concern lines say what just happened; this says where the run
        stands — counts per status and joins landed — so a watcher stops
        reconstructing the aggregate from the scroll.
        """


class WorktreePreparer(ABC):
    """Make a freshly created leased worktree ready for execution.

    A bare ``git worktree add`` carries no dependency environment, so
    verification commands inside the lease would resolve against the source
    checkout. The application injects the same preparation its ordinary
    feature worktrees receive.
    """

    @abstractmethod
    def prepare(self, root: Path) -> None:
        """Prepare one worktree root after creation or restoration."""
