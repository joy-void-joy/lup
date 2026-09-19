# lup: ignore[constant-declaration]
# Every name below is the store's own on-disk layout, which processes sharing
# no import must spell alike to meet at all — an identity of this store rather
# than a choice a caller can make. The typed writers import them from here
# instead of restating them, which is what a pin over two copies could only
# report after the fact.
"""The coordination store: one file per member, and everything else derived.

The store was append-only records folded whole by every reader on every call.
It answered who is here by replaying who had ever been here, which grew
without bound, kept sixteen rows for two live sessions, and could not be asked
anything the records had not been written to answer — so a claim over a path
in a deleted worktree stood until another record retired it, and a change no
window could attribute was recorded with a guess and a list of rivals.

It is state now. One file per member, written by nobody but that member's own
processes, and every relation between members derived at the read:

- **presence** is the member file's modification time. The owner touches it
  while it lives, and a file older than the window is a session that stopped
  without saying so. Nothing folds a departure to find out.
- **a claim** records the modification time of the path it was taken over. A
  reader stats that path: gone means vacant, newer than recorded means
  somebody else has written it since, and otherwise the claim stands. There is
  no vacating record to write and no rival to guess at.
- **a contest** is two live members' claims meeting on one path, which is a
  fact about their two files rather than a third record about both.
- **a name** is on the member that answers to it, with the names it answered
  to before beside it, so a reference somebody wrote down still resolves.

What is left is bounded by the population rather than by its history: a member
that stops takes its file to ``departed/``, and the sweep deletes that after
the retention window.

Three processes read this and no two of them share an import — the typed
library inside a session's tool server, the hooks a runtime spawns as bare
scripts, and the compiled permission dispatcher. So the reading is written
once, here, under the strictest of the three constraints: the standard library
alone, no pydantic, no ``lup``. The library imports it; each plugin ships this
package into ``hooks/runtime/``.

**Writing is the owner's.** A member file is revised under its own lock, by
whichever of that member's processes is revising it. The lock is per member
rather than per store, so two sessions never wait on each other, and a lock
taken to add one claim is held for one read and one rename.

**Nothing here raises.** Every reader is on a path where failing would cost
more than not answering: a prompt, a tool call, a permission decision. An
unreadable file reads as absent, a half-written one is never seen because
every write lands by rename, and a record that is not an object is passed
over.

``TypedDict`` throughout, and partial for every shape another process writes:
a field a newer library adds must not make its file unreadable here.
"""

import fcntl
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

STORE_DIR = "lup"
COORDINATION_DIR = "coordination"
"""Where one repository's peers meet, beneath its shared git directory.

Two worktrees that spelled this differently would coordinate with nobody, and
nothing anywhere would report the mismatch: both sessions work, and neither is
on the other's roster.
"""

MEMBERS_DIR = "members"
DEPARTED_DIR = "departed"
"""Who is here, and who was here recently enough to still be news.

Two directories rather than a flag inside one, because the question a reader
asks is almost always "who is here", and a listing that had to open every file
ever written to answer it is the fold this replaces.
"""

INBOX_DIR = "inbox"
NOTICES_DIR = "notices"
"""What is waiting for one member, and what is true for all of them.

Mail is addressed and consumed; a notice is neither. Keeping them apart is
what lets a notice be read by a member that did not exist when it was posted,
with no position for anybody to keep.
"""

LOOKS_DIR = "looks"
WINDOWS_DIR = "windows"
"""The two places one process keeps working state of its own under the store.

Declared beside the rest of the layout although nothing here reads either: the
dispatcher is the windows' only writer and reader, and the prompt fold is the
looks'. A name the layout carries in one place is a name a rename cannot leave
behind.
"""

ROSTER_LOCK = "roster.lock"
"""Taken for a join or a rename, and for nothing else.

Both decide a name against every other member's, which is the one question a
per-member lock cannot answer. Everything else a member writes is about itself
and is taken under its own lock, so the store-wide lock is held for as long as
it takes to read a directory and rename one file.
"""

