# lup: ignore[constant-declaration]
# Every name below is the store's own on-disk layout, which processes sharing
# no import must spell alike to meet at all — an identity of this store rather
# than a choice a caller can make. The typed writers import them from here
# instead of restating them, which is what a pin over two copies could only
# report after the fact.
"""One fold of the coordination store, for every process that reads it.

The store is three append-only records and a pair of stamp directories under
one repository's shared git directory, and what anyone asks of it is a fold:
who is here, what each is holding, what a name reaches. Three processes ask,
and no two of them share an import — the typed library inside a session's tool
server, the hooks a runtime spawns as bare scripts, and the compiled
permission dispatcher. Each folded the same files for itself, so every record
the store gained had to be taught to three readers separately, and a reader
that missed one went on answering confidently about a store it no longer
understood.

So the fold is written once, here, under the strictest of the three
constraints: the standard library alone, no pydantic, no ``lup``. The library
imports it as an ordinary module; each plugin ships this package into
``hooks/runtime/``, where a hook imports it as a sibling and the dispatcher
reaches it through the search path it already inserts for the kernel.

**It owns the layout.** Every file and directory name the store is made of is
declared here and imported by the typed writers beside it. A rename moves
every reader with it.

**Two writes ride along.** A session's ending hook appends its own departure,
and the dispatcher appends the claim for a change it has just seen. Both run
in a process with no typed writer to reach, and both are one record whose
shape this module already owns — so they live beside the fold rather than
being restated wherever a bare process happens to need one.

**Nothing here raises.** Every reader is on a path where failing would cost
more than not answering: a prompt, a tool call, a permission decision. An
unreadable file reads as empty, a torn last line is skipped, and a record that
is not an object is passed over — which is the ordinary state of a store
another session is appending to.

``TypedDict`` throughout, and partial for every shape another process writes:
a field the typed writer adds must not make its record unreadable here.
"""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

STORE_DIR = "lup"
COORDINATION_DIR = "coordination"
"""Where one repository's peers meet, beneath its shared git directory.

Two worktrees that spelled this differently would coordinate with nobody, and
nothing anywhere would report the mismatch: both sessions work, and neither is
on the other's roster.
"""

ROSTER_FILE = "roster.jsonl"
NAMES_FILE = "names.jsonl"
TOUCHES_FILE = "touches.jsonl"
"""The three records every reader folds: who is here, what they are called, and
what they hold."""

HEARTBEATS_DIR = "heartbeats"
RESETS_DIR = "resets"
"""The two stamps a session leaves about itself, whose modification time is the
whole of what they carry: it is still here, and the conversation its row
described is gone."""

WINDOWS_DIR = "windows"
LOOKS_DIR = "looks"
"""The two places one process keeps its own working state under the store.

Declared beside the rest of the layout although nothing here reads either:
the dispatcher is the windows' only writer and reader, and the prompt fold is
the looks'. A name the store's layout carries in one place is a name a rename
cannot leave behind.
"""

MEMBER_KIND = "session"
"""What a repository peer is on the roster, beside spawned workers and the person.

The one kind that answers for its own presence, which is why the pulse applies
to it and to nothing else: a spawned agent is live because the process that
spawned it says so, and the person is never finished at all.
"""

STALE_AFTER_SECONDS = 120.0
"""How long a session's silence reads as absence.

A few beats wide rather than one, so a stalled scheduler or a slow disk is not
read as a departure; short because the roster is read to decide whether a path
is safe to write, and a dead session holding that decision open for an hour is
the failure this closes.
"""


class Actor(TypedDict, total=False):
    """Whom a record attributes itself to, as every record spells it."""

    kind: str
    id: str
    round: int


class Wake(TypedDict, total=False):
    """What would make one member look, where anything can."""

    runtime: str
    handle: str


class RosterRecord(TypedDict, total=False):
    """One record on the roster, as far as folding it needs to know."""

    type: str
    actor: Actor
    task: str
    description: str
    summary: str
    error: str
    worktree: str
    liveness: str
    delivery: str
    wake: Wake
    at: str


