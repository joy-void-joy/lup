"""What one agent has done so far, read while it is still doing it.

A spawn that has not returned is not a spawn nobody can learn from. Its turn
events reach the journal as they happen, so the material for "which of these
three is getting somewhere" is already on disk — what was missing is a way to
read it that does not cost the reader the whole transcript.

That is the shape here: a fold from records to lines, at the resolution
somebody outside the agent needs. What it said, what it called, what refused
it, and what was said to it. Not what it thought — reasoning is the largest
thing in a turn by a wide margin, and a caller deciding whether to keep
steering a spawn is not reading it. Not what its calls returned either: a
whole certificate or a search sweep is the artifact rather than news about
it, and the agent's own words are what it made of them.

A reader is a follower. It takes a page, keeps the cursor, and comes back.
Where more is waiting than a page holds, the recent end is what it carries
and the count of what it passed over rides along — an agent that has been
working an hour is exactly the one whose last minutes answer the question,
and a page that quietly dropped the rest would read like the whole record of
a quiet agent.

The roster's word rides with the lines for the same reason. Lines alone read
as an agent gone quiet when it may have finished an hour ago; a roster alone
says something is working and nothing about what it has found.
"""

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from lup.actors.cohort import ActorCohort, CohortEntry
from lup.actors.mail import MailEventBase
from lup.actors.refs import ActorRef
from lup.actors.roster import SpawnedActor
from lup.runtime.models import TurnMessage
from lup.types import JsonObject

type ProgressKind = Literal[
    "said", "called", "refused", "received", "redirected", "unread"
]
"""What one line is. Telling and stopping stay apart here as everywhere else:
a caller that redirected an agent needs to see *that* land, and a line reading
`received` where a redirect was sent is the report that sends somebody looking
for an agent that never read it."""


class ProgressWindow(BaseModel):
    """How much of one conversation a single read carries.

    A model rather than three parameters, so the tool an agent calls and the
    door a person watches take the same window and neither has to restate
    what a page is.
    """

    after: int = Field(
        default=-1,
        ge=-1,
        description=(
            "Resume after this record number — the cursor a previous read "
            "handed back. Leave it out to start from the most recent"
        ),
    )
    limit: int = Field(
        default=40,
        gt=0,
        description=(
            "How many records one page folds. Where more are waiting, the "
            "most recent are what it carries and the rest are counted"
        ),
    )
    chars: int = Field(
        default=600,
        gt=0,
        description=(
            "How much of one line survives. What a cut leaves behind is "
            "counted onto the line rather than dropped in silence"
        ),
    )


class ProgressLine(BaseModel, frozen=True):
    """One thing an agent did, or one thing that reached it."""

    seq: int = Field(ge=0, description="Where this sits in the cohort's record")
    at: datetime
    kind: ProgressKind = Field(
        description=(
            "said: the agent's own words. called: an instrument it invoked. "
            "refused: a call that came back an error. received: something a "
            "door told it. redirected: something that stopped it. unread: "
            "something said to it that it never took"
        )
    )
    text: str
    tool: str = Field(
        default="", description="The instrument, on a line that names one"
    )
    door: str = Field(
        default="", description="Where it came from, on a line that was sent"
    )


class ActorProgress(BaseModel, frozen=True):
    """One conversation's record since a cursor, and where to resume."""

    address: str
    running: bool = Field(
        description="Whether the roster still holds this agent as working"
    )
    lines: list[ProgressLine] = []
    cursor: int = Field(
        description="Pass back as `after` to resume where this page stopped"
    )
    skipped: int = Field(
        default=0,
        description=(
            "Records between the cursor and this page that would not fit. "
            "Nonzero means the agent has moved faster than this reader; "
            "raise the limit, or accept that the recent end is the answer"
        ),
    )
    summary: str = Field(
        default="", description="What it concluded, once it has concluded"
    )
    error: str = Field(default="", description="Why it stopped, where it failed")


def brief(text: str, chars: int) -> str:
    """One value cut to what identifies it, saying how much it stands for.

    The whole value stays in the journal this line was folded from, at the
    record number the line carries, so the cut costs a reader nothing it
    cannot go and get.
    """
    if len(text) <= chars:
        return text
    return f"{text[:chars]}… (+{len(text) - chars} more chars)"


def arguments(values: JsonObject, chars: int) -> str:
    """What a call was made with, at the resolution a watcher needs."""
    return brief(
        " ".join(f"{name}={value}" for name, value in sorted(values.items())), chars
    )


