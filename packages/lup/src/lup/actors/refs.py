"""Which actor something belongs to, in the one spelling every path uses."""

from pydantic import BaseModel, Field


class ActorRef(BaseModel, frozen=True):
    """Which actor something belongs to.

    A round is part of the identity because the same worker on round two is a
    different actor: it holds a different session, and a reader tracing a
    decision needs to know which attempt they are looking at.

    Here rather than with the record it attributes, because addressing an
    actor is not the journal's business alone: the mailbox routes mail by the
    same identity, and the two disagreeing about what named an actor is what
    made a redirect reach nobody.

    ``kind`` is an open string. The consumer names its own roles and validates
    them at its own boundary — a closed set here would be every consumer's set
    at once, and adding a role to one would mean editing the layer underneath
    all of them.
    """

    kind: str = Field(min_length=1)
    id: str
    round: int = Field(default=1, ge=1)

    def label(self) -> str:
        return f"{self.kind}:{self.id}#{self.round}"

    def conversation(self) -> str:
        """Which session this actor speaks through, which outlives its round.

        Deliberately not the label. A worker on round two is the agent that
        wrote round one's code and was told what was wrong with it, so the
        round attributes what happened without forking the conversation —
        and anything held per conversation, an open session or a delivery
        position, is keyed by this rather than by the round it is on.
        """
        return f"{self.kind}-{self.id}"

    def addresses(self) -> list[str]:
        """Every spelling a door may use that reaches this actor.

        Recognizing rather than parsing, because the two delivery paths
        disagreed about what an address was: one printed and accepted
        ``worker:some-concern#1`` while the mid-turn hook matched the bare
        id, so a redirect sent to the address that was printed reached
        nobody.

        Earlier rounds are included because they name the same conversation.
        A worker's second round is the session that took its first, so an
        operator addressing the label listed a round ago is not addressing a
        different agent, and nothing they could read would tell them the
        label had moved on.
        """
        return [
            "",
            self.id,
            f"{self.kind}:{self.id}",
            *(f"{self.kind}:{self.id}#{taken}" for taken in range(1, self.round + 1)),
        ]