class NameRecord(TypedDict, total=False):
    """One member answering to one name, from that moment until it renames."""

    id: str
    cli_name: str
    at: str


class TouchRecord(TypedDict, total=False):
    """One thing that happened to a claim, as far as folding it needs to know."""

    type: str
    actor: Actor
    path: str
    prefix: bool
    digest: str
    rivals: list[Actor]
    at: str


class Finished(TypedDict):
    """The record that ends a row, as the typed roster serializes its own."""

    type: str
    actor: Actor
    at: str
    summary: str
    error: str


class Touched(TypedDict):
    """The record that claims a path, as the typed touches serialize their own."""

    type: str
    actor: Actor
    at: str
    path: str
    digest: str
    rivals: list[Actor]


class Member(TypedDict):
    """One member as the roster's fold leaves it, alive or finished.

    Every field the three readers between them ask for, because a fold that
    answered one of them would leave the others folding again. What each reader
    then renders is its own business: a console prints four of these, the
    prompt hook diffs three, and the typed library validates the lot into its
    own model.
    """

    kind: str
    id: str
    round: int
    task: str
    description: str
    summary: str
    error: str
    worktree: str
    liveness: str
    delivery: str
    wake: Wake
    running: bool
    heard: str
    """When the record last spoke of this member, as its newest record spells it.

    The record's own time, whichever kind of record it was. A reader deciding
    whether a silent member is still there starts here and takes a later pulse
    where one was written — the record alone says when a member last *said*
    something, which is not the same question.
    """

    arrived: str
    """When this member's present standing began: its newest arrival's own time.

    Apart from ``heard`` because the two move differently, and because one
    question needs only this: which departures happened while this member was
    here to have written to the departed.
    """


class Held(TypedDict):
    """One claim as the touch record's fold leaves it, with everyone holding it.

    More than one holder is honest rather than broken: a change made by a shell
    command is attributed by comparing the tree before and after, which sees
    every change in its window regardless of who made it, so where two sessions
    had windows open over one path both names are recorded and neither is
    guessed at.
    """

    subject: str
    path: str
    prefix: bool
    holders: list[Actor]
    digest: str
    at: str


class Named(TypedDict):
    """One naming, as the record keeps it: who, what, and from when."""

    id: str
    cli_name: str
    at: str


def text(value: str | None) -> str:
    """A field as a string, blank where the record carries something else.

    The record's declared type says string; the file another process wrote says
    whatever it says, so the value is checked rather than trusted.
    """
    return value if isinstance(value, str) else ""


def actor_kind(actor: Actor | None) -> str:
    """What kind of member a record attributes itself to, blank where none."""
    return text(actor.get("kind")) if isinstance(actor, dict) else ""


def actor_id(actor: Actor | None, kind: str = "") -> str:
    """The id an actor object carries, blank where it is not one of *kind*.

    An empty *kind* accepts any: a claim's holder is an id whatever it is,
    while a roster fold read for sessions wants sessions and not the person.
    """
    if not isinstance(actor, dict) or (kind and actor_kind(actor) != kind):
        return ""
    return text(actor.get("id"))


def actor_round(actor: Actor | None) -> int:
    """Which attempt this record is about, the first where it does not say."""
    if not isinstance(actor, dict):
        return 1
    held = actor.get("round")
    return held if isinstance(held, int) and held >= 1 else 1


def conversation_of(actor: Actor | None) -> str:
    """Which conversation an actor speaks through, which outlives its round.

    The key the fold holds a member under, spelled as
    :meth:`~lup.coordination.refs.ActorRef.conversation` spells it: a member
    taken through a second round is that member further on and not a second
    one, and a fold keyed by the printed address held two of it.
    """
    kind, held = actor_kind(actor), actor_id(actor)
    return f"{kind}-{held}" if kind and held else ""


