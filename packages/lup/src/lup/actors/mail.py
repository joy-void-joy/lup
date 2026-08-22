# lup: ignore[constant-declaration]
# The constants here name the stream's own on-disk layout, which a writer and
# a reader in different processes must agree on to find each other's files at
# all — an identity of this format rather than a choice a caller can make.
"""Saying something to a running actor, and knowing whether it was read.

A message is not a question, and the type is where that is enforced: mail
rides a :class:`~lup.channels.stream.Stream`, which has no unsettled state
for anything to wait on, so no amount of messaging can park a run. That split
— questions are slots, messages are streams — is what lets a caller volunteer
information to a working actor without stalling whoever volunteered it.

Delivery positions are files rather than numbers a session happens to hold.
Two readers over one stream, each starting at whatever the head was when it
was constructed, can only agree by luck: a message posted while a turn was in
flight was already behind both of them, and the run reported it sent.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from lup.actors.refs import ActorRef
from lup.channels.cursor import StreamCursors
from lup.channels.models import Door, utc_now
from lup.channels.stream import Stream

MESSAGE_FILE = "messages.jsonl"
DELIVERY_DIR = "delivery"

EVERYONE = "*"
"""The address every actor answers to, for one message meant for all of them.

A token rather than a blank, because these are different acts and the blank
spelled both. `to_actor` is optional on more than one door, so leaving it out
used to broadcast: a worker's report to the humans was delivered into every
sibling's context and consumed there, and no surface a person reads ever held
it. An unaddressed message now reaches nobody, which is the safe direction for
a field somebody forgot.

One record rather than one per member, so an actor spawned after the broadcast
still receives it — its cursor starts behind the record, and the record is
still addressed to it. A fan-out at send time cannot do that, because it can
only name the members that existed when it ran.
"""


class ActorMessage(BaseModel, frozen=True):
    """One thing a door told an actor. This never settles anything.

    ``redirect`` separates telling an actor something from stopping it. An
    ordinary message rides in front of the actor's next tool call and it
    keeps going; a redirect refuses that call and hands back the text as the
    reason, so the actor cannot carry on with what it was doing without
    first reading why it was stopped. Both are the same record on the same
    stream, because an intervention belongs in order beside what it
    interrupted.
    """

    run_id: str
    to_actor: str
    text: str
    door: Door
    sent_at: datetime
    in_reply_to: str = ""
    redirect: bool = False


class ActorDelivery(BaseModel, frozen=True):
    """What one actor has waiting, and the position that consumes exactly it.

    The position is carried rather than taken again at the moment of
    delivery, because a message posted between reading and handing over
    would otherwise be committed past without ever being read.
    """

    messages: list[ActorMessage]
    through: int

    def redirects(self) -> list[ActorMessage]:
        return [message for message in self.messages if message.redirect]


class MailEventBase(BaseModel, frozen=True):
    """One thing that happened to an actor's mail, answering about itself.

    The arrangement the turn events already use, for the same reason: a
    reader asks the event rather than testing which one it is holding, so a
    third thing that can happen to a message — expired, forwarded, refused
    by a closed door — is one class rather than an edit to every fold that
    would otherwise have to notice it and would not.

    What every kind carries is here. What separates them is whether the
    actor took the message, which is the one fact a reader cannot infer and
    the one the sender most needs: a sender is told a message was sent on
    the strength of the mailbox accepting it, which is not the same as
    anybody having read it.
    """

    text: str
    door: str
    redirect: bool = False

    @property
    def delivered(self) -> bool:
        """Whether the actor took this, or it only ever reached its queue."""
        raise NotImplementedError


class MessagePostedEvent(MailEventBase, frozen=True):
    """A door volunteered something to an actor, or an actor replied.

    An intervention belongs in the record beside what it interrupted. A
    reader scrolling one actor's trace sees the moment someone redirected
    it, in order, against what it was doing — which is the difference
    between a trace and an audit filed somewhere else.
    """

    type: Literal["message_posted"] = "message_posted"
    in_reply_to: str | None = None

    @property
    def delivered(self) -> bool:
        """Posted is handed over: this record is written where it lands."""
        return True


class MessageOutstandingEvent(MailEventBase, frozen=True):
    """A message still queued for an actor whose session is being closed.

    Recorded because the sender was told the message was sent, and the
    stream alone cannot say whether anyone read it. On a park this is a
    message that will land at the head of the resumed turn; on a run that
    ended it is one that reached nobody, and a redirect nobody read is the
    failure of an operation somebody performed to stop something.
    """

    type: Literal["message_outstanding"] = "message_outstanding"

    @property
    def delivered(self) -> bool:
        """Queued and not handed over, which is the whole point of the record."""
        return False


type MailEvent = MessagePostedEvent | MessageOutstandingEvent
"""What the actor layer itself records, which any consumer's journal admits."""


class ActorMail:
    """One run's message stream and everyone's position in it.

    Separate from the question mailbox because the two are different
    commitments over different storage, and only this half is what an actor
    holds open to stay reachable. A consumer wanting nothing but
    addressability takes this and never declares a question.
    """

    def __init__(self, root: Path) -> None:
        self.stream: Stream[ActorMessage] = Stream(
            root / MESSAGE_FILE, TypeAdapter(ActorMessage)
        )
        self.cursors = StreamCursors(root / DELIVERY_DIR)

    def send(self, message: ActorMessage) -> None:
        """Tell an actor something. This never settles and never parks a run."""
        self.stream.append(message)

    def waiting(self, actor: ActorRef) -> ActorDelivery:
        """Everything queued for one actor, consuming none of it.

        From the position that actor was last *delivered* to, which is a
        file rather than a number some session happens to hold. Starting
        each session at the stream head instead meant a message posted while
        the previous turn was in flight was skipped rather than queued: the
        window a turn opened began after it, in every round, so it reached
        nobody ever. Reading is separated from consuming so that asking what
        an actor has waiting — which is how a sender learns whether anything
        was read — cannot itself be what makes it disappear.
        """
        position = self.cursors.offset(actor.conversation())
        found = self.stream.read_from(position)
        reaching = actor.addresses()

        def addressed(message: ActorMessage) -> bool:
            """Whether this actor is a recipient, alone or among everyone.

            The broadcast is matched here rather than by putting a token in
            every actor's own addresses, so identity stays the answer to "is
            this me?" and a door asking which actor `*` names correctly gets
            none.
            """
            return message.to_actor == EVERYONE or message.to_actor in reaching

        return ActorDelivery(
            messages=[pair.item for pair in found if addressed(pair.item)],
            through=found[-1].commit_offset if found else position,
        )

    def delivered(self, actor: ActorRef, through: int) -> None:
        """Record that one actor has been handed everything through ``through``.

        The whole region rather than the last matching message, because a
        reader filtering by actor must still skip past the ones addressed
        elsewhere or it re-reads them on every turn.
        """
        self.cursors.commit(actor.conversation(), through)


def new_message(
    run_id: str,
    to_actor: str,
    text: str,
    door: Door,
    in_reply_to: str = "",
    redirect: bool = False,
) -> ActorMessage:
    """Build a message stamped now, so callers do not each reach for a clock."""
    return ActorMessage(
        run_id=run_id,
        to_actor=to_actor,
        text=text,
        door=door,
        sent_at=utc_now(),
        in_reply_to=in_reply_to,
        redirect=redirect,
    )
