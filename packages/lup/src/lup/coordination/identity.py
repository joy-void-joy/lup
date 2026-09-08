# lup: ignore[constant-declaration]
# The environment name and the stream's file name are a handshake between a
# launcher, a hook and a tool server in three different processes, so a caller
# free to choose them is a caller free to open a session nobody can address.
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

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter
from pydantic_settings import BaseSettings

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.coordination.refs import ActorRef
from lup.types import EnvVars

MEMBER_ENV = "LUP_COORDINATION_MEMBER"
"""Environment variable naming the durable id a launcher minted for a session."""

MEMBER_KIND = "session"
"""What a repository peer is on the roster, beside spawned workers and the user.

One kind for every session, rather than a kind per role. A role restricts
tools, specialises a prompt, or separates contexts, and none of those is an
identity — so what distinguishes two peers is what each says it is doing,
which is its description, not a word baked into its address.
"""

NAMES_FILE = "names.jsonl"


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

    The consumer side of what :func:`member_environment` writes, spelled once
    so the process that mints an id and the process that answers to it cannot
    drift — the arrangement :class:`~lup.workspace.context.SessionEnv` uses,
    for the same reason.
    """

    member_id: str = Field(default="", validation_alias=MEMBER_ENV)


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


def member_environment(member_id: str) -> EnvVars:
    """Declare one session's coordination id, or clear it with an empty value.

    Cleared rather than omitted for the reason the agent identity is: runtimes
    merge a session's environment over the launching process's, so an operator
    with this exported would otherwise hand their own address to every session
    they start, and two peers would answer to one id.
    """
    return {MEMBER_ENV: member_id}


def member_ref(member_id: str) -> ActorRef:
    """The roster address one session is reached at."""
    return ActorRef(kind=MEMBER_KIND, id=member_id)


def derived_cli_name(worktree: Path) -> str:
    """What to call a session that was not given a name, from where it is working.

    The worktree, because that is what a person watching several sessions is
    actually distinguishing between — which branch is this one on — and it is
    the one fact a session has before it has done anything. Two sessions in one
    worktree collide on the name and not on the id, which is the right way
    round: the collision is visible, and renaming is one call.
    """
    return worktree.name


class MemberNames:
    """Every name every member has answered to, folded from the record.

    Kept beside the roster rather than on it, because the two are read on
    different schedules and one of them is history. A roster fold answers who
    is present; this answers what a name meant, including names nothing is
    called any more.
    """

    def __init__(self, path: Path) -> None:
        self.stream: Stream[MemberNamed] = Stream(path, NAME_ADAPTER)

    def rename(self, member_id: str, cli_name: str) -> MemberNamed:
        """Record what this member is called from now on."""
        record = MemberNamed(id=member_id, cli_name=cli_name, at=utc_now())
        self.stream.append(record)
        return record

    def named(self) -> list[MemberNamed]:
        """Every naming ever recorded, oldest first."""
        return [pair.item for pair in self.stream.read_from(0)]

    def current(self, member_id: str) -> str:
        """What this member is called now, or nothing where it was never named."""
        found = [record for record in self.named() if record.id == member_id]
        return found[-1].cli_name if found else ""

    def resolve(self, cli_name: str) -> str:
        """The member a name reaches, taking the most recent claim on it.

        Newest wins rather than first, because a name is a handle and handles
        get reused: a session that took a name its predecessor released is the
        session somebody typing that name means. An older binding still
        resolves for as long as nothing else claims it, which is the whole
        point of keeping the record — a reference written down before a rename
        goes on working.
        """
        found = [record for record in self.named() if record.cli_name == cli_name]
        return found[-1].id if found else ""
