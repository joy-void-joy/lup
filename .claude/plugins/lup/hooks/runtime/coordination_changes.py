# lup: ignore[constant-declaration]
# The store's file names are restated because a verbatim copy cannot import
# them, and pinned back to the typed writers by a test; the envelope's names
# are the wire spelling both runtimes document for their prompt event.
"""What changed on this repository's roster since one session last looked.

A session learns who else is working in this clone only when it asks — a
`coordination_peers` call, or a native listing the policy attaches the roster
to — and the moment it most needs to know is the one it has no reason to ask
at: a prompt has just arrived, and whoever started since the last one is
invisible. This is the fold that answers at that moment, run by a hook the
runtime fires when a prompt is submitted, and it says only what is different
from the last time this session looked.

Shipped verbatim into each plugin's ``hooks/runtime/``, so everything here
resolves on a bare interpreter: standard library only, no ``lup`` import. That
is what lets it reach a person's own session, which has the plugin and no
process of lup's to close over.

**A reader, never the authority.** :mod:`lup.coordination.roster`,
:mod:`lup.coordination.identity` and :mod:`lup.coordination.touches` write
the three records this folds and own what each means; this reads their settled
shapes and keeps one file of its own, the last look, beside the delivery
positions. The spellings the halves share are pinned by a test rather than
shared by an import.

**The first look is a baseline, not a replay** — the convention the watcher
keeps. A session attaching to a repository already at work is told where the
roster is, once, and everything after that is a difference. What is pushed is
what changes the reader's next decision: a path somebody holds under this
checkout, contested ones first, then who arrived, who left, and who now says
they are on something else. A quiet roster costs no context at all.

**It fails open.** Every failure is silence: a roster that cannot be read
costs the session one look and never the prompt it was attached to.

The output is the shape both runtimes document for the event that fires on a
submitted prompt — ``hookSpecificOutput`` carrying ``hookEventName`` and
``additionalContext``, read from stdout on exit 0. Claude Code documents it
under "UserPromptSubmit" at https://code.claude.com/docs/en/hooks, and Codex
under the same event name at https://learn.chatgpt.com/docs/hooks, where
https://developers.openai.com/codex/hooks redirects. The event's name is the
one word here a runtime owns, so it arrives as an argument from the adapter
that spells it.

``TypedDict`` throughout, partial for every record another module writes:
pydantic is not here to be imported, and a field added by the typed writer
must not make its record unreadable here.
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

ROSTER_FILE = "roster.jsonl"
NAMES_FILE = "names.jsonl"
TOUCHES_FILE = "touches.jsonl"
MEMBER_KIND = "session"
"""The store's own spellings, restated because a verbatim copy cannot import them.

Pinned against the typed writers by a test, which is what stands in for the
import: a rename there fails the suite here rather than quietly folding a
file nobody writes.
"""

LOOKS_DIR = "looks"
"""Where each session's last look is kept, one file per member, beside the mail
positions the delivery reader keeps the same way."""


class Actor(TypedDict, total=False):
    """Whom a record attributes itself to, as the roster and touch records spell it."""

    kind: str
    id: str


class RosterRecord(TypedDict, total=False):
    """One record on the roster stream, as far as folding it needs to know."""

    type: str
    actor: Actor
    task: str
    description: str
    summary: str
    worktree: str


class NameRecord(TypedDict, total=False):
    """One member answering to one name from that moment on."""

    id: str
    cli_name: str


class TouchRecord(TypedDict, total=False):
    """One thing that happened to a claim, as far as folding it needs to know."""

    type: str
    actor: Actor
    path: str
    rivals: list[Actor]


class Seen(TypedDict):
    """One peer as this session last saw it: the facts a change is read against."""

    name: str
    worktree: str
    doing: str
    holding: list[str]


class Look(TypedDict):
    """Everything one look at the roster records, keyed so the next can diff it.

    ``contested`` is keyed by the claim rather than by the peer, because a
    contested path is one fact about two sessions and a reader is told it
    once, with every name on it.
    """

    peers: dict[str, Seen]
    contested: dict[str, list[str]]


class Member(TypedDict):
    """One session as the roster's fold leaves it, alive or finished."""

    task: str
    description: str
    summary: str
    worktree: str
    running: bool


