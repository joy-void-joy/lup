"""Everyone working in one repository, whichever worktree they are in.

A cohort is what one process assembled; this is the population nobody
assembled. Its members are sessions somebody started at different times in
different checkouts, and what makes them one population is the repository —
so joining is something a session does to itself rather than something done to
it, and leaving is too.

Built over the same roster, mail and journal a cohort uses, at the repository's
own directory. That is the whole of the reuse and it is the point: a message to
a peer and a message to a spawned worker land in the same inbox, are read by
the same fold, and are consumed the same way, so there is one delivery path to
get right rather than two that agree until they do not.

What this adds is the vocabulary a repository needs and a run does not — a
session names itself and may rename, says what it is doing as that changes, and
is addressed by that name as readily as by its id. A run's members are named by
the run; peers name themselves, and a name somebody wrote down has to go on
working after the session behind it has moved on.

Everything derived at the read — a row the pulse retired, a description a
rewind unsaid, a claim whose holders have stopped — is derived in
:mod:`lup.coordination.bare.store`, which a hook and the permission
dispatcher read the same store through. What is here is the vocabulary: the
verbs a session uses on the roster, and the rows a surface renders.

**A name is settled against every other member's**, which is the one decision
a member cannot take from its own file alone. Joining and renaming take the
store's roster lock for exactly that: long enough to read the directory and
rename one file, and held for nothing else a member writes.
"""

import fcntl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, computed_field

from lup.channels.models import Door, utc_now
from lup.coordination.bare import store
from lup.coordination.cohort import ActorCohort
from lup.coordination.identity import (
    LaunchedMember,
    NameTakenError,
    derived_cli_name,
    member_ref,
    mint_member_id,
    session_cli_name,
    unique_cli_name,
)
from lup.coordination.mail import ActorDelivery
from lup.coordination.meeting import coordination_root
from lup.coordination.peers import USER_KIND, user_peer
from lup.coordination.pulse import Pulse
from lup.coordination.refs import ActorRef
from lup.coordination.roster import Delivery, Roster, SpawnedActor, folded_member
from lup.coordination.touches import Claim, folded_claim


class Retention(BaseModel, frozen=True):
    """How long a session that has stopped stays in a listing read with no arrival.

    A session reading the roster is told about the departures it was here for,
    which its own arrival bounds. A console has no arrival, so it is told about
    the recent ones instead, and this says how recent: long enough that a
    person coming back to a terminal finds out who left since they looked,
    short enough that a roster read a month on is not a history of everyone.

    The default is the store's own window, not a second figure beside it: the
    sweep deletes a departed stub past it, so a listing reaching further back
    would be asking for rows nothing keeps.
    """

    departed_seconds: float = store.DEPARTED_SECONDS

    def since(self, now: datetime) -> datetime:
        """The moment before which a departure is history rather than news."""
        return now - timedelta(seconds=self.departed_seconds)


class PeerDepartedError(LookupError):
    """Raised when a message is addressed to a session that has stopped.

    Raised rather than queued, because mail to a session that will never read
    it is a message the sender goes on believing was delivered. What the row
    says about the departure travels with it, so the surface reporting this
    can say when the session left and what it concluded.
    """

    def __init__(self, member: SpawnedActor, cli_name: str) -> None:
        left = member.heard.isoformat() if member.heard is not None else "unknown"
        outcome = member.summary or member.error
        super().__init__(
            f"{cli_name or member.actor.id} left at {left}"
            + (f": {outcome}" if outcome else "")
        )
        self.member = member
        self.cli_name = cli_name


