"""Everyone working in one repository, whichever worktree they are in.

A cohort is what one process assembled; this is the population nobody
assembled. Its members are sessions somebody started at different times in
different checkouts, and what makes them one population is the repository —
so joining is something a session does to itself rather than something done to
it, and leaving is too.

Built over the same roster, mail and journal a cohort uses, at the repository's
own directory. That is the whole of the reuse and it is the point: a message to
a peer and a message to a spawned worker travel the same stream, are folded by
the same records, and are read by the same inbox, so there is one delivery path
to get right rather than two that agree until they do not.

What this adds is the vocabulary a repository needs and a run does not — a
session names itself and may rename, says what it is doing as that changes, and
is addressed by that name as readily as by its id. A run's members are named by
the run; peers name themselves, and a name somebody wrote down has to go on
working after the session behind it has moved on.
"""

from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, computed_field

from lup.channels.models import Door
from lup.coordination.cohort import ActorCohort
from lup.coordination.identity import (
    NAMES_FILE,
    MemberNames,
    derived_cli_name,
    member_ref,
)
from lup.coordination.mail import ActorDelivery
from lup.coordination.refs import ActorRef
from lup.coordination.roster import Delivery, SpawnedActor
from lup.coordination.store import coordination_root


class PeerView(BaseModel, frozen=True):
    """One row of a repository roster, as a person or an agent reads it.

    The name and the member are carried separately rather than merged, because
    a member with no name is a real state — a session that joined before
    anything named it — and a row that invented one would be a row an operator
    could type and nothing would answer.
    """

    member: SpawnedActor
    cli_name: str = ""

    @computed_field
    @property
    def address(self) -> str:
        """The spelling to send to: the name where there is one, else the id.

        Names first because that is what a person has: a roster is read to
        find somebody to talk to, and an id is what you fall back on when
        nothing has been called anything yet.
        """
        return self.cli_name or self.member.actor.id

    @computed_field
    @property
    def doing(self) -> str:
        """What this member is working on, falling back to what it arrived for.

        A member that has not described itself is not silent about its
        purpose — it joined for something — so the fallback is the task rather
        than a blank, and the blank only appears where there is genuinely
        nothing to say.
        """
        return self.member.description or self.member.task


class RepositoryPeers:
    """The roster of one repository, joined and read from any of its worktrees.

    Holds no session and spawns nobody: every method is a fold of files under
    the shared git directory, so a console, a hook and a tool server reading it
    at once see the same population and none of them has to be running for the
    others to work.
    """

    def __init__(self, root: Path) -> None:
        self.root = coordination_root(root)
        self.names = MemberNames(self.root / NAMES_FILE)

    @cached_property
    def cohort(self) -> ActorCohort:
        """The roster, mail and journal, opened the first time one is asked for.

        Lazy because opening a cohort *writes*: it publishes the manifest that
        makes the directory findable and joins the person onto the roster. That
        is right when a caller has asked to reach somebody and wrong as a side
        effect of construction — a session assembling its tool groups, or a
        test building a registry, would otherwise create this repository's
        coordination store by mentioning it.

        Cached because the roster's own idempotence is per record and not per
        call: re-opening costs a fold and a lock each time, and every verb here
        goes through it.
        """
        return ActorCohort(
            self.root,
            run_id=self.root.parents[1].name,
            description="every session working in this repository",
        )

    def join(
        self,
        member_id: str,
        worktree: Path,
        cli_name: str = "",
        delivery: Delivery = Delivery.MAILBOX,
    ) -> ActorRef:
        """Put this session on the roster, and hand back the address it answers to.

        Idempotent through the roster's own announce, so a session may call it
        on every coordination request rather than remembering whether it has
        joined — which is what lets a hook and a tool server in one session
        each arrive without a channel between them.

        The name is recorded separately and unconditionally, because renaming
        is not arriving: a session that joined this morning and renames at noon
        must not have that refused by the guard that stops it joining twice.
        """
        peer = member_ref(member_id)
        self.cohort.roster.joined(
            peer,
            task=f"working in {worktree}",
            delivery=delivery,
            worktree=str(worktree),
        )
        chosen = cli_name or derived_cli_name(worktree)
        if self.names.current(member_id) != chosen:
            self.names.rename(member_id, chosen)
        return peer

    def rename(self, member_id: str, cli_name: str) -> None:
        """Record what this session is called from now on, keeping the old name.

        The old binding stays in the record, so a reference somebody wrote down
        before the rename goes on reaching this session until another one
        claims that name.
        """
        self.names.rename(member_id, cli_name)

    def describe(self, member_id: str, description: str) -> None:
        """Record what this session is doing now, for whoever reads the roster."""
        self.cohort.roster.describes(member_ref(member_id), description)

    def leave(self, member_id: str, summary: str = "") -> None:
        """Record that this session has stopped, so nobody addresses it again."""
        self.cohort.roster.finished(member_ref(member_id), summary=summary)

    def address(self, spelling: str) -> ActorRef | None:
        """The member one spelling reaches: a name, an id, or a printed label.

        Names are resolved first and then handed to the same fold every other
        address goes through, so a name and an id cannot reach different
        members and a spelling one surface accepts is not one the next rejects.
        """
        resolved = self.names.resolve(spelling)
        return self.cohort.reaching(resolved or spelling)

    def listing(self) -> list[PeerView]:
        """Every session this repository holds, the ones still working first.

        The sessions, which is one member short of the roster: the person is on
        it and is not a session. They need no listing either, being reachable
        at the same word in every repository — where a session's address is
        exactly what a reader cannot know without asking.
        """
        return [
            PeerView(member=member, cli_name=self.names.current(member.actor.id))
            for member in self.cohort.live()
        ]

    def send(
        self,
        to: str,
        text: str,
        redirect: bool = False,
        door: Door = Door.AGENT,
        in_reply_to: str = "",
    ) -> ActorRef | None:
        """Post one message to whatever a sender spelled, or say it reached nobody.

        Returning the member rather than raising, because "nobody answers to
        that" is an answer a caller has to render differently on each surface —
        a tool says who is here, a console prints the roster — and a layer that
        chose for them would be choosing the wording of somebody else's error.
        """
        member = self.address(to)
        if member is None:
            return None
        self.cohort.say(
            member, text, redirect=redirect, door=door, in_reply_to=in_reply_to
        )
        return member

    def waiting(self, member_id: str) -> ActorDelivery:
        """What is queued for this session, consuming none of it."""
        return self.cohort.mail.waiting(member_ref(member_id))

    def take(self, member_id: str) -> ActorDelivery:
        """Take everything queued for this session, and record it as handed over.

        The delivery is returned rather than the bare messages so a caller
        holds what was consumed: the position has already moved past it, so a
        caller that dropped the result has lost the mail rather than deferred
        it, and the type it gets back is the one it would have peeked at.
        """
        inbox = self.cohort.inbox(member_ref(member_id))
        delivery = inbox.waiting()
        inbox.commit(delivery)
        return delivery
