"""The resolver's mailbox: the shared one, bound to its own question type.

Everything this module used to hold is in :mod:`lup.actors.mailbox`. What it
did — declare a question once, let any door correct an offer, promote exactly
one answer, and carry messages on a stream nothing parks on — was never about
concerns or leases.

What stays is the binding: which question rides in the slots. Only that, so
this is a specialization rather than a barrel — a caller wanting
``AnswerOffer`` or ``ActorMessage`` imports it from the layer that defines it,
and there is one place each name comes from.
"""

from pathlib import Path

from lup.actors.mailbox import PendingQuestion as SharedPendingQuestion
from lup.actors.mailbox import QuestionMailbox as SharedMailbox
from lup.resolver.models import MaterialQuestion


class PendingQuestion(SharedPendingQuestion[MaterialQuestion], frozen=True):
    """One resolver question a run is waiting on.

    A subclass rather than an alias because callers construct it, and an
    alias to a parameterized generic is a type rather than something
    callable.
    """


class QuestionMailbox(SharedMailbox[MaterialQuestion]):
    """This run's mailbox, carrying the resolver's own question.

    A subclass rather than an alias so the question type is supplied once,
    here, and every construction site keeps saying ``QuestionMailbox(root)``.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root, MaterialQuestion)