MEMBER_KIND = "session"
"""What a repository peer is on the roster, beside spawned workers and the person.

The one kind that answers for its own presence, which is why the pulse applies
to it and to nothing else: a spawned agent is live because the process that
spawned it says so, and the person is never finished at all.
"""

STALE_AFTER_SECONDS = 120.0
"""How long a member's silence reads as absence.

A few beats wide rather than one, so a stalled scheduler or a slow disk is not
read as a departure; short because the roster is read to decide whether a path
is safe to write, and a dead session holding that decision open for an hour is
the failure this closes.
"""

DEPARTED_SECONDS = 18000.0
"""How long a member that stopped stays readable before the sweep deletes it.

Long enough that somebody back at a terminal finds out who left while they
were away, short enough that the store is the population and not its history.
"""


class Actor(TypedDict, total=False):
    """Whom a record attributes itself to, as every file spells it."""

    kind: str
    id: str
    round: int


class Wake(TypedDict, total=False):
    """What would make one member look, where anything can."""

    runtime: str
    handle: str


class Named(TypedDict, total=False):
    """One name a member answered to, and from when."""

    cli_name: str
    at: str


class Claiming(TypedDict):
    """One name, the member it reaches, and when that member claimed it."""

    cli_name: str
    id: str
    at: str


class Conversation(TypedDict, total=False):
    """Which conversation this member's row is describing.

    Carried on the member rather than stamped beside it, because what it
    qualifies — what this member says it is doing — is on the member too. A
    runtime that rewinds or clears keeps the process, the id and the pulse and
    signals none of it, so the prompt fold notices the transcript's roots move
    and clears its own description in the same write.
    """

    transcript: str
    roots: int


class Claim(TypedDict, total=False):
    """One path a member holds, and the state it left that path in.

    The modification time is what makes the claim answerable later. A record
    of *having written* a file says nothing about whether it still holds — the
    writer may be long gone, or somebody else may have written it since —
    while a recorded time can be compared against the path as it is now.
    """

    path: str
    prefix: bool
    mtime: float
    at: str


class Member(TypedDict, total=False):
    """One member as its own file holds it, plus what the read derives.

    Everything down to ``left_at`` is written; ``running`` and ``heard`` are
    not in the file at all — they are the file's modification time, read as
    presence. That is the whole of what replaces a departure record nobody
    wrote: a member is here while something is touching its file.
    """

    kind: str
    id: str
    round: int
    names: list[Named]
    task: str
    description: str
    summary: str
    error: str
    worktree: str
    liveness: str
    delivery: str
    wake: Wake
    conversation: Conversation
    claims: list[Claim]
    arrived: str
    left_at: str
    running: bool
    heard: str


class Held(TypedDict):
    """One claim as a reader about to write asks about it, with everyone on it.

    Derived across member files rather than recorded: more than one holder is
    two live members whose own files both claim the path, which is honest
    where a single record with a guessed author was not.
    """

    subject: str
    path: str
    prefix: bool
    holders: list[Actor]
    at: str


def text(value: str | None) -> str:
    """A field as a string, blank where the file carries something else.

    The declared type says string; the file another process wrote says
    whatever it says, so the value is checked rather than trusted.
    """
    return value if isinstance(value, str) else ""


def moment(value: float | None) -> float:
    """A field as a modification time, zero where it is not one."""
    return value if isinstance(value, float | int) else 0.0


def whole(value: int | None) -> int:
    """A field as a counting number, the first where it is not one."""
    return value if isinstance(value, int) and value >= 1 else 1


def actor_kind(actor: Actor | None) -> str:
    """What kind of member a record attributes itself to, blank where none."""
    return text(actor.get("kind")) if isinstance(actor, dict) else ""


def actor_id(actor: Actor | None, kind: str = "") -> str:
    """The id an actor object carries, blank where it is not one of *kind*."""
    if not isinstance(actor, dict) or (kind and actor_kind(actor) != kind):
        return ""
    return text(actor.get("id"))