class Folded(TypedDict):
    """One look, and the roster fold it was read from.

    The fold rides beside the look because a departure needs what the look
    deliberately leaves out: only running peers are recorded, so the file does
    not grow with every session that ever stopped, and a departed peer's
    summary is read from the fold at the moment it is reported.
    """

    look: Look
    members: dict[str, Member]


class Held(TypedDict):
    """One claim as the touch record's fold leaves it, with its live holders."""

    subject: str
    path: str
    prefix: bool
    holders: list[str]


class Prompt(TypedDict, total=False):
    """What the runtime hands the hook on stdin, as far as this reads it.

    Partial because the runtime owns this record: both document more fields
    than these, and a field added there must not make the payload unreadable
    here.
    """

    session_id: str
    cwd: str


class Pushed(TypedDict):
    """The runtime's own envelope fields, in the runtime's own spelling."""

    hookEventName: str
    additionalContext: str


class HookOutput(TypedDict):
    """What this hook prints. ``additionalContext`` nested here is what is read."""

    hookSpecificOutput: Pushed


def text(value: str | None) -> str:
    """A field as a string, blank where the record carries something else.

    The record's declared type says string; the file another process wrote
    says whatever it says, so the value is checked rather than trusted.
    """
    return value if isinstance(value, str) else ""


def actor_id(actor: Actor | None, kind: str = "") -> str:
    """The id an actor object carries, blank where it is not one of *kind*.

    An empty *kind* accepts any: a touch record's holder is an id whatever it
    is, while a roster fold wants sessions and not the person on it.
    """
    if not isinstance(actor, dict):
        return ""
    if kind and text(actor.get("kind")) != kind:
        return ""
    return text(actor.get("id"))