def mail_kind(mail: MailEventBase) -> ProgressKind:
    """Which line one message is, read off what the mail says about itself.

    Three outcomes rather than two, because a sender needs all three apart:
    something that reached the agent, something that stopped it, and
    something it never took — and the last is the failure of an operation
    somebody performed, which the other two would hide.
    """
    if not mail.delivered:
        return "unread"
    return "redirected" if mail.redirect else "received"


def progress_lines(entries: Sequence[CohortEntry], chars: int) -> list[ProgressLine]:
    """Fold one conversation's records into the lines a reader outside it needs."""
    # Which call each result answers, so a refusal names the instrument that
    # refused rather than an opaque identifier. Carried across the page rather
    # than within one message, because a result arrives in a later message
    # than the call it answers.
    # lup: ignore[dict-str-payload, empty-collection] — provider call ids, an
    # open key set, folded onto their names as the page walks
    invoked: dict[str, str] = {}

    def stamped(
        entry: CohortEntry,
        kind: ProgressKind,
        text: str,
        tool: str = "",
        door: str = "",
    ) -> ProgressLine:
        """One line, placed where the record it came from sits."""
        return ProgressLine(
            seq=entry.seq, at=entry.at, kind=kind, text=text, tool=tool, door=door
        )

    def blocks(message: TurnMessage, entry: CohortEntry) -> Iterator[ProgressLine]:
        """Every line one completed message contributes, asking each block.

        Asking rather than testing the type, so a block written later is
        carried by whichever accessor it answers and this fold never becomes
        the filter that silently stopped seeing something.

        What the agent was *given* is not here. A user message is the task
        this reader already holds and the mail this reader already sent, and
        a page that echoed either back would spend its room on them.
        """
        if message.role not in ("assistant", "tool"):
            return
        for block in message.blocks:
            if (name := block.tool_call_name) is not None:
                if (identifier := block.invoked_call_id) is not None:
                    invoked[identifier] = name
                yield stamped(
                    entry,
                    "called",
                    arguments(block.tool_arguments or {}, chars),
                    tool=name,
                )
            elif (refused := block.refusal) is not None:
                yield stamped(
                    entry,
                    "refused",
                    brief(refused.detail, chars),
                    # lup: ignore[dict-get] — a result whose call fell before
                    # this page names no instrument, which is what "" says
                    tool=invoked.get(refused.call_id, ""),
                )
            elif (said := block.text_payload) is not None:
                yield stamped(entry, "said", brief(said, chars))

    def lines(entry: CohortEntry) -> Iterator[ProgressLine]:
        """Whatever one record says happened, as lines stamped with its place.

        One narrowing, and it separates the two families rather than the
        members of either. Mail answers through its base and a turn through
        its own accessor, so a kind added to either side is carried by
        whichever question it already answers instead of falling through a
        filter that stopped being complete.
        """
        match entry.event:
            # The two families, not the members of either. `ActorEvent` unions
            # mail with turn events across two layers, so there is no common
            # base for both to answer through: one narrowing separates them
            # and each side is then asked rather than tested. A kind added to
            # either family rides the accessor its family already answers, and
            # a third family fails to type-check right here, because the
            # capture below would no longer carry `completed_message`.
            # lup: ignore[own-model-dispatch] — separates the families, not their members
            case MailEventBase() as mail:
                yield stamped(
                    entry, mail_kind(mail), brief(mail.text, chars), door=mail.door
                )
            case turn:
                message = turn.completed_message
                if message is not None:
                    yield from blocks(message, entry)

    return [line for entry in entries for line in lines(entry)]


def read_progress(
    cohort: ActorCohort, actor: ActorRef, window: ProgressWindow
) -> ActorProgress:
    """One agent's recent record, folded, with the roster's word on it.

    Read from the cohort's own record rather than from whatever it appends
    to. A consumer keeping a journal of its own is keeping one this layer
    cannot fold — the resolver's carries what the *run* did as well — and the
    file this reads is the one the cohort's root names either way.

    The recent end is what a page keeps where the window cannot hold
    everything: an agent working for an hour is exactly the one whose last
    minutes say whether to keep steering it, and what fell outside is counted
    into ``skipped`` rather than dropped in silence.
    """
    entries = cohort.record.conversation(actor, window.after)
    page = entries[-window.limit :]
    member = next(
        (
            found
            for found in cohort.live()
            if found.actor.conversation() == actor.conversation()
        ),
        SpawnedActor(actor=actor, task="", running=False),
    )
    return ActorProgress(
        address=actor.label(),
        running=member.running,
        lines=progress_lines(page, window.chars),
        cursor=page[-1].seq if page else window.after,
        skipped=len(entries) - len(page),
        summary=member.summary,
        error=member.error,
    )