def actor_round(actor: Actor | None) -> int:
    """Which attempt this record is about, the first where it does not say."""
    return whole(actor.get("round")) if isinstance(actor, dict) else 1


def conversation_of(actor: Actor | None) -> str:
    """Which conversation an actor speaks through, which outlives its round.

    Spelled as :meth:`~lup.coordination.refs.ActorRef.conversation` spells it:
    a member taken through a second round is that member further on and not a
    second one, and anything held per conversation is keyed by this.
    """
    kind, held = actor_kind(actor), actor_id(actor)
    return f"{kind}-{held}" if kind and held else ""


def member_actor(member: Member) -> Actor:
    """One member's address, as a claim or a message attributes itself to it."""
    return Actor(
        kind=text(member.get("kind")),
        id=text(member.get("id")),
        round=whole(member.get("round")),
    )


def stamped(value: datetime | None = None) -> str:
    """This moment as every file in the store spells one."""
    return (value or datetime.now(UTC)).isoformat()


def spoken_at(recorded: str) -> datetime | None:
    """A field's time as a moment, or nothing where it does not read as one."""
    try:
        parsed = datetime.fromisoformat(recorded)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def loaded[Record](path: Path, shape: type[Record]) -> Record | None:
    """One file read as *shape*, or nothing where it is not a JSON object.

    A file that will not parse reads as absent. Every write here lands by
    rename, so a half-written one is never seen under its own name — what this
    catches is a file some other tool wrote, and refusing to read the rest of
    the store over it would be the wrong trade on every path that reads.
    """
    try:
        record: Record = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def published[Record](path: Path, record: Record) -> Record | None:
    """Write one file so that no reader ever sees it half written.

    Into a neighbour and renamed, which is atomic within a directory on every
    filesystem this runs on: a reader either sees what was there before or
    sees the whole of what replaced it. That is what lets every read here go
    unlocked — only a writer that must first read takes the member's lock.

    Hands back what landed rather than whether it did, so a caller that wants
    the written shape has it and one that wants the verdict reads it as one.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        writing = path.with_name(f"{path.name}.{uuid4().hex[:8]}.writing")
        writing.write_text(json.dumps(record), encoding="utf-8")
        writing.replace(path)
    except OSError:
        return None
    return record


def listed(directory: Path, suffix: str = ".json") -> list[Path]:
    """Every file of this kind in one directory, in name order."""
    try:
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.name.endswith(suffix)
        )
    except OSError:
        return []


def discarded(path: Path) -> bool:
    """Remove one file, saying whether it was there to remove."""
    try:
        path.unlink()
    except OSError:
        return False
    return True


def member_path(root: Path, member_id: str) -> Path:
    """Where one member's own file sits while it is here."""
    return root / MEMBERS_DIR / f"{member_id}.json"


def departed_path(root: Path, member_id: str) -> Path:
    """Where one member's file sits once it has stopped."""
    return root / DEPARTED_DIR / f"{member_id}.json"


def member_lock(root: Path, member_id: str) -> Path:
    """The lock one member's own processes revise its file under."""
    return root / MEMBERS_DIR / f"{member_id}.lock"


def read_member(path: Path, running: bool) -> Member | None:
    """One member file, with the presence its modification time carries.

    The file says what the member is; the stat says when it last said so.
    Neither is written twice, which is what stops a row claiming to be present
    under a process that stopped.
    """
    found = loaded(path, Member)
    if found is None or not text(found.get("id")):
        return None
    try:
        heard = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None
    settled = found.copy()
    settled["running"] = running
    settled["heard"] = stamped(heard)
    return settled


def blank_member(kind: str, member_id: str) -> Member:
    """A member with nothing said about it yet, for a writer about to say it."""
    return Member(
        kind=kind,
        id=member_id,
        round=1,
        names=[],
        task="",
        description="",
        summary="",
        error="",
        worktree="",
        liveness="",
        delivery="",
        wake=Wake(),
        conversation=Conversation(transcript="", roots=0),
        claims=[],
        arrived=stamped(),
        left_at="",
        running=True,
        heard=stamped(),
    )