class PeerView(BaseModel, frozen=True):
    """One row of a repository roster, as a person or an agent reads it.

    The name and the member are carried separately rather than merged, because
    a member with no name is a real state — a session that joined before
    anything named it — and a row that invented one would be a row an operator
    could type and nothing would answer.
    """

    member: SpawnedActor
    cli_name: str = ""

    holding: list[str] = []
    """What this session's calls have actually claimed, as the fold spells it.

    Observed rather than declared, which is the whole reason it rides beside
    ``doing``: a description is what a session said about itself whenever it
    last said anything, and a reader deciding whether it is safe to write
    needs what that session touched. Empty is the honest state for a session
    that has changed nothing yet.
    """

    contested: list[str] = []
    """The claims here that another live session also holds.

    Separate from ``holding`` rather than a flag inside it, because the two
    answer different questions — what this session has, and what it does not
    have to itself — and a reader about to write needs the second only when it
    is not empty. A contested claim appears on both sessions' rows, which is
    the honest rendering of a path two members' own files both claim.
    """

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

    def __init__(
        self,
        root: Path,
        pulse: Pulse = Pulse(),
        retention: Retention = Retention(),
    ) -> None:
        self.root = coordination_root(root)
        self.pulse = pulse
        self.retention = retention

    @cached_property
    def roster(self) -> Roster:
        """The record of who is here, opened to read it and for nothing else.

        The cohort holds the same directory, but reaching the record through
        the cohort opens it, and opening writes. Every read here goes through
        this instead, so a launcher asking which names are taken, or a listing
        of a repository nobody has joined, finds what is there and creates
        nothing.
        """
        return Roster(self.root)

    @cached_property
    def cohort(self) -> ActorCohort:
        """The roster, mail and journal, opened the first time one is asked for.

        Lazy because opening a cohort *writes*: it publishes the manifest that
        makes the directory findable and joins the person onto the roster. That
        is right when a caller has asked to reach somebody and wrong as a side
        effect of construction — a session assembling its tool groups, or a
        test building a registry, would otherwise create this repository's
        coordination store by mentioning it.

        Cached because the roster's own idempotence is per member and not per
        call: re-opening costs a fold and a lock each time, and every verb here
        goes through it.
        """
        return ActorCohort(
            self.root,
            run_id=self.root.parents[1].name,
            description="every session working in this repository",
        )

    @contextmanager
    def naming_settled(self) -> Iterator[None]:
        """Hold the one lock a member cannot decide its own name without.

        Every other write a member makes is about itself and is taken under
        its own lock. A name is decided against every other member's, so two
        sessions choosing at once would both read the same directory and both
        take the same name — which is precisely the collision the numbered
        default exists to rule out.

        Held for a read of the members directory and one rename, and released
        whatever happens inside: a refused name must not leave the store's
        lock standing for the next session to wait on.
        """
        lock = self.root / store.ROSTER_LOCK
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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

        The name is settled here too, and settled once: a session keeps what
        it is called across every rejoin. One given a name — by this call, or
        by whoever launched it — answers to that; one given nothing is called
        after its worktree, numbered where another live session already is,
        so the address a listing prints for each of two sessions in one
        checkout reaches that one. A chosen name a live session already
        answers to is refused rather than numbered, because the caller meant
        it, and the refusal comes before the arrival so a refused join leaves
        no row behind.

        The arrival and the naming happen under the store's roster lock, so
        two sessions starting together cannot read the same set of taken names
        and both take the free one.
        """
        with self.naming_settled():
            current = self.standing_name(member_id)
            taken = self.names_taken(except_id=member_id)
            if cli_name and cli_name != current and cli_name in taken:
                raise NameTakenError(cli_name, taken[cli_name])
            peer = member_ref(member_id)
            self.cohort.roster.joined(
                peer,
                task=f"working in {worktree}",
                delivery=delivery,
                worktree=str(worktree),
            )
            chosen = (
                cli_name
                or current
                or unique_cli_name(
                    session_cli_name() or derived_cli_name(worktree), taken
                )
            )
            if chosen != current:
                self.record_name(member_id, chosen)
            return peer

    def rename(self, member_id: str, cli_name: str) -> None:
        """Record what this session is called from now on, keeping the old name.

        The old name stays on the member's own file, so a reference somebody
        wrote down before the rename goes on reaching this session until
        another one claims that name. A name a live session currently answers
        to is refused, because the roster would then print one address for two.
        """
        with self.naming_settled():
            taken = self.names_taken(except_id=member_id)
            if cli_name in taken:
                raise NameTakenError(cli_name, taken[cli_name])
            self.record_name(member_id, cli_name)

    # lup: ignore[dict-str-payload] — keyed by the name a session answers to,
    # whose value is the member id holding it: two spellings of an identity
    # rather than an open payload
    def names_taken(self, except_id: str = "") -> dict[str, str]:
        """Every name a live session other than this one currently answers to.

        Current names rather than every name ever claimed: a name its holder
        has renamed away from is free for somebody else to take, and goes on
        reaching the old holder only until they do. A departed session's name
        is free for the same reason — it is not there to be confused with.
        """
        live = self.live_ids()
        return {
            name: member_id
            for member_id, name in store.called(self.root).items()
            if member_id != except_id and member_id in live
        }

    def record_name(self, member_id: str, cli_name: str) -> None:
        """Append one name to this member's own file, under that member's lock."""
        store.revised(
            self.root,
            store.session_actor(member_id),
            lambda member: store.renamed(member, cli_name),
        )

    def standing_name(self, member_id: str) -> str:
        """What this session is called on a file still under ``members/``.

        Deliberately blind to the departed, which is what makes a rejoin after
        a departure name itself again. The stub a departure leaves keeps the
        name for whoever reads *that* row, and a fresh file carrying no name
        because a stub beside it had one would be a session nothing addresses.
        """
        found = store.read_member(
            store.member_path(self.root, store.session_actor(member_id)), running=True
        )
        return store.current_name(found) if found is not None else ""

    def called(self, member_id: str) -> str:
        """What this session is called now, wherever its file sits.

        The departed included, because a surface reporting who left has the id
        and wants the name — and a name a live session has since taken reaches
        that one, which is why this is read for rendering and never for
        deciding what is free.
        """
        member = store.member_of(self.root, store.session_actor(member_id))
        return store.current_name(member) if member is not None else ""

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
        A name resolves to the live session answering to it ahead of any that
        has stopped, so a name reused after a departure reaches the newcomer.
        """
        return self.cohort.reaching(self.answering(spelling) or spelling)

    def answering(self, cli_name: str) -> str:
        """The member id one name reaches, blank where no member claimed it.

        Every claim on the name, newest first, live ones ahead of stopped
        ones. A name somebody wrote down before a rename goes on reaching the
        member that answered to it, and a name reused after a departure
        reaches whoever holds it now.
        """
        if not cli_name:
            return ""
        claims = [
            claiming["id"]
            for claiming in reversed(store.naming(self.root))
            if claiming["cli_name"] == cli_name
        ]
        live = self.live_ids()
        return next(
            (member_id for member_id in claims if member_id in live),
            claims[0] if claims else "",
        )

    def row(self, member_id: str, now: datetime | None = None) -> SpawnedActor | None:
        """One session as the record and the pulses say, or nothing where none stands."""
        return next(
            (member for member in self.present(now) if member.actor.id == member_id),
            None,
        )

    def listing(self, since: datetime | None = None) -> list[PeerView]:
        """The sessions here, and those that stopped since a moment the reader names.

        The sessions, which is one member short of the roster: the person is on
        it and is not a session. They need no listing either, being reachable
        at the same word in every repository — where a session's address is
        exactly what a reader cannot know without asking.

        A session that stopped is listed only back to *since*, and says so on
        its row. A session reading the roster names its own arrival, because
        what left before it came is history it could never have written to;
        a console reading with no arrival names the retention window. Naming
        nothing lists the live rows alone, which is what a roster a month old
        should read as: who is here, not everyone who ever was.

        Each row carries what its session is *holding* as well as what it says
        it is doing, because the question this listing is read to answer — is
        it safe to start here — is one a self-description cannot answer. The
        claims are folded once for the whole roster rather than once per row,
        so a listing costs the same read whatever the population.
        """
        claims = self.held()
        names = store.called(self.root)

        def told(member: SpawnedActor) -> bool:
            """Whether this row is news to a reader whose look starts at *since*."""
            if member.running:
                return True
            heard = member.heard
            return since is not None and heard is not None and heard >= since

        def row(member: SpawnedActor) -> PeerView:
            """One session, with what it is observed to hold folded in."""
            held = [
                claim
                for claim in claims
                if any(holder.id == member.actor.id for holder in claim.holders)
            ]
            return PeerView(
                member=member,
                cli_name=names.get(member.actor.id, ""),
                holding=[claim.subject() for claim in held],
                contested=[claim.subject() for claim in held if len(claim.holders) > 1],
            )

        return [row(member) for member in self.present() if told(member)]

    def recent(self, now: datetime | None = None) -> list[PeerView]:
        """The listing a reader with no arrival of its own gets: the retention window."""
        return self.listing(since=self.retention.since(now or utc_now()))

    def present(self, now: datetime | None = None) -> list[SpawnedActor]:
        """Every member as the files and their modification times say, live ones first.

        The shared fold's, so a row the prompt hook reads as gone and a row a
        tool call reads as gone are the same row. Only the window is this
        caller's, which is what a test moves.
        """
        return [
            folded_member(member)
            for member in store.present(
                self.root, now, window=self.pulse.stale_after_seconds
            )
            if store.text(member.get("kind")) != USER_KIND
        ]

    def beat(self, member_id: str) -> None:
        """Record that this session is here now."""
        store.beat(self.root, store.session_actor(member_id))

    def lapsed(self, now: datetime | None = None) -> list[SpawnedActor]:
        """Every session a sweep would retire: still listed, and no longer heard.

        What a console prints before it sweeps, which is why it is read rather
        than derived from a second reading of the record — there is no record
        beside the file, and the file's own time is the whole of the answer.
        """
        return [
            folded_member(member)
            for member in store.lapsed(self.root, now, self.pulse.stale_after_seconds)
            if store.text(member.get("kind")) != USER_KIND
        ]

    def sweep(
        self, now: datetime | None = None, by: ActorRef = user_peer()
    ) -> list[SpawnedActor]:
        """Move what the read already derives, and delete what nobody reads.

        A member whose pulse stopped has its file moved to the departed, so a
        reader that lists the directory agrees with one that stats the file; a
        departed stub past the retention window is deleted, which is what
        keeps the store the size of the population rather than of its history.
        A session that beats again after this re-joins on its next call, which
        the roster's own idempotence allows once the file has moved.

        A claim needs no sweeping and *by* names nobody: a claim stands or it
        does not, and the filesystem is what says which. Whoever swept is a
        parameter the surfaces still pass and this no longer has a record to
        attribute to them.
        """
        return [
            folded_member(member)
            for member in store.swept(self.root, now, self.pulse.stale_after_seconds)
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

        A member that has stopped is the other answer, and that one raises:
        the address was right, the session is gone, and queuing for it would
        tell the sender nothing while the message waits for nobody.
        """
        member = self.address(to)
        if member is None:
            return None
        standing = self.row(member.id)
        if standing is not None and not standing.running:
            raise PeerDepartedError(standing, self.called(member.id))
        self.cohort.say(
            member, text, redirect=redirect, door=door, in_reply_to=in_reply_to
        )
        return member

    def notify(self, text: str, door: Door = Door.AGENT, by: str = "") -> None:
        """State something true for every session here, and for whoever starts next.

        A notice is state rather than mail: it is read at the head of every
        prompt for as long as it stands, so a session opened tomorrow reads it
        at its first. Whoever is working is told now as well, because a fact
        worth stating is worth hearing before the turn they are in ends.
        """
        self.cohort.notify(text, door=door, by=by)

    def waiting(self, member_id: str) -> ActorDelivery:
        """What is queued for this session, consuming none of it."""
        return self.cohort.mail.waiting(member_ref(member_id))

    def take(self, member_id: str) -> ActorDelivery:
        """Take everything queued for this session, and record it as handed over.

        The delivery is returned rather than the bare messages so a caller
        holds what was consumed: the files it names have been deleted, so a
        caller that dropped the result has lost the mail rather than deferred
        it, and the type it gets back is the one it would have peeked at.
        """
        inbox = self.cohort.inbox(member_ref(member_id))
        delivery = inbox.waiting()
        inbox.commit(delivery)
        return delivery

    def live_ids(self) -> list[str]:
        """Every member still working here, by id, which is what expires a claim.

        A claim is alive while its holder is, so this is the whole of the
        expiry rule: no timeout to tune, no release to forget, and the failure
        mode is a session that stopped taking its own claims with it.
        """
        return [member.actor.id for member in self.present() if member.running]

    def held(self) -> list[Claim]:
        """Every claim a live session is holding, newest first."""
        return [folded_claim(row) for row in store.held(self.root, self.live_ids())]

    def holding(self, path: Path) -> list[Claim]:
        """Every live claim a write to this path would land under."""
        return [
            folded_claim(row)
            for row in store.covering(self.root, path, self.live_ids())
        ]

    def revise(
        self, member_id: str, revise: Callable[[store.Member], store.Member]
    ) -> bool:
        """Change what one member's own file says about what it holds.

        Under that member's own lock, because its tool server, its prompt hook
        and the permission dispatcher recording what a command just changed
        are three processes revising one file. Nothing is written for a member
        that has no file: a revision of nobody would put a row on the roster
        that never joined.
        """
        return (
            store.revised(self.root, store.session_actor(member_id), revise) is not None
        )

    def touched(self, member_id: str, *paths: Path) -> None:
        """Record that this session changed exactly these files.

        A path claimed again replaces its earlier claim rather than joining
        it: what a claim carries is the state this session left the path in,
        and the older reading is what the newer write has just made wrong.
        """
        self.revise(
            member_id,
            lambda member: store.claimed(member, [str(path) for path in paths], False),
        )

    def lock(self, member_id: str, prefix: Path) -> Claim:
        """Take everything beneath a prefix, ahead of having touched any of it."""
        self.revise(
            member_id, lambda member: store.claimed(member, [str(prefix)], True)
        )
        return Claim(
            path=str(prefix), prefix=True, holders=[member_ref(member_id)], at=utc_now()
        )

    def holds(self, member_id: str, prefix: Path) -> bool:
        """Whether this session took exactly this prefix and still holds it."""
        return any(
            claim.prefix
            and claim.path == str(prefix)
            and any(holder.id == member_id for holder in claim.holders)
            for claim in self.held()
        )

    def release(self, member_id: str, prefix: Path) -> bool:
        """Give a prefix back, saying whether this session held it to give.

        Nothing is written for a prefix this session does not hold: a release
        by somebody else would take nothing off that session's own file, and
        the write would be a write of nothing having happened.
        """
        if not self.holds(member_id, prefix):
            return False
        return self.revise(member_id, lambda member: store.unclaimed(member, prefix))


def launched_member(root: Path) -> LaunchedMember:
    """The identity a launcher mints for the session it is about to open in *root*.

    The id is minted; the name is the worktree's, numbered where a live session
    of this repository is already called that, so the runtime's own chrome and
    the roster agree on a name that reaches this session and no other. Read
    without joining, because a launch that only generates has to leave the
    store as it found it — the session joins for itself once it is open.
    """
    peers = RepositoryPeers(root)
    return LaunchedMember(
        member_id=mint_member_id(),
        cli_name=unique_cli_name(derived_cli_name(root), peers.names_taken()),
    )
