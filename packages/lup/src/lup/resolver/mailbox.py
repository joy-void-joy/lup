"""The persisted question mailbox every answer door writes through.

A question is a :class:`~lup.channels.slot.Slot`: declared once by whoever
asks, offered to by any door, and settled exactly once. Messages ride a
:class:`~lup.channels.stream.Stream` instead, and that split is the point.
A run parks while any *slot* it needs is unsettled; nothing parks on a
stream. So volunteering information to a worker cannot stall the run, which
it could when both rode the same structure.

Doors write ``offered``, which is correctable — a mistyped free-text answer
can be replaced right up until it counts, and an offer may arrive before its
question exists, which is what lets a flag answer a question the run has not
asked yet. Exactly one writer promotes offers into ``settled``, taking the
earliest valid one, so "first answer wins" is a deterministic decision
rather than a race between whoever reached the filesystem first.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from lup.channels.models import (
    ChannelConflictError,
    ChannelCorruptionError,
    Door,
    DoorPolicy,
    utc_now,
)
from lup.channels.slot import Slot, SlotSet
from lup.channels.stream import Stream
from lup.channels.wait import POLL_SECONDS, wait_until
from lup.resolver.models import FROZEN, MaterialQuestion, QuestionAnswer

QUESTION_DIR = "questions"
MESSAGE_FILE = "messages.jsonl"
PARK_DIR = "park"
RESUME_DIR = "resume"
ANSWER_POLL_SECONDS = POLL_SECONDS

# The resolver's own names for the channel package's shapes, so a caller
# reads one vocabulary rather than two.
MailboxConflictError = ChannelConflictError
MailboxCorruptionError = ChannelCorruptionError
AnswerDoor = Door


class PendingQuestion(BaseModel):
    """One question a run is waiting on, written once by whoever asked."""

    model_config = FROZEN

    run_id: str
    question: MaterialQuestion
    asked_by: str
    asked_at: datetime


class AnswerOffer(BaseModel):
    """One door's proposed answer, correctable until it is promoted."""

    model_config = FROZEN

    run_id: str
    question_id: str
    value: str
    door: AnswerDoor
    offered_at: datetime


class RecordedAnswer(BaseModel):
    """The promoted answer to one question. Written once, never revised."""

    model_config = FROZEN

    run_id: str
    answer: QuestionAnswer
    door: AnswerDoor
    answered_at: datetime


class ParkRequest(BaseModel):
    """A door asking every open wait in this run to give up now."""

    model_config = FROZEN

    run_id: str
    reason: str


class ActorMessage(BaseModel):
    """One thing a door told an actor. This never settles anything.

    A message is not a question, and the type is where that is enforced: a
    stream has no unsettled state for a run to wait on, so no amount of
    messaging can park anything.
    """

    model_config = FROZEN

    run_id: str
    to_actor: str
    text: str
    door: AnswerDoor
    sent_at: datetime
    in_reply_to: str = ""


class MailboxWait(BaseModel):
    """How one wait ended. ``reason`` is empty only on a complete answer."""

    model_config = ConfigDict(frozen=True)

    answered: list[RecordedAnswer]
    unanswered: list[str]
    reason: str = ""


type MailboxRecord = PendingQuestion | AnswerOffer | RecordedAnswer | ParkRequest


class MailboxSlotRecord(BaseModel):
    """One question slot's payload at whichever of its three states it holds.

    A slot stores one model, and a question's declaration, its correctable
    offer, and its settled answer are three different shapes. Carrying all
    three optionally keeps the slot generic over a single type without
    collapsing what the three of them mean.
    """

    model_config = FROZEN

    pending: PendingQuestion | None = None
    offer: AnswerOffer | None = None
    answer: RecordedAnswer | None = None