def loaded[Record](path: Path, shape: type[Record]) -> list[Record]:
    """Every line that is a JSON object, read as *shape*, skipping the rest.

    A torn final line is the ordinary state of a store another session is
    appending to, and a malformed one must not stop the reader seeing the
    records around it. The shape is the caller's declaration of what the file
    holds; nothing here checks a record against it beyond being an object.
    """
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        return []

    def parsed(line: str) -> Record | None:
        try:
            record: Record = json.loads(line)
        except ValueError:
            return None
        return record if isinstance(record, dict) else None

    return [record for record in map(parsed, lines) if record is not None]


def appended[Record](path: Path, records: list[Record]) -> bool:
    """Put these records on the end of one file, saying whether they landed.

    One write with the append flag, which is what makes a concurrent writer
    safe: the kernel places the whole buffer at the end of the file as it
    stands, so two processes appending at once interleave records and never
    halves of one.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(f"{json.dumps(record)}\n" for record in records))
    except OSError:
        return False
    return True


def spoken_at(recorded: str) -> datetime | None:
    """A record's own time as a moment, or nothing where it does not read as one."""
    try:
        moment = datetime.fromisoformat(recorded)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def stamp(path: Path) -> None:
    """Mark this moment on one file, creating what is missing on the way."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except OSError:
        return


def stamped_at(path: Path) -> datetime | None:
    """The moment one stamp file was last marked, or nothing where there is none."""
    try:
        marked = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(marked, UTC)


def beat_path(root: Path, member_id: str) -> Path:
    """Where one member's pulse is kept, under the coordination store."""
    return root / HEARTBEATS_DIR / member_id


def beat(root: Path, member_id: str) -> None:
    """Record that this member is here now."""
    stamp(beat_path(root, member_id))


def heard_at(root: Path, member_id: str) -> datetime | None:
    """When this member last beat, or nothing where it never has."""
    return stamped_at(beat_path(root, member_id))


def reset_path(root: Path, member_id: str) -> Path:
    """Where one member's conversation reset is kept, beside its pulse."""
    return root / RESETS_DIR / member_id


def reset(root: Path, member_id: str) -> None:
    """Record that the conversation this member's row described is gone."""
    stamp(reset_path(root, member_id))


def reset_at(root: Path, member_id: str) -> datetime | None:
    """When this member's conversation last moved, or nothing where it never has."""
    return stamped_at(reset_path(root, member_id))


def stale(
    heard_moment: datetime | None,
    now: datetime,
    window: float = STALE_AFTER_SECONDS,
) -> bool:
    """Whether a silence since *heard_moment* has outlasted the window at *now*.

    A member heard neither on the record nor by a beat is one no reader can
    vouch for, which reads as absent rather than as present by default.

    The window is a parameter with the store's own default, because a typed
    caller may turn it — a test wants one it can cross — and the arithmetic
    must still be this one, so a turned window changes how long a silence is
    tolerated and never what tolerating it means.
    """
    if heard_moment is None:
        return True
    return now - heard_moment > timedelta(seconds=window)


def arrival(record: RosterRecord) -> Member:
    """The member one arrival starts, carrying everything that arrival declared."""
    actor = record.get("actor")
    at = text(record.get("at"))
    wake = record.get("wake")
    return Member(
        kind=actor_kind(actor),
        id=actor_id(actor),
        round=actor_round(actor),
        task=text(record.get("task")),
        description=text(record.get("description")),
        summary="",
        error="",
        worktree=text(record.get("worktree")),
        liveness=text(record.get("liveness")),
        delivery=text(record.get("delivery")),
        wake=wake if isinstance(wake, dict) else Wake(),
        running=True,
        heard=at,
        arrived=at,
    )


