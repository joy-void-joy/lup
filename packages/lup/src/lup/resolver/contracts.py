"""The independently replaceable resolver capability contracts."""

from abc import ABC, abstractmethod
from pathlib import Path

from lup.resolver.models import (
    AnswerBatch,
    ConcernProgress,
    MaterialQuestion,
    QuestionBatch,
    ResolvePhase,
)


class ResolverAwaitingAnswers(Exception):
    """A run parked on material questions its broker has no answers for.

    Brokers raise this to park instead of guessing; the resolver records the
    affected concerns as waiting and surfaces every pending question so one
    flag-carrying rerun can answer the complete set.
    """

    def __init__(self, pending: list[MaterialQuestion], problems: list[str]) -> None:
        super().__init__(f"resolver run is awaiting {len(pending)} material answer(s)")
        self.pending = pending
        self.problems = problems


class QuestionBroker(ABC):
    """Deliver material resolver questions and return persisted answers."""

    @abstractmethod
    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        """Ask one batch before worker execution."""


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
