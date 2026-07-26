"""The independently replaceable user-question delivery capability."""

from abc import ABC, abstractmethod

from lup.resolver.models import AnswerBatch, MaterialQuestion, QuestionBatch


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