def applied(record: RosterRecord, standing: Member | None) -> Member | None:
    """The member as one record leaves it, or nothing where it says nothing.

    A replayed arrival for a round the member has already moved past says
    nothing about where it is now, so the standing entry survives it. A
    description or a finish for nobody invents no member: a record arriving
    before the join it belongs to is one every reader passes over, and so is a
    record of a kind this fold has never heard of.
    """
    at = text(record.get("at"))
    match text(record.get("type")):
        case "spawned" | "joined":
            if (
                standing is not None
                and actor_round(record.get("actor")) < standing["round"]
            ):
                return standing
            return arrival(record)
        case "described" if standing is not None:
            described = standing.copy()
            described["description"] = text(record.get("description"))
            described["heard"] = at
            return described
        case "finished" if standing is not None:
            finished = standing.copy()
            finished["running"] = False
            finished["summary"] = text(record.get("summary"))
            finished["error"] = text(record.get("error"))
            finished["heard"] = at
            return finished
        case _:
            return standing


def members(roster: Path) -> dict[str, Member]:
    """Every member one roster has held, by conversation, in first-seen order.

    A round advance updates the member in place rather than adding one, because
    a worker on its second round is the agent that took its first. Finished
    members are kept with ``running`` false rather than dropped: a departure is
    read off the finished record, and what a session concluded is there and
    nowhere else.
    """
    # lup: ignore[empty-collection] — a fold whose every step reads what the
    # steps before it left, which is the one shape a comprehension cannot
    # spell: a description revises the member an earlier record created
    held: dict[str, Member] = {}
    for record in loaded(roster, RosterRecord):
        speaking = conversation_of(record.get("actor"))
        if not speaking:
            continue
        settled = applied(record, held.get(speaking))
        if settled is not None:
            held[speaking] = settled
    return held


def heard(root: Path, member: Member) -> datetime | None:
    """When this member was last heard from: its newest record, or a later beat."""
    return max(
        (
            moment
            for moment in (spoken_at(member["heard"]), heard_at(root, member["id"]))
            if moment is not None
        ),
        default=None,
    )


def pulsed(
    root: Path, member: Member, now: datetime, window: float = STALE_AFTER_SECONDS
) -> Member:
    """This member as its pulse leaves it: gone where the pulse has stopped.

    Only a session answers for itself this way. A spawned agent's presence is
    the word of the process that spawned it, which writes the finish, and the
    person is never finished at all. A session whose record says running and
    whose pulse says nothing within the window reads as gone, with the silence
    named where the finish would have been — derived at the read, so beating
    again is enough to read as back.
    """
    if member["kind"] != MEMBER_KIND or not member["running"]:
        return member
    last = heard(root, member)
    if not stale(last, now, window):
        return member
    gone = member.copy()
    gone["running"] = False
    gone["error"] = f"unheard since {last.isoformat() if last else 'it joined'}"
    return gone


def rewound(root: Path, member: Member) -> Member:
    """This member as its conversation leaves it: unsaid where that moved.

    A rewind or a clear keeps the process, the id and the pulse, and discards
    what the session was saying, so a description older than the reset stamp
    is the discarded conversation's and reads as empty — derived at the read,
    so describing again is enough to read as current. What the session holds
    is left alone: a touch is what happened to the tree, and the tree is
    whatever the rewind left it.
    """
    if member["kind"] != MEMBER_KIND or not member["description"]:
        return member
    moved = reset_at(root, member["id"])
    spoken = spoken_at(member["heard"])
    if moved is None or (spoken is not None and spoken >= moved):
        return member
    unsaid = member.copy()
    unsaid["description"] = ""
    return unsaid


def present(
    root: Path,
    now: datetime | None = None,
    mine: str = "",
    window: float = STALE_AFTER_SECONDS,
) -> list[Member]:
    """Every member as the record, the pulses and the resets say, live ones first.

    The whole of what is derived at the read: a row whose pulse stopped is
    gone however the record reads, and a description from a conversation that
    was rewound is unsaid. Both are derived here rather than recorded, so a
    session that beats again reads as back and one that describes itself again
    reads as current, without anybody writing a correction.

    *mine* is the reading session's own id, which is never read as absent: the
    reader is manifestly here, and its own beat lands after this fold rather
    than before it — so a session folding the store at its first prompt would
    otherwise find itself gone and drop its own claims from the live set.
    """
    moment = now or datetime.now(UTC)
    return sorted(
        (
            rewound(
                root,
                member
                if member["id"] == mine
                else pulsed(root, member, moment, window),
            )
            for member in members(root / ROSTER_FILE).values()
        ),
        key=lambda member: not member["running"],
    )