def stored(member: Member) -> Member:
    """This member as its file holds it, without what the read derives.

    ``running`` and ``heard`` are the file's modification time. Writing them
    into the file would give a reader two answers to one question, and the
    written one would be the stale one.
    """
    settled = member.copy()
    settled.pop("running", None)
    settled.pop("heard", None)
    return settled


def write_member(root: Path, member: Member) -> bool:
    """Put one member's file down whole, by rename."""
    landed = published(member_path(root, text(member.get("id"))), stored(member))
    return landed is not None


def revised(
    root: Path, member_id: str, revise: Callable[[Member], Member]
) -> Member | None:
    """Read this member's file, apply *revise*, and put it back, under its lock.

    The one read-modify-write in the store, and the reason each member has a
    lock of its own: a session's tool server, its prompt hook and the
    permission dispatcher recording what a command just changed are three
    processes revising one file, and two of them reading before either writes
    would lose whichever wrote first.

    Per member rather than per store, so one session's writes never wait on
    another's, and the region is one read and one rename wide.

    Nothing is created for a member that has no file: a revision of nobody
    would put a row on the roster that never joined.
    """
    lock = member_lock(root, member_id)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                found = read_member(member_path(root, member_id), running=True)
                if found is None:
                    return None
                settled = revise(found)
                return settled if write_member(root, settled) else None
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return None


def beat(root: Path, member_id: str) -> None:
    """Record that this member is here now, without rewriting what it says.

    The modification time is the whole of the pulse, so a beat touches the
    file rather than revising it: nothing is read, nothing is locked, and a
    beat cannot race a description being written in another process.
    """
    try:
        member_path(root, member_id).touch()
    except OSError:
        return


def members(root: Path) -> list[Member]:
    """Every member whose file is still under ``members/``, oldest arrival first.

    Present on the record, which the pulse may still contradict: a session
    killed a minute ago has a file here and a modification time that says so.
    :func:`present` is what applies that.
    """
    found = [
        member
        for path in listed(root / MEMBERS_DIR)
        for member in [read_member(path, running=True)]
        if member is not None
    ]
    return sorted(found, key=lambda member: text(member.get("arrived")))


def departed(root: Path, now: datetime | None = None) -> list[Member]:
    """Every member that stopped recently enough to still be worth reporting.

    Bounded by the retention window here rather than by the sweep alone, so a
    reader gets the same answer whether or not a sweep has run since.
    """
    since = (now or datetime.now(UTC)) - timedelta(seconds=DEPARTED_SECONDS)

    def recent(member: Member) -> bool:
        """Whether this departure is still news rather than history."""
        left = spoken_at(text(member.get("left_at")))
        return left is None or left >= since

    return [
        member
        for path in listed(root / DEPARTED_DIR)
        for member in [read_member(path, running=False)]
        if member is not None and recent(member)
    ]


def stale(heard: datetime | None, now: datetime, window: float) -> bool:
    """Whether a silence since *heard* has outlasted the window at *now*.

    A member nothing can be read for is one no reader can vouch for, which
    reads as absent rather than as present by default.
    """
    if heard is None:
        return True
    return now - heard > timedelta(seconds=window)


def pulsed(member: Member, now: datetime, window: float) -> Member:
    """This member as its own file's modification time leaves it.

    Only a session answers for itself this way. A spawned agent's presence is
    the word of the process that spawned it, and the person is never finished
    at all, so both pass through as their files say.
    """
    if text(member.get("kind")) != MEMBER_KIND or not member.get("running"):
        return member
    heard = spoken_at(text(member.get("heard")))
    if not stale(heard, now, window):
        return member
    gone = member.copy()
    gone["running"] = False
    gone["error"] = f"unheard since {heard.isoformat() if heard else 'it joined'}"
    return gone


