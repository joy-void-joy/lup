# lup: ignore[constant-declaration]
# The environment names are a handshake between a launcher, a hook and a tool
# server in three different processes, so a caller free to choose them is a
# caller free to open a session nobody can address.
"""Who a session is on its repository's roster, and what it is called.

Two facts, deliberately separated, because they change on different schedules
and answer different questions. The **id** is minted once and never moves: it
is what mail is addressed to, what a touch is attributed to, and what a
restart reattaches by. The **name** is what a person types and reads, and a
session may rename itself whenever what it is doing changes.

Renames are journaled rather than overwritten, so a name somebody wrote down
an hour ago still reaches the session it named. That is what the stream buys
over a field: a roster that only held the current name would silently misroute
every reference taken before the rename, and there is no error a sender could
be shown, because the name they used was correct when they read it.

**A launcher declares the id; a session without one derives it.** The
environment variable is set by the process that minted the id and can prove it,
which mirrors ``LUP_AGENT_IDENTITY`` and works for the same reason: a hook
script is spawned by the runtime CLI with the CLI's own environment, so an
agent exporting this inside a shell call cannot reach the hook that reads it.
A session nobody launched that way — a bare ``claude`` in a worktree — has the
plugin and no launcher, so it falls back to the identity its own runtime
already gave it. It is a full peer that cannot prove who started it, which is
the honest description and costs it nothing on the roster.

Nothing here reads a runtime's environment for that fallback. Which variable
carries a session's own id is one runtime's spelling, so it arrives as an
argument from the adapter that knows it, and this module stays the vocabulary
both halves share.
"""

from collections.abc import Collection
from datetime import datetime
from itertools import count
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter
from pydantic_settings import BaseSettings

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.coordination.bare import store
from lup.coordination.bare.store import MEMBER_KIND, NAMES_FILE
from lup.coordination.refs import ActorRef
from lup.types import EnvVars

MEMBER_ENV = "LUP_COORDINATION_MEMBER"
"""Environment variable naming the durable id a launcher minted for a session."""

NAME_ENV = "LUP_COORDINATION_NAME"
"""Environment variable naming what a launcher called the session it minted an id for.

Exported beside the id for the same reason: the runtime's own chrome shows a
name the launcher chose, and the roster has to answer to the same one, so the
choice is made once where both can read it rather than derived twice.
"""


class MemberNamed(BaseModel, frozen=True):
    """One member answering to one name, from this moment until it renames.

    Append-only, so the stream is the whole history of who was called what.
    Nothing revises a record: a rename is another record, and the fold is what
    decides which of them a reader is asking about.
    """

    id: str
    cli_name: str
    at: datetime


NAME_ADAPTER: TypeAdapter[MemberNamed] = TypeAdapter(MemberNamed)


class MemberEnv(BaseSettings):
    """The launcher's half of the identity contract, read from the environment.

    The consumer side of what :meth:`LaunchedMember.environment` writes,
    spelled once so the process that mints an id and the process that answers
    to it cannot drift — the arrangement
    :class:`~lup.workspace.context.SessionEnv` uses, for the same reason.
    """

    member_id: str = Field(default="", validation_alias=MEMBER_ENV)
    cli_name: str = Field(default="", validation_alias=NAME_ENV)


def session_cli_name() -> str:
    """What the launcher called this session, or blank where nothing launched it.

    Blank is a real answer: a session with the plugin and no launcher is named
    after its worktree when it joins, and nothing here has to invent one.
    """
    return MemberEnv().cli_name


def session_member_id(fallback: str = "") -> str:
    """The id this session is on the roster under, preferring the proven one.

    A launcher that minted an id and exported it is the strongest claim
    available: it set the variable in the environment the runtime CLI spawns
    hooks and tool servers with, so nothing the agent does inside a shell call
    can reach it. Where there is none, the caller's fallback stands — the
    identity that session's own runtime already gave it, which is honest about
    being unproven and is still stable for as long as the session lives.

    Empty means neither: a process that is not a session at all. Nothing joins
    a roster under an empty id, so the caller is left to decide, rather than
    being handed a mint that would put a new member on the roster every call.
    """
    return MemberEnv().member_id or fallback


def mint_member_id() -> str:
    """A durable id for one session, unique without asking anybody.

    Minted rather than derived from the worktree, because two sessions in one
    worktree are two peers and a derived id would make them one — which is the
    case a repository-wide roster exists to hold. The worktree still names the
    session; it just does not identify it.
    """
    return uuid4().hex[:12]


