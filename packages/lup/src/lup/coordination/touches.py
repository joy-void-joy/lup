"""What each session in this repository is holding, without anybody declaring it.

Nobody says what they are working on. Asking them to is asking for the one
thing an agent reliably forgets, and a declaration nobody keeps up to date is
worse than none — it reads as current and is not. So this is observed: a hook
watches what each session's calls actually change, and the record of that is
the claim, on that session's own file.

**A claim is evidence, not an assertion.** It carries the modification time of
the path it was taken over, so a reader can ask the filesystem whether it
still says anything: the path is gone, or somebody has written it since, or
what this session left is what stands there. Nothing has to be written to
retire one — which is what the vacating record used to be for, and why a claim
over a deleted worktree outlived the worktree.

**Two kinds.** A *touch* is an exact path some session changed. A *lock* is a
prefix a session took deliberately, for the case observation cannot reach — an
agent about to rewrite a package has touched none of it yet, and the
interesting moment is before the first write rather than after it. A lock is
exempt from the modification-time test, because a directory's time moves
whenever anything under it does, including by the holder.

**A claim can have more than one holder,** and that is derived rather than
guessed. Two live sessions whose own files both claim one path are contesting
it; nothing records that, and nothing has to name a rival at the moment of
writing — which is what a before-and-after comparison could never do honestly,
since it sees the change and cannot see who made it.

Expiry is the roster's: a claim is alive while the session holding it is, so
there is no timeout to tune and no release to forget.
"""

from datetime import datetime

from pydantic import BaseModel

from lup.channels.models import utc_now
from lup.coordination.bare import store
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
    """Every session whose own file claims it, more than one where two do.

    Ordered by arrival, so the first is whoever took it first.
    """

    at: datetime

    def subject(self) -> str:
        """What a reader keys this claim by, which a lock and a touch differ in.

        A prefix and an exact path can be spelled identically and mean
        different things — locking ``src/lup`` is not touching a file of that
        name — so the kind is part of the key.
        """
        return store.subject_of(self.path, self.prefix)

    def covers(self, candidate: str) -> bool:
        """Whether a path about to be written falls under this claim."""
        return store.covers(self.held(), candidate)

    def held(self) -> store.Held:
        """This claim as the shared reader spells it, so one answer serves both."""
        return store.Held(
            subject=self.subject(),
            path=self.path,
            prefix=self.prefix,
            holders=[
                store.Actor(kind=holder.kind, id=holder.id, round=holder.round)
                for holder in self.holders
            ],
            at=self.at.isoformat(),
        )


def folded_claim(row: store.Held) -> Claim:
    """One row of the shared reader, as a typed caller reads it.

    Total rather than validating, for the reason a member is: this is the read
    path a listing and a permission decision both go through, and a file a
    newer library wrote must leave an older one still able to say who holds
    what.
    """
    return Claim(
        path=row["path"],
        prefix=row["prefix"],
        holders=[
            ActorRef(
                kind=store.actor_kind(holder),
                id=store.actor_id(holder),
                round=store.actor_round(holder),
            )
            for holder in row["holders"]
            if store.actor_kind(holder) and store.actor_id(holder)
        ],
        at=store.spoken_at(row["at"]) or utc_now(),
    )