def present(
    root: Path,
    now: datetime | None = None,
    mine: str = "",
    window: float = STALE_AFTER_SECONDS,
) -> list[Member]:
    """Every member this store holds, live ones first, as the read leaves them.

    The departed are here too, back to the retention window, because a reader
    that arrived after somebody left still wants to know what they concluded —
    and a sender addressing them has to be told they are gone rather than have
    the message wait for nobody.

    *mine* is the reading member's own id, which is never read as absent: the
    reader is manifestly here, and its own beat may land after this read.
    """
    moment_now = now or datetime.now(UTC)
    here = [
        member if text(member.get("id")) == mine else pulsed(member, moment_now, window)
        for member in members(root)
    ]
    return sorted(
        [*here, *departed(root, moment_now)],
        key=lambda member: not member.get("running"),
    )


def member_of(root: Path, member_id: str) -> Member | None:
    """One member by id, wherever its file sits, or nothing where none does."""
    here = read_member(member_path(root, member_id), running=True)
    if here is not None:
        return here
    return read_member(departed_path(root, member_id), running=False)


def live_ids(
    root: Path,
    now: datetime | None = None,
    mine: str = "",
    window: float = STALE_AFTER_SECONDS,
) -> list[str]:
    """Every member still working here, by id, which is what expires a claim.

    A claim is alive while its holder is, so this is the whole of the expiry
    rule: no timeout to tune, no release to forget, and the failure mode is a
    member that stopped taking its own claims with it.
    """
    return [
        text(member.get("id"))
        for member in present(root, now, mine, window)
        if member.get("running")
    ]


def names_of(member: Member) -> list[Named]:
    """Every name one member has answered to, oldest first."""
    found = member.get("names")
    return [
        named
        for named in (found if isinstance(found, list) else [])
        if isinstance(named, dict) and text(named.get("cli_name"))
    ]


def current_name(member: Member) -> str:
    """What this member is called now, or nothing where nothing named it."""
    found = names_of(member)
    return text(found[-1].get("cli_name")) if found else ""


def renamed(member: Member, cli_name: str) -> Member:
    """This member answering to one more name, keeping the ones before it.

    Kept rather than replaced, so a reference somebody wrote down an hour ago
    still reaches the member it named. There is no error a sender could be
    shown for using it: the name was correct when they read it.
    """
    settled = member.copy()
    settled["names"] = [*names_of(member), Named(cli_name=cli_name, at=stamped())]
    return settled


# lup: ignore[dict-str-payload] — keyed by member id, an identity the roster's
# own module mints and that a half with no type of lup's cannot name
def called(root: Path, now: datetime | None = None) -> dict[str, str]:
    """What each member is called now, by id."""
    return {
        text(member.get("id")): current_name(member)
        for member in present(root, now)
        if current_name(member)
    }


def naming(root: Path, now: datetime | None = None) -> list[Claiming]:
    """Every name any member has answered to, oldest claim first.

    The whole history rather than the current names: a name somebody wrote
    down before a rename goes on reaching the member it named until something
    else claims it. Ordered by when each was claimed, so a reader taking the
    last match takes the newest claim on that name.
    """
    return sorted(
        (
            Claiming(
                cli_name=text(named.get("cli_name")),
                id=text(member.get("id")),
                at=text(named.get("at")),
            )
            for member in present(root, now)
            for named in names_of(member)
        ),
        key=lambda claiming: claiming["at"],
    )


def subject_of(path: str, prefix: bool) -> str:
    """What a reader keys a claim by, which a lock and a touch differ in.

    A prefix and an exact path can be spelled identically and mean different
    things — locking ``src/lup`` is not touching a file of that name — so the
    kind is part of the key.
    """
    return f"{'under' if prefix else 'at'} {path}"