class LaunchedMember(BaseModel, frozen=True):
    """The identity a launcher mints for one session: its id and what it is called.

    Minted together because they are exported together and read together: the
    tool server joins under the id and answers to the name, and the runtime's
    chrome shows the name, so a launcher holding them as two values would be
    the one place they could disagree.
    """

    member_id: str
    cli_name: str

    def environment(self) -> EnvVars:
        """Declare this session's coordination identity for the processes it starts.

        Set rather than omitted for the reason the agent identity is: runtimes
        merge a session's environment over the launching process's, so an
        operator with these exported would otherwise hand their own address
        to every session they start, and two peers would answer to one id.
        """
        return {MEMBER_ENV: self.member_id, NAME_ENV: self.cli_name}


def unique_cli_name(wanted: str, taken: Collection[str]) -> str:
    """*wanted* where nobody else answers to it, else the first free numbered form.

    Numbered rather than refused, because the name is a default nobody chose:
    two sessions opened in one worktree are two peers and both are called
    after it, and the second has to be reachable by a name that is not the
    first's. A name somebody chose is refused instead, by the caller that
    knows it was chosen.
    """
    if wanted not in taken:
        return wanted
    return next(
        candidate
        for candidate in (f"{wanted}-{ordinal}" for ordinal in count(2))
        if candidate not in taken
    )


class NameTakenError(ValueError):
    """Raised when a session asks for a name a live session already answers to.

    A refusal rather than a silent suffix, because the name was chosen: a
    session renaming itself to what another live session is called would make
    the roster print one address for two peers, which is the collision the
    numbered default exists to rule out.
    """

    def __init__(self, cli_name: str, holder_id: str) -> None:
        super().__init__(
            f"{cli_name!r} is what session {holder_id} is called; a live "
            "session's name reaches it, so choose another"
        )
        self.cli_name = cli_name
        self.holder_id = holder_id


def member_ref(member_id: str) -> ActorRef:
    """The roster address one session is reached at."""
    return ActorRef(kind=MEMBER_KIND, id=member_id)


def derived_cli_name(worktree: Path) -> str:
    """What to call a session that was not given a name, from where it is working.

    The worktree, because that is what a person watching several sessions is
    actually distinguishing between — which branch is this one on — and it is
    the one fact a session has before it has done anything. Two sessions in one
    worktree want the same one, and the second is numbered by
    :func:`unique_cli_name` when it joins, so the address a listing prints for
    either reaches that one and not the other.
    """
    return worktree.name


class MemberNames:
    """Every name every member has answered to, folded from the record.

    Kept beside the roster rather than on it, because the two are read on
    different schedules and one of them is history. A roster fold answers who
    is present; this answers what a name meant, including names nothing is
    called any more.

    The fold is :mod:`lup.coordination.bare.store`'s, because a hook and the
    permission dispatcher resolve the same names without being able to import
    this. What is here is the writer and the vocabulary a typed caller reads.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.stream: Stream[MemberNamed] = Stream(root / NAMES_FILE, NAME_ADAPTER)

    def rename(self, member_id: str, cli_name: str) -> MemberNamed:
        """Record what this member is called from now on."""
        record = MemberNamed(id=member_id, cli_name=cli_name, at=utc_now())
        self.stream.append(record)
        return record

    def named(self) -> list[MemberNamed]:
        """Every naming ever recorded, oldest first."""
        return [
            MemberNamed(
                id=record["id"],
                cli_name=record["cli_name"],
                at=store.spoken_at(record["at"]) or utc_now(),
            )
            for record in store.named(self.root)
        ]

    def latest(self, member_id: str) -> MemberNamed | None:
        """This member's newest naming, or nothing where it was never named."""
        found = [record for record in self.named() if record.id == member_id]
        return found[-1] if found else None

    def current(self, member_id: str) -> str:
        """What this member is called now, or nothing where it was never named."""
        return store.called(self.root).get(member_id, "")

    def resolve(self, cli_name: str, live: Collection[str] = ()) -> str:
        """The member a name reaches: the live one that claimed it last, else the last.

        A name is a handle and handles get reused, so among the sessions that
        ever answered to one, the one somebody typing it means is the one
        still here — and where two are, the one that claimed it most recently.
        Only where nobody live ever held it does the last claimant of all
        stand, so a reference written down before a rename or a departure
        still resolves to the session it named, and the sender is told what
        became of it rather than that the name means nothing.
        """
        found = [
            record["id"]
            for record in store.named(self.root)
            if record["cli_name"] == cli_name
        ]
        present = [member_id for member_id in found if member_id in live]
        return (present or found)[-1] if found else ""

    def called(self, live: Collection[str], except_id: str = "") -> list[MemberNamed]:
        """The current naming of every live member but one.

        The names a newcomer must not take: whatever every other live session
        currently answers to. A name a live session renamed away from is not
        here and may be taken — the record still resolves it for anyone who
        wrote it down, live holders first.
        """
        return [
            latest
            for member_id in live
            if member_id != except_id
            for latest in [self.latest(member_id)]
            if latest is not None
        ]