class QuestionMailbox:
    """File-backed question, answer, and message exchange for one run."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.slots: SlotSet[MailboxSlotRecord] = SlotSet(
            root / QUESTION_DIR, MailboxSlotRecord
        )
        self.stream: Stream[ActorMessage] = Stream(
            root / MESSAGE_FILE, TypeAdapter(ActorMessage)
        )
        self.park_slot: Slot[ParkRequest] = Slot(root / PARK_DIR, ParkRequest)
        # Pause and resume are asymmetric on purpose. Pausing is a directive
        # any door may issue; resuming is a decision, and excluding AGENT
        # makes it one the orchestrator physically cannot take for itself.
        self.resume_slot: Slot[ParkRequest] = Slot(
            root / RESUME_DIR, ParkRequest, DoorPolicy(excluded=[Door.AGENT])
        )

    def queue(self, pending: PendingQuestion) -> None:
        """Record a question once; re-asking the same question is a no-op."""
        slot = self.slots.slot(pending.question.id)
        existing = slot.declared()
        if existing is not None and existing.pending is not None:
            if existing.pending.question != pending.question:
                raise MailboxConflictError(
                    f"question {pending.question.id!r} is already asked differently"
                )
            return
        slot.declare(MailboxSlotRecord(pending=pending))

    def offer(self, offer: AnswerOffer) -> None:
        """Propose an answer, replacing any earlier proposal for that question."""
        self.slots.slot(offer.question_id).offer(
            MailboxSlotRecord(offer=offer), offer.door
        )

    def record(self, answer: RecordedAnswer) -> bool:
        """Promote one answer, or report that another door already won."""
        return self.slots.slot(answer.answer.question_id).settle(
            MailboxSlotRecord(answer=answer), answer.door
        )

    def questions(self) -> list[PendingQuestion]:
        return [
            record.pending
            for record in self.slots.declared()
            if record.pending is not None
        ]

    def offers(self) -> list[AnswerOffer]:
        return [
            record.offer for record in self.slots.offered() if record.offer is not None
        ]

    def answers(self) -> list[RecordedAnswer]:
        return [
            record.answer
            for record in self.slots.settled()
            if record.answer is not None
        ]

    def answered_ids(self) -> list[str]:
        return [record.answer.question_id for record in self.answers()]

    def send(self, message: ActorMessage) -> None:
        """Tell an actor something. This never settles and never parks a run."""
        self.stream.append(message)

    def messages_for(self, actor: str, offset: int = 0) -> list[ActorMessage]:
        """Every message addressed to one actor, or broadcast to all of them."""
        return [
            pair.item
            for pair in self.stream.read_from(offset)
            if pair.item.to_actor in (actor, "")
        ]

    def park(self, request: ParkRequest) -> None:
        self.park_slot.clear()
        self.park_slot.settle(request)

    def parked(self) -> ParkRequest | None:
        return self.park_slot.settled()

    def clear_park(self) -> None:
        """Drop a stale park marker so a resumed run can wait again."""
        self.park_slot.clear()

    def request_resume(self, request: ParkRequest, door: AnswerDoor) -> bool:
        """Release a paused run. Refused for ``AGENT`` by the slot's own policy."""
        return self.resume_slot.settle(request, door)

    def resumed(self) -> ParkRequest | None:
        return self.resume_slot.settled()


async def wait_for_answers(
    mailbox: QuestionMailbox,
    question_ids: list[str],
    *,
    wait_seconds: float,
    poll_interval_seconds: float = ANSWER_POLL_SECONDS,
    wake: asyncio.Event | None = None,
) -> MailboxWait:
    """Wait for every named answer, a park request, or the deadline.

    The tick bounds how late an out-of-process answer can be noticed; the
    optional event lets an in-process promoter deliver one with no delay at
    all. Both surfaces observe the same promotion, so there is one mechanism
    rather than a fast path and a slow path that can disagree.
    """
    wanted = list(dict.fromkeys(question_ids))

    def recorded() -> dict[str, RecordedAnswer]:
        return {record.answer.question_id: record for record in mailbox.answers()}

    def resolved() -> MailboxWait | None:
        found = recorded()
        answered = [found[name] for name in wanted if name in found]
        outstanding = [name for name in wanted if name not in found]
        if not outstanding:
            return MailboxWait(answered=answered, unanswered=[])
        request = mailbox.parked()
        if request is not None:
            return MailboxWait(
                answered=answered, unanswered=outstanding, reason=request.reason
            )
        return None

    settled = await wait_until(
        resolved,
        wait_seconds=wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        wake=wake,
    )
    if settled is not None:
        return settled
    found = recorded()
    return MailboxWait(
        answered=[found[name] for name in wanted if name in found],
        unanswered=[name for name in wanted if name not in found],
        reason="no answer arrived before the wait elapsed",
    )


def new_message(
    run_id: str, to_actor: str, text: str, door: AnswerDoor, in_reply_to: str = ""
) -> ActorMessage:
    """Build a message stamped now, so callers do not each reach for a clock."""
    return ActorMessage(
        run_id=run_id,
        to_actor=to_actor,
        text=text,
        door=door,
        sent_at=utc_now(),
        in_reply_to=in_reply_to,
    )
