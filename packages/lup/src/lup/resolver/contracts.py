"""The independently replaceable user-question delivery capability."""

from abc import ABC, abstractmethod

from lup.resolver.models import AnswerBatch, QuestionBatch


class QuestionBroker(ABC):
    """Deliver material resolver questions and return persisted answers."""

    @abstractmethod
    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        """Ask one batch before worker execution."""