def loaded[Record](path: Path, shape: type[Record]) -> list[Record]:
    """Every line that is a JSON object, read as *shape*, skipping the rest.

    A torn final line is the ordinary state of a store another session is
    appending to, and a malformed one must not stop the session reading the
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


def standing(path: Path) -> dict[str, Member]:
    """Every session the roster has held, by id, folded from its own record.

    Finished members are kept with ``running`` false rather than dropped,
    because a departure is read off the finished record: what a session said
    it concluded is on that record and nowhere else.
    """
    records = loaded(path, RosterRecord)
    # lup: ignore[empty-collection] — a fold whose every step reads what the
    # steps before it left: a description updates a member an earlier record
    # created, which is the one shape a comprehension cannot spell
    members: dict[str, Member] = {}
    for record in records:
        held = actor_id(record.get("actor"), MEMBER_KIND)
        if not held:
            continue
        match text(record.get("type")):
            case "spawned" | "joined":
                members[held] = Member(
                    task=text(record.get("task")),
                    description=text(record.get("description")),
                    summary="",
                    worktree=text(record.get("worktree")),
                    running=True,
                )
            case "described" if held in members:
                members[held]["description"] = text(record.get("description"))
            case "finished" if held in members:
                members[held]["running"] = False
                members[held]["summary"] = text(record.get("summary"))
            case _:
                continue
    return members


# lup: ignore[dict-str-payload] — keyed by member id, an identity the roster's
# own module mints and a verbatim copy has no type of lup's to name it with
def called(path: Path) -> dict[str, str]:
    """What each member is called now, the latest record for an id winning."""
    records = loaded(path, NameRecord)
    return {
        text(record.get("id")): text(record.get("cli_name"))
        for record in records
        if text(record.get("id")) and text(record.get("cli_name"))
    }


def held(path: Path, live: list[str]) -> list[Held]:
    """Every claim a live session holds, holders narrowed to the live ones.

    Keyed by kind as well as path, because locking a directory and touching a
    file of that name are different claims. Expiry is the roster's: a claim
    whose every holder has stopped is gone, and one holder's leaving takes
    only that name off a contested claim.
    """
    records = loaded(path, TouchRecord)
    # lup: ignore[empty-collection] — a fold whose every step reads what the
    # steps before it left: a release answers against the claim an earlier
    # record created, which is the one shape a comprehension cannot spell
    claims: dict[str, Held] = {}
    for record in records:
        holder = actor_id(record.get("actor"))
        path_text = text(record.get("path"))
        if not holder or not path_text:
            continue
        kind = text(record.get("type"))
        prefix = kind in ("locked", "released")
        subject = f"{'under' if prefix else 'at'} {path_text}"
        match kind:
            case "touched" | "contested":
                rivals = record.get("rivals")
                claims[subject] = Held(
                    subject=subject,
                    path=path_text,
                    prefix=False,
                    holders=[
                        holder,
                        *[
                            actor_id(rival)
                            for rival in (rivals if isinstance(rivals, list) else [])
                            if actor_id(rival)
                        ],
                    ],
                )
            case "locked":
                claims[subject] = Held(
                    subject=subject, path=path_text, prefix=True, holders=[holder]
                )
            case "released" if (
                subject in claims and holder in claims[subject]["holders"]
            ):
                del claims[subject]
            case _:
                continue
    return [
        Held(
            subject=claim["subject"],
            path=claim["path"],
            prefix=claim["prefix"],
            holders=[holder for holder in claim["holders"] if holder in live],
        )
        for claim in claims.values()
        if any(holder in live for holder in claim["holders"])
    ]


def within(path: str, root: str) -> bool:
    """Whether one absolute path is the root or lies beneath it."""
    return bool(root) and (path == root or path.startswith(root + "/"))


def concerns(claim: Held, checkout: str) -> bool:
    """Whether a claim names something a session in this checkout could write.

    A touch or lock inside the checkout, or a lock over a prefix the checkout
    itself lies under. Claims are keyed by absolute path, so a session in
    another worktree holding its own copy of a file is not this session's
    business at prompt time — the merge reconciles those, and the roster
    still lists them for whoever asks.
    """
    return within(claim["path"], checkout) or (
        claim["prefix"] and within(checkout, claim["path"])
    )


def looked(root: Path, mine: str, checkout: str) -> Folded:
    """One look at the roster as this session reads it, and the fold behind it."""
    members = standing(root / ROSTER_FILE)
    names = called(root / NAMES_FILE)
    live = [held_id for held_id, member in members.items() if member["running"]]
    claims = [
        claim for claim in held(root / TOUCHES_FILE, live) if concerns(claim, checkout)
    ]

    def name(member_id: str) -> str:
        return names.get(member_id) or member_id

    peers = {
        member_id: Seen(
            name=name(member_id),
            worktree=Path(member["worktree"]).name if member["worktree"] else "",
            doing=member["description"] or member["task"],
            holding=sorted(
                claim["subject"] for claim in claims if member_id in claim["holders"]
            ),
        )
        for member_id, member in members.items()
        if member_id != mine and member["running"]
    }
    contested = {
        claim["subject"]: [name(holder) for holder in claim["holders"]]
        for claim in claims
        if len(claim["holders"]) > 1
    }
    return Folded(look=Look(peers=peers, contested=contested), members=members)


def last_look(cursor: Path) -> Look | None:
    """What this session saw last time, or nothing where it never looked.

    A look that will not parse reads as never having looked, which re-baselines
    rather than replays: the cost is one pointer line, and the alternative —
    reporting every peer as arrived — is the replay the baseline exists to
    avoid.
    """
    try:
        stored: Look = json.loads(cursor.read_text("utf-8"))
        return Look(peers=stored["peers"], contested=stored["contested"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remember(cursor: Path, look: Look) -> None:
    """Record this look atomically, so a crash re-baselines instead of tearing."""
    cursor.parent.mkdir(parents=True, exist_ok=True)
    temporary = cursor.with_suffix(".writing")
    temporary.write_text(json.dumps(look), encoding="utf-8")
    temporary.replace(cursor)


def pointer(others: int) -> str:
    """The one line a first prompt gets: how many are here, and where to look."""
    match others:
        case 0:
            return (
                "No other session is working in this repository; "
                "`coordination_peers` lists whoever arrives."
            )
        case 1:
            return (
                "1 other session is working in this repository; "
                "`coordination_peers` lists it."
            )
        case _:
            return (
                f"{others} other sessions are working in this repository; "
                "`coordination_peers` lists them."
            )


def differences(before: Look, now: Look, members: dict[str, Member]) -> list[str]:
    """A line per change between two looks, the ones that stop a write first.

    Contested paths, then paths a peer holds here, then arrivals, departures
    and redescriptions: the order a session about to write needs them in. A
    subject reported as contested is not repeated as a holding beneath it.
    """

    def held_before(member_id: str) -> list[str]:
        seen = before["peers"].get(member_id)
        return seen["holding"] if seen else []

    def summary_of(member_id: str) -> str:
        member = members.get(member_id)
        return member["summary"] if member else ""

    contested = [
        f"contested {subject} — {', '.join(holders)}"
        for subject, holders in sorted(now["contested"].items())
        if subject not in before["contested"]
    ]
    holding = [
        f"{seen['name']} holding {subject}"
        for member_id, seen in now["peers"].items()
        for subject in seen["holding"]
        if subject not in held_before(member_id) and subject not in now["contested"]
    ]
    arrived = [
        " — ".join(
            part
            for part in (f"{seen['name']} arrived", seen["worktree"], seen["doing"])
            if part
        )
        for member_id, seen in now["peers"].items()
        if member_id not in before["peers"]
    ]
    departed = [
        " — ".join(
            part for part in (f"{seen['name']} left", summary_of(member_id)) if part
        )
        for member_id, seen in before["peers"].items()
        if member_id not in now["peers"]
    ]
    redescribed = [
        f"{seen['name']} now: {seen['doing']}"
        for member_id, seen in now["peers"].items()
        if member_id in before["peers"]
        and seen["doing"] != before["peers"][member_id]["doing"]
    ]
    return [*contested, *holding, *arrived, *departed, *redescribed]


def changes(root: Path, mine: str, checkout: Path) -> list[str]:
    """What this session is told at this prompt, and nothing where nothing moved.

    The first look writes the baseline and answers with the pointer alone.
    Every later look answers with the differences and advances the baseline
    only where something differed, so a quiet roster costs no write either.
    """
    if not mine:
        return []
    folded = looked(root, mine, str(checkout))
    if not folded["members"]:
        return []
    cursor = root / LOOKS_DIR / f"{MEMBER_KIND}-{mine}.json"
    before = last_look(cursor)
    now = folded["look"]
    if before is None:
        remember(cursor, now)
        return [pointer(len(now["peers"]))]
    lines = differences(before, now, folded["members"])
    if now != before:
        remember(cursor, now)
    return lines


def envelope(event: str, lines: list[str]) -> HookOutput:
    """The hook output carrying these lines, in the shape both runtimes read."""
    return HookOutput(
        hookSpecificOutput=Pushed(
            hookEventName=event, additionalContext="\n".join(lines)
        )
    )


def main() -> None:
    """Fold, or say nothing at all and let the prompt through.

    The store root, this member's launcher-proven id (blank where nothing
    launched it) and the event name arrive as arguments; the prompt payload on
    stdin supplies the session's own id as the fallback and the checkout the
    prompt was submitted from. Every failure is silence, because a prompt is
    not something a broken roster may stop.
    """
    try:
        root, member, event = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
        prompt: Prompt = json.load(sys.stdin)
        lines = changes(
            root,
            member or prompt.get("session_id", ""),
            Path(prompt.get("cwd", "")),
        )
    except Exception:
        return
    if lines:
        print(json.dumps(envelope(event, lines)))


if __name__ == "__main__":
    main()
