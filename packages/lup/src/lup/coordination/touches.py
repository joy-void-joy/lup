"""What each session in this repository is holding, without anybody declaring it.

Nobody says what they are working on. Asking them to is asking for the one
thing an agent reliably forgets, and a declaration nobody keeps up to date is
worse than none — it reads as current and is not. So this is observed: a hook
watches what each session's calls actually change, and the record of that is
the claim.

A claim is alive while the session holding it is on the roster, and expires
with that session. There is no release to forget and no lock to leak, which is
what makes an observed claim safe to act on: the failure mode of the whole
mechanism is a session that stopped, and a stopped session's claims go with it.

**Two kinds, one record.** A *touch* is an exact path some session changed. A
*lock* is a prefix a session took deliberately, for the case observation
cannot reach — an agent about to rewrite a package has touched none of it yet,
and the interesting moment is before the first write rather than after it.

**A claim can have more than one holder,** and that is honest rather than
broken. A change made by a shell command is attributed by comparing the tree
before and after, which sees every change in its window regardless of who made
it — so where two sessions had windows open over one path, both names are
recorded and neither is guessed at. The next named-path edit or explicit lock
settles it, because both of those attribute exactly.

**The records are here and the fold is not.** What a record makes of a claim
is one question and three processes ask it, only one of which can import
pydantic — so it is answered once in :mod:`lup.coordination.bare.store` and
read back here as the typed shape a caller holds.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.coordination.bare import store
from lup.coordination.bare.store import TOUCHES_FILE
from lup.coordination.refs import ActorRef


class Claim(BaseModel, frozen=True):
    """One thing sessions are holding, as a reader about to write asks about it.

    Absolute paths throughout, so two sessions in different worktrees never
    collide over the same file of source. That is the right answer rather than
    a limitation: they are editing two checkouts, the merge is what reconciles
    them, and a claim that spanned worktrees would refuse ordinary parallel
    work.
    """

    path: str
    prefix: bool = False
    """Whether this covers everything beneath it, or exactly one file."""

    holders: list[ActorRef]
    """Every session with a claim on it, more than one where nothing could tell.

    Ordered by when each was recorded, so the first is whoever the attribution
    was first able to name.
    """

    digest: str = ""
    """The content this claim was recorded over, empty for a prefix lock."""

    at: datetime

    def held(self) -> store.Held:
        """This claim as the shared fold spells it, so one answer serves both."""
        return store.Held(
            subject=self.subject(),
            path=self.path,
            prefix=self.prefix,
            holders=[
                store.Actor(kind=holder.kind, id=holder.id, round=holder.round)
                for holder in self.holders
            ],
            digest=self.digest,
            at=self.at.isoformat(),
        )

    def covers(self, candidate: str) -> bool:
        """Whether a path about to be written falls under this claim."""
        return store.covers(self.held(), candidate)

    def subject(self) -> str:
        """What the fold keys this claim by, which a lock and a touch differ in.

        A prefix and an exact path can be spelled identically and mean
        different things — locking `src/lup` is not touching a file of that
        name — so the kind is part of the key rather than something a later
        record could silently convert.
        """
        return store.subject_of(self.path, self.prefix)

    def vacant(self) -> bool:
        """Whether the path this claim is over has gone from the filesystem.

        A worktree removed from under a session takes every path in it, and a
        claim over one names nothing anybody could write. Asked of the
        filesystem rather than of git, because a claim is keyed by the path
        and the path is what has to be there.
        """
        return store.vacant(self.held())


def folded_claim(held: store.Held) -> Claim:
    """One row of the shared fold, as a typed caller reads it.

    Total rather than validating, for the reason a member is: this is the read
    path a listing and a permission decision both go through, and a record a
    newer library wrote must leave an older one still able to say who holds
    what.
    """
    return Claim(
        path=held["path"],
        prefix=held["prefix"],
        holders=[
            ActorRef(
                kind=store.actor_kind(holder),
                id=store.actor_id(holder),
                round=store.actor_round(holder),
            )
            for holder in held["holders"]
            if store.actor_kind(holder) and store.actor_id(holder)
        ],
        digest=held["digest"],
        at=store.spoken_at(held["at"]) or utc_now(),
    )


class TouchRecord(BaseModel, frozen=True):
    """One thing that happened to a claim, written down as it happened."""

    actor: ActorRef
    at: datetime
    path: str


class PathTouched(TouchRecord, frozen=True):
    """One session changed one file, and it is known which session.

    Replaces whatever stood before it rather than joining it. A named-path
    edit attributes exactly, so it is the record that settles a claim nothing
    else could attribute — including one that had been left contested.
    """

    type: Literal["touched"] = "touched"
    digest: str = ""


class PathContested(TouchRecord, frozen=True):
    """One file changed while more than one session had a window over it.

    Recorded with every name rather than with a guess. A before-and-after
    comparison sees the change and cannot see who made it, and inventing an
    author there would put a confident wrong answer where a reader is deciding
    whether it is safe to write.
    """

    type: Literal["contested"] = "contested"
    digest: str = ""
    rivals: list[ActorRef] = []


class PrefixLocked(TouchRecord, frozen=True):
    """One session took a prefix deliberately, ahead of touching anything in it.

    The case observation cannot reach. An agent about to rewrite a package has
    changed none of it yet, and the moment worth telling anybody about is
    before the first write rather than after it.
    """

    type: Literal["locked"] = "locked"


class PrefixReleased(TouchRecord, frozen=True):
    """One session gave a prefix back, which only a holder of it can do.

    Checked in the fold rather than at the writer, because the record is the
    whole history and a reader replaying it has to reach the same answer as
    the process that wrote it. A release by somebody who never held it says
    nothing, which is what leaves the claim standing rather than letting one
    session unlock another's work by asking.
    """

    type: Literal["released"] = "released"


class PathVacated(TouchRecord, frozen=True):
    """The path a claim was over is gone, so the claim is over whoever held it.

    Written by whichever session's sweep noticed, which is why it ends the
    claim without being a holder: a path that is not there is held by nobody,
    and that is a fact of the filesystem any session can check rather than a
    say-so about somebody else's work. Recorded rather than derived at every
    read, so that a worktree cut again at the same path starts with no claims
    from the one that was removed.
    """

    type: Literal["vacated"] = "vacated"
    prefix: bool = False
    """Which claim over the path this ends, since a lock and a touch differ."""


type TouchEntry = (
    PathTouched | PathContested | PrefixLocked | PrefixReleased | PathVacated
)
"""What the claim record carries: two ways to take one, and two ways it ends.