def live_ids(
    root: Path,
    now: datetime | None = None,
    mine: str = "",
    window: float = STALE_AFTER_SECONDS,
) -> list[str]:
    """Every member still working here, by id, which is what expires a claim.

    A claim is alive while its holder is, so this is the whole of the expiry
    rule: no timeout to tune, no release to forget, and the failure mode is a
    session that stopped taking its own claims with it.
    """
    return [
        member["id"] for member in present(root, now, mine, window) if member["running"]
    ]


def member_actor(root: Path, member_id: str) -> Actor | None:
    """One session's own address as the roster holds it, or nothing.

    Read rather than composed. A session that never joined has no address to
    write claims under, and inventing one here would put a holder on the record
    that no listing shows and nothing can ask.
    """
    return next(
        (
            Actor(kind=member["kind"], id=member["id"], round=member["round"])
            for member in members(root / ROSTER_FILE).values()
            if member["id"] == member_id
        ),
        None,
    )


def named(root: Path) -> list[Named]:
    """Every naming ever recorded, oldest first.

    The whole history rather than the current names: a name somebody wrote down
    before a rename goes on reaching the session it named until something else
    claims it, and there is no error the sender could have been shown, because
    the name they used was correct when they read it.
    """
    return [
        Named(id=held, cli_name=calling, at=text(record.get("at")))
        for record in loaded(root / NAMES_FILE, NameRecord)
        for held in [text(record.get("id"))]
        for calling in [text(record.get("cli_name"))]
        if held and calling
    ]


# lup: ignore[dict-str-payload] — keyed by member id, an identity the roster's
# own module mints and that a half with no type of lup's cannot name
def called(root: Path) -> dict[str, str]:
    """What each member is called now, the latest record for an id winning."""
    return {record["id"]: record["cli_name"] for record in named(root)}


# lup: ignore[dict-str-payload] — keyed by the name somebody types, whose value
# is the member id it reaches; neither side is a type this half can name
def name_holders(root: Path) -> dict[str, str]:
    """Which member each name reaches now, the newest claim on a name winning.

    Newest wins by construction, the comprehension walking the record in order.
    """
    return {record["cli_name"]: record["id"] for record in named(root)}


def subject_of(path: str, prefix: bool) -> str:
    """What the fold keys a claim by, which a lock and a touch differ in.

    A prefix and an exact path can be spelled identically and mean different
    things — locking ``src/lup`` is not touching a file of that name — so the
    kind is part of the key rather than something a later record could silently
    convert.
    """
    return f"{'under' if prefix else 'at'} {path}"


def covers(claim: Held, candidate: str) -> bool:
    """Whether a path about to be written falls under this claim."""
    if not claim["prefix"]:
        return candidate == claim["path"]
    return candidate == claim["path"] or candidate.startswith(claim["path"] + "/")


def vacant(claim: Held) -> bool:
    """Whether the path this claim is over has gone from the filesystem.

    A worktree removed from under a session takes every path in it, and a claim
    over one names nothing anybody could write. Asked of the filesystem rather
    than of git, because a claim is keyed by the path and the path is what has
    to be there.
    """
    return not Path(claim["path"]).exists()


def touch_prefix(record: TouchRecord, kind: str) -> bool:
    """Whether one record is about a prefix lock or about an exact path.

    A vacating says which it ends, because the path it names could be either;
    every other record is told by its own kind.
    """
    if kind != "vacated":
        return kind in ("locked", "released")
    return record.get("prefix") is True