def path_mtime(path: str) -> float:
    """When the filesystem says this path was last written, zero where it is gone."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def standing(claim: Claim) -> bool:
    """Whether this claim still says something about the path it names.

    Three ways it stops. The path is **gone**, and a claim over nothing names
    nothing anybody could write. Somebody has **written it since**, which the
    recorded time is there to notice — the claim was evidence of what this
    member left, and what stands there now is not it. Otherwise it **holds**.

    A prefix lock is exempt from the second: a directory's modification time
    moves whenever anything inside it is created or removed, including by the
    holder, so comparing it would retire a lock the moment it was used. A lock
    ends when its holder leaves, when it is released, or when the prefix goes.
    """
    path = text(claim.get("path"))
    if not path:
        return False
    current = path_mtime(path)
    if not current:
        return False
    return bool(claim.get("prefix")) or current <= moment(claim.get("mtime"))


def claims_of(member: Member) -> list[Claim]:
    """Every claim one member's file holds that still stands."""
    found = member.get("claims")
    return [
        claim
        for claim in (found if isinstance(found, list) else [])
        if isinstance(claim, dict) and standing(claim)
    ]


def held(root: Path, live: list[str], now: datetime | None = None) -> list[Held]:
    """Every claim a live member holds, one row per path, newest first.

    Two members holding one path meet here, which is the whole of how a
    contest is found: no record says they contest, their two files do.
    """
    # lup: ignore[empty-collection] — a fold gathering holders across files
    # into one row per subject, which no comprehension expresses: each member
    # contributes to a row an earlier member may already have created
    rows: dict[str, Held] = {}
    for member in present(root, now):
        if text(member.get("id")) not in live:
            continue
        for claim in claims_of(member):
            path = text(claim.get("path"))
            prefix = bool(claim.get("prefix"))
            subject = subject_of(path, prefix)
            at = text(claim.get("at"))
            found = rows.get(subject)
            rows[subject] = Held(
                subject=subject,
                path=path,
                prefix=prefix,
                holders=[*(found["holders"] if found else []), member_actor(member)],
                at=max(at, found["at"]) if found else at,
            )
    return sorted(rows.values(), key=lambda row: row["at"], reverse=True)


def covers(row: Held, candidate: str) -> bool:
    """Whether a path about to be written falls under this claim."""
    if not row["prefix"]:
        return candidate == row["path"]
    return candidate == row["path"] or candidate.startswith(row["path"] + "/")


def covering(
    root: Path, target: Path, live: list[str], now: datetime | None = None
) -> list[Held]:
    """Every live claim a write to this path would land under."""
    return [row for row in held(root, live, now) if covers(row, str(target))]


def claim_holders(
    root: Path, target: str, mine: str, now: datetime | None = None
) -> list[str]:
    """Who else, still working here, is holding the path a write would land on.

    Live holders other than the asker. A claim expires with the member that
    made it, so a departed holder is nobody to ask; and a member meeting its
    own claim on every edit would be asked about its own work.
    """
    live = live_ids(root, now)
    names = called(root, now)
    return sorted(
        {
            names.get(holder) or holder
            for row in covering(root, Path(target).resolve(), live, now)
            for holder in [actor_id(found) for found in row["holders"]]
            if holder and holder != mine
        }
    )


def claimed(member: Member, paths: list[str], prefix: bool) -> Member:
    """This member holding these paths as well as whatever it held already.

    A path claimed again replaces its earlier claim rather than joining it:
    what a claim carries is the state this member left the path in, and the
    older reading is what the newer write has just made wrong.
    """
    at = stamped()
    taken = [
        Claim(path=path, prefix=prefix, mtime=path_mtime(path), at=at) for path in paths
    ]
    subjects = [subject_of(text(claim.get("path")), prefix) for claim in taken]
    settled = member.copy()
    settled["claims"] = [
        *[
            claim
            for claim in claims_of(member)
            if subject_of(text(claim.get("path")), bool(claim.get("prefix")))
            not in subjects
        ],
        *taken,
    ]
    return settled


def unclaimed(member: Member, prefix: Path) -> Member:
    """This member without the lock it took over *prefix*."""
    settled = member.copy()
    settled["claims"] = [
        claim
        for claim in claims_of(member)
        if not (bool(claim.get("prefix")) and text(claim.get("path")) == str(prefix))
    ]
    return settled