A touch and a contest are the same event seen with and without an attribution,
which is why they are separate records rather than one carrying an optional
list — a reader deciding whether to write wants "somebody, and we know who"
told apart from "somebody, and nobody could tell" without inspecting a field's
emptiness. A release is a holder giving a prefix back; a vacating is the path
itself going, which ends a touch as readily as a lock.
"""

TOUCH_ADAPTER: TypeAdapter[TouchEntry] = TypeAdapter(TouchEntry)


class Touches:
    """Every claim this repository's sessions hold, folded from the record.

    Holds nothing and remembers nothing: a hook writing a touch, a console
    listing them, and a session asking whether it may write all fold the same
    file, so none of them has to be running for the others to answer.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.stream: Stream[TouchEntry] = Stream(root / TOUCHES_FILE, TOUCH_ADAPTER)

    def record(self, entry: TouchEntry) -> TouchEntry:
        """Append one thing that happened to a claim."""
        self.stream.append(entry)
        return entry

    def touched(self, actor: ActorRef, path: Path, digest: str = "") -> TouchEntry:
        """Record that one session changed one file, attributing it exactly."""
        return self.record(
            PathTouched(actor=actor, at=utc_now(), path=str(path), digest=digest)
        )

    def contested(
        self, actor: ActorRef, path: Path, rivals: list[ActorRef], digest: str = ""
    ) -> TouchEntry:
        """Record a change nothing could attribute, with every name it could be."""
        return self.record(
            PathContested(
                actor=actor,
                at=utc_now(),
                path=str(path),
                digest=digest,
                rivals=rivals,
            )
        )

    def locked(self, actor: ActorRef, prefix: Path) -> TouchEntry:
        """Record that one session has taken everything beneath a prefix."""
        return self.record(PrefixLocked(actor=actor, at=utc_now(), path=str(prefix)))

    def released(self, actor: ActorRef, prefix: Path) -> TouchEntry:
        """Record that one session has given a prefix back, if it held it."""
        return self.record(PrefixReleased(actor=actor, at=utc_now(), path=str(prefix)))

    def vacated(self, actor: ActorRef, claim: Claim) -> TouchEntry:
        """Record that the path under one claim has gone, ending the claim."""
        return self.record(
            PathVacated(actor=actor, at=utc_now(), path=claim.path, prefix=claim.prefix)
        )

    def claims(self) -> list[Claim]:
        """Every claim standing, whether or not the session holding it is alive."""
        return [folded_claim(held) for held in store.claims(self.root)]

    def held(self, live: list[str]) -> list[Claim]:
        """Every claim whose holder is still on the roster, newest first.

        Expiry is the roster's rather than a timeout's. A claim outliving its
        session would have to be released by somebody, and the somebody who
        would have to remember is exactly the session that has stopped.
        """
        return [folded_claim(held) for held in store.held(self.root, live)]

    def covering(self, path: Path, live: list[str]) -> list[Claim]:
        """Every live claim a write to this path would land under."""
        return [folded_claim(held) for held in store.covering(self.root, path, live)]