def touched_claim(record: TouchRecord, actor: Actor, path: str) -> Held:
    """The claim one change leaves, with every session it could have been.

    Recorded with every name rather than with a guess: a before-and-after
    comparison sees the change and cannot see who made it, and inventing an
    author there would put a confident wrong answer where a reader is deciding
    whether it is safe to write.
    """
    rivals = record.get("rivals")
    return Held(
        subject=subject_of(path, False),
        path=path,
        prefix=False,
        holders=[
            actor,
            *[
                rival
                for rival in (rivals if isinstance(rivals, list) else [])
                if actor_id(rival)
            ],
        ],
        digest=text(record.get("digest")),
        at=text(record.get("at")),
    )


def claims(root: Path) -> list[Held]:
    """Every claim standing on the record, whoever holds it and whether they live.

    Keyed by kind as well as path, so a later record cannot silently convert a
    lock into a touch. A release by somebody who never held the prefix says
    nothing, which is what stops one session unlocking another's work by
    asking; a vacating ends the claim whoever wrote it, because a path that is
    not there is held by nobody and that is a fact of the filesystem any
    session can check.
    """
    # lup: ignore[empty-collection] — a fold whose every step reads what the
    # steps before it left: a release answers against the claim an earlier
    # record created, which is the one shape a comprehension cannot spell
    standing: dict[str, Held] = {}
    for record in loaded(root / TOUCHES_FILE, TouchRecord):
        actor = record.get("actor") or Actor()
        path = text(record.get("path"))
        if not actor_id(actor) or not path:
            continue
        kind = text(record.get("type"))
        subject = subject_of(path, touch_prefix(record, kind))
        match kind:
            case "vacated":
                standing.pop(subject, None)
            case "touched" | "contested":
                standing[subject] = touched_claim(record, actor, path)
            case "locked":
                standing[subject] = Held(
                    subject=subject,
                    path=path,
                    prefix=True,
                    holders=[actor],
                    digest="",
                    at=text(record.get("at")),
                )
            case "released" if subject in standing and actor_id(actor) in [
                actor_id(holder) for holder in standing[subject]["holders"]
            ]:
                del standing[subject]
            case _:
                continue
    return list(standing.values())


def narrowed(claim: Held, live: list[str]) -> Held:
    """This claim with only the holders still working here."""
    remaining = claim.copy()
    remaining["holders"] = [
        holder for holder in claim["holders"] if actor_id(holder) in live
    ]
    return remaining


def held(root: Path, live: list[str]) -> list[Held]:
    """Every claim a live session holds, holders narrowed to them, newest first.

    Expiry is the roster's rather than a timeout's. A claim outliving its
    session would have to be released by somebody, and the somebody who would
    have to remember is exactly the session that has stopped.
    """
    return sorted(
        (
            narrowed(claim, live)
            for claim in claims(root)
            if any(actor_id(holder) in live for holder in claim["holders"])
        ),
        key=lambda claim: claim["at"],
        reverse=True,
    )


def covering(root: Path, target: Path, live: list[str]) -> list[Held]:
    """Every live claim a write to this path would land under."""
    return [claim for claim in held(root, live) if covers(claim, str(target))]


def addresses(root: Path, now: datetime | None = None) -> list[str]:
    """Every spelling that currently reaches a live member of this roster.

    Ids, the kind-qualified label a door prints, and whatever each member is
    called now, because a sender types whichever of those it last read — a
    check knowing only one of them would let the others through, which is the
    failure that made a redirect reach nobody.

    Names are read both ways round, which is one line and the whole of a hole.
    `name_holders` answers which member a name reaches now, so a name somebody
    wrote down before a rename still refuses; `called` answers what a member is
    called now, so a member that went quiet long enough to read as gone, lost
    its name to a newcomer, and came back once the newcomer had left is still
    refused under the name every listing prints for it. Either reading alone
    leaves a live member a sender can type their way to unrecorded.

    Live members only. A session that has left is not somewhere a durable
    message would arrive either, so redirecting a send to it would trade one
    call reaching nobody for another.
    """
    live = live_ids(root, now)
    calling = called(root)
    return sorted(
        {
            *live,
            *[f"{MEMBER_KIND}:{member}" for member in live],
            *[name for name, member in name_holders(root).items() if member in live],
            *[calling[member] for member in live if calling.get(member)],
        }
    )