def record_claims(root: Path, mine: str, paths: list[str]) -> bool:
    """Write down what one member's call just changed, under that member's lock.

    The dispatcher's write. It runs after the work has already happened, so
    the call it belongs to cannot be undone by refusing, and a claim nobody
    could record costs a later reader an attribution while a raised exception
    would cost the session its ability to work.

    No rival is recorded and none is guessed at. Where two sessions had
    windows open over one path, both record a claim of their own and the
    contest is what a reader derives from meeting them — the same answer,
    arrived at from evidence rather than from a list of suspects.
    """
    if not mine or not paths:
        return False
    return revised(root, mine, lambda member: claimed(member, paths, False)) is not None


def addresses(root: Path, now: datetime | None = None) -> list[str]:
    """Every spelling that currently reaches a live member of this roster.

    Ids, the kind-qualified label a door prints, and whatever each member is
    called now, because a sender types whichever of those it last read — a
    check knowing only one of them would let the others through, which is the
    failure that made a redirect reach nobody.
    """
    live = live_ids(root, now)
    return sorted(
        {
            *live,
            *[f"{MEMBER_KIND}:{member}" for member in live],
            *[
                claiming["cli_name"]
                for claiming in naming(root, now)
                if claiming["id"] in live
            ],
        }
    )


def listing(root: Path, now: datetime | None = None) -> list[str]:
    """One line per live member, as somebody choosing who to reach reads it."""

    def described(member: Member) -> list[str]:
        """The parts one member's line is joined from, blanks included."""
        worktree = text(member.get("worktree"))
        return [
            current_name(member) or text(member.get("id")),
            Path(worktree).name if worktree else "",
            text(member.get("description")) or text(member.get("task")),
            text(member.get("delivery")),
        ]

    return [
        " — ".join(part for part in described(member) if part)
        for member in present(root, now)
        if member.get("running")
    ]


def depart(root: Path, member_id: str, summary: str = "", error: str = "") -> bool:
    """Move this member's file to the departed, saying whether one was moved.

    A session's ending hook runs in a process with no typed writer to reach,
    and a file nobody moved reads as present until the pulse retires it —
    which is right for a session that was killed and needlessly vague for one
    that exited.

    A member that never joined leaves nothing: there is no file to move, and a
    departed stub for a member that never arrived is a row no listing should
    carry.
    """
    if not member_id:
        return False
    found = read_member(member_path(root, member_id), running=False)
    if found is None:
        return False
    settled = found.copy()
    settled["summary"] = summary or text(found.get("summary"))
    settled["error"] = error or text(found.get("error"))
    settled["left_at"] = stamped()
    if published(departed_path(root, member_id), stored(settled)) is None:
        return False
    discarded(member_path(root, member_id))
    discarded(member_lock(root, member_id))
    return True


def swept(root: Path, now: datetime | None = None) -> list[Member]:
    """Retire what the read already derives, and delete what nobody reads.

    A member whose pulse stopped is moved to the departed, so a reader that
    lists the directory agrees with one that stats the file; and a departed
    stub older than the retention window is deleted, which is what keeps the
    store the size of the population rather than of its history.

    A claim needs no sweeping: it stands or it does not, and the filesystem is
    what says which.
    """
    moment_now = now or datetime.now(UTC)
    retired = [
        gone
        for member in members(root)
        if not (gone := pulsed(member, moment_now, STALE_AFTER_SECONDS)).get("running")
    ]
    for member in retired:
        depart(root, text(member.get("id")), error=text(member.get("error")))
    since = moment_now - timedelta(seconds=DEPARTED_SECONDS)
    for path in listed(root / DEPARTED_DIR):
        found = read_member(path, running=False)
        left = spoken_at(text(found.get("left_at"))) if found is not None else None
        if found is None or (left is not None and left < since):
            discarded(path)
    return retired
