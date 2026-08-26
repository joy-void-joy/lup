"""What every question is, under whatever a consumer adds to it.

A question is a :class:`~lup.channels.slot.Slot`: declared once by whoever
asks, offered to by any door, and settled exactly once. What rides in the
slot differs — the resolver's carries the edit gates a choice would need, a
research session's carries nothing of the sort — so the shape a mailbox
needs is here and the rest subclasses it.

The base holds what a *door* has to read to present the question and record
an answer against it. Anything only the asker consults belongs to the asker.
"""

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class Question(BaseModel, frozen=True):
    """One question put to whoever can answer it, in the mailbox's own terms."""

    id: str
    prompt: str
    choices: list[str] = []
    recommendation: str | None = None
    closed_choices: bool = Field(
        default=False,
        description=(
            "Whether the choices are the complete answer domain. A gate whose "
            "reader tests for a literal token closes them; a question whose "
            "choices are suggestions leaves them open, so the answer may "
            "arrive in the answerer's own words."
        ),
    )

    def restates(self, asked: "Question") -> bool:
        """Whether this is ``asked`` again, re-rendered from facts that moved.

        An answer binds to the choices, not to the prose around them. A gate
        that quotes a fact still moving re-renders itself while the run is
        parked on it, so the prose changing is the question staying true —
        where a moved answer domain would be a different question wearing one
        id.
        """
        return self.model_copy(update={"prompt": asked.prompt}) == asked

    @model_validator(mode="after")
    def identity_is_path_safe(self) -> "Question":
        """Each question is one file in the mailbox, so its id is a filename."""
        if not self.id or Path(self.id).name != self.id:
            raise ValueError(f"question id {self.id!r} is not a path-safe name")
        return self

    @model_validator(mode="after")
    def recommendation_is_a_choice(self) -> "Question":
        if (
            self.recommendation is not None
            and self.choices
            and self.recommendation not in self.choices
        ):
            raise ValueError(
                f"question {self.id!r} recommendation is not one of its choices"
            )
        return self


class QuestionAnswer(BaseModel, frozen=True):
    """One answer, bound to the question it settles by id alone."""

    question_id: str
    value: str