def listing(root: Path, now: datetime | None = None) -> list[str]:
    """One line per live member, as somebody choosing who to reach reads it.

    Four facts, because a listing naming members without saying what reaches
    them leaves a reader to guess which of them will hear anything: who they
    are, which checkout they are in, what they are on, and what carries a
    message to them.
    """
    names = called(root)

    def described(member: Member) -> list[str]:
        """The parts one member's line is joined from, blanks included."""
        return [
            names.get(member["id"]) or member["id"],
            Path(member["worktree"]).name if member["worktree"] else "",
            member["description"] or member["task"],
            member["delivery"],
        ]

    return [
        " — ".join(part for part in described(member) if part)
        for member in present(root, now)
        if member["running"]
    ]


def claim_holders(
    root: Path, target: str, mine: str, now: datetime | None = None
) -> list[str]:
    """Who else, still working here, is holding the path a write would land on.

    Live holders other than the asker. A claim expires with the session that
    made it, so a departed holder is nobody to ask; and a session meeting its
    own claim on every edit would be asked about its own work.

    Named where a session has a name and identified by id otherwise, because
    this reaches somebody deciding whom to ask, and an id is what you fall back
    on when nothing has been called anything yet.
    """
    live = live_ids(root, now)
    names = called(root)
    return sorted(
        {
            names.get(holder) or holder
            for claim in covering(root, Path(target).resolve(), live)
            for holder in [actor_id(found) for found in claim["holders"]]
            if holder and holder != mine
        }
    )


def digest_of(path: str) -> str:
    """What one file's bytes hash to, or nothing where they cannot be read.

    Carried on a claim so a later reader can tell the content a session left
    from whatever stands there now — which is what makes a claim evidence of a
    change rather than only an assertion that one happened.
    """
    try:
        return sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def depart(root: Path, member_id: str) -> bool:
    """End this member's row where it is standing; say whether one was written.

    The first of the two bare writes. A session's ending hook runs in a process
    with no typed writer to reach, and a row nobody ended reads as running until
    the pulse retires it — which is right for a session that was killed and
    needlessly vague for one that exited.

    A session that never joined leaves nothing, because a finish for nobody is
    a line every fold ignores and a store should not carry.
    """
    if not member_id:
        return False
    standing = members(root / ROSTER_FILE).get(f"{MEMBER_KIND}-{member_id}")
    if standing is None or not standing["running"]:
        return False
    return appended(
        root / ROSTER_FILE,
        [
            Finished(
                type="finished",
                actor=Actor(kind=MEMBER_KIND, id=member_id),
                at=datetime.now(UTC).isoformat(),
                summary="",
                error="",
            )
        ],
    )


def record_claims(root: Path, mine: str, paths: list[str], rivals: list[str]) -> bool:
    """Write down what one session's call changed, and who else it could be.

    The second of the two bare writes, and the dispatcher's: it runs after the
    work has already happened, so the call it belongs to cannot be undone by
    refusing, and a claim nobody could record costs a later reader an
    attribution while a raised exception would cost the session its ability to
    work.

    A claim per path. Where another session had a window open across the same
    moment, every name goes on the record instead of one being guessed at,
    because the next reader is deciding whether it is safe to write and a
    confident wrong author is worse than an honest pair.
    """
    actor = member_actor(root, mine) if mine else None
    if actor is None or not paths:
        return False
    contenders = [
        found for other in rivals for found in [member_actor(root, other)] if found
    ]
    stamped = datetime.now(UTC).isoformat()
    return appended(
        root / TOUCHES_FILE,
        [
            Touched(
                type="contested" if contenders else "touched",
                actor=actor,
                at=stamped,
                path=path,
                digest=digest_of(path),
                rivals=contenders,
            )
            for path in paths
        ],
    )
