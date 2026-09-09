# lup: ignore[constant-declaration]
# The names here are where a hook writes what it saw and a console reads it,
# in two processes that share no import — an identity of this layout rather
# than a choice a caller can make.
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
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.coordination.refs import ActorRef

TOUCHES_FILE = "touches.jsonl"
WINDOWS_DIR = "windows"


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

    def covers(self, candidate: str) -> bool:
        """Whether a path about to be written falls under this claim."""
        if not self.prefix:
            return candidate == self.path
        return candidate == self.path or candidate.startswith(self.path + "/")

    def subject(self) -> str:
        """What the fold keys this claim by, which a lock and a touch differ in.

        A prefix and an exact path can be spelled identically and mean
        different things — locking `src/lup` is not touching a file of that
        name — so the kind is part of the key rather than something a later
        record could silently convert.
        """
        return f"{'under' if self.prefix else 'at'} {self.path}"


class TouchRecord(BaseModel, frozen=True):
    """One thing that happened to a claim, and what it makes of that claim.

    The fold asks each record what the claim becomes rather than testing which
    record it is holding, the way the roster's does — so a third thing that can
    happen to a claim answers for itself instead of being dropped by a filter
    nobody extended.
    """

    actor: ActorRef
    at: datetime
    path: str

    def claim(self) -> Claim:
        """The claim this record is about, as a bare shape the fold keys by."""
        return Claim(path=self.path, holders=[self.actor], at=self.at)

    def applied(self, standing: "Claim | None") -> "Claim | None":
        """The claim as this record leaves it, or None where it releases one."""
        raise NotImplementedError


class PathTouched(TouchRecord, frozen=True):
    """One session changed one file, and it is known which session.

    Replaces whatever stood before it rather than joining it. A named-path
    edit attributes exactly, so it is the record that settles a claim nothing
    else could attribute — including one that had been left contested.
    """

    type: Literal["touched"] = "touched"
    digest: str = ""

    def claim(self) -> Claim:
        return Claim(
            path=self.path, holders=[self.actor], digest=self.digest, at=self.at
        )

    def applied(self, standing: "Claim | None") -> "Claim | None":
        return self.claim()


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

    def claim(self) -> Claim:
        return Claim(
            path=self.path,
            holders=[self.actor, *self.rivals],
            digest=self.digest,
            at=self.at,
        )

    def applied(self, standing: "Claim | None") -> "Claim | None":
        return self.claim()


class PrefixLocked(TouchRecord, frozen=True):
    """One session took a prefix deliberately, ahead of touching anything in it.

    The case observation cannot reach. An agent about to rewrite a package has
    changed none of it yet, and the moment worth telling anybody about is
    before the first write rather than after it.
    """

    type: Literal["locked"] = "locked"

    def claim(self) -> Claim:
        return Claim(path=self.path, prefix=True, holders=[self.actor], at=self.at)

    def applied(self, standing: "Claim | None") -> "Claim | None":
        return self.claim()


class PrefixReleased(TouchRecord, frozen=True):
    """One session gave a prefix back, which only a holder of it can do.

    Checked here rather than at the writer, because the record is the whole
    history and a reader replaying it has to reach the same answer as the
    process that wrote it. A release by somebody who never held it says
    nothing, which is what leaves the claim standing rather than letting one
    session unlock another's work by asking.
    """

    type: Literal["released"] = "released"

    def claim(self) -> Claim:
        return Claim(path=self.path, prefix=True, holders=[self.actor], at=self.at)

    def applied(self, standing: "Claim | None") -> "Claim | None":
        if standing is None:
            return None
        held = [holder.id for holder in standing.holders]
        return None if self.actor.id in held else standing


type TouchEntry = PathTouched | PathContested | PrefixLocked | PrefixReleased
"""What the claim record carries: two ways to take one, and one way to give it back.

A touch and a contest are the same event seen with and without an attribution,
which is why they are separate records rather than one carrying an optional
list — a reader deciding whether to write wants "somebody, and we know who"
told apart from "somebody, and nobody could tell" without inspecting a field's
emptiness.
"""

TOUCH_ADAPTER: TypeAdapter[TouchEntry] = TypeAdapter(TouchEntry)


class Touches:
    """Every claim this repository's sessions hold, folded from the record.

    Holds nothing and remembers nothing: a hook writing a touch, a console
    listing them, and a session asking whether it may write all fold the same
    file, so none of them has to be running for the others to answer.
    """

    def __init__(self, path: Path) -> None:
        self.stream: Stream[TouchEntry] = Stream(path, TOUCH_ADAPTER)

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

    def claims(self) -> list[Claim]:
        """Every claim standing, whether or not the session holding it is alive."""
        # lup: ignore[empty-collection] — a fold whose every step reads what the
        # steps before it left, which is the one shape a comprehension cannot
        # spell: a release answers against the claim an earlier record created
        standing: dict[str, Claim | None] = {}
        for offset in self.stream.read_from(0):
            record = offset.item
            subject = record.claim().subject()
            standing[subject] = record.applied(standing.get(subject))
        return [claim for claim in standing.values() if claim is not None]

    def held(self, live: list[str]) -> list[Claim]:
        """Every claim whose holder is still on the roster, newest first.

        Expiry is the roster's rather than a timeout's. A claim outliving its
        session would have to be released by somebody, and the somebody who
        would have to remember is exactly the session that has stopped.
        """
        return sorted(
            (
                claim.model_copy(
                    update={
                        "holders": [
                            holder for holder in claim.holders if holder.id in live
                        ]
                    }
                )
                for claim in self.claims()
                if any(holder.id in live for holder in claim.holders)
            ),
            key=lambda claim: claim.at,
            reverse=True,
        )

    def covering(self, path: Path, live: list[str]) -> list[Claim]:
        """Every live claim a write to this path would land under."""
        return [claim for claim in self.held(live) if claim.covers(str(path))]
