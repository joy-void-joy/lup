# lup: ignore[constant-declaration]
# The envelope's names are the wire spelling both runtimes document for their
# prompt event — a fact about those runtimes rather than a taste. Everything
# the store itself is spelled with comes from the fold beside this.
"""What changed on this repository's roster since one session last looked.

A session learns who else is working in this clone only when it asks — a
`coordination_peers` call, or a native listing the policy attaches the roster
to — and the moment it most needs to know is the one it has no reason to ask
at: a prompt has just arrived, and whoever started since the last one is
invisible. This is the fold that answers at that moment, run by a hook the
runtime fires when a prompt is submitted, and it says only what is different
from the last time this session looked.

Shipped into each plugin's ``hooks/runtime/coordination/``, so everything
here resolves on a bare interpreter: standard library, and the fold beside it
in the same package. That is what lets it reach a person's own session, which
has the plugin and no process of lup's to close over.

**What it adds to the fold is the difference.** :mod:`.store` answers who is
here, what each holds, and what everyone is called; the whole of this module
is what a *prompt* does with that — keep one look per session, compare it
against the next, and say the part that moved.

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
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

from .store import (
    LOOKS_DIR,
    MEMBER_KIND,
    Held,
    Member,
    beat,
    called,
    held,
    loaded,
    present,
    reset,
    text,
)

MOVED_LINE = (
    "This conversation was rewound or cleared, so what this session's roster "
    "row said it was doing is reset; `coordination_describe` once you know."
)
"""The one line a prompt gets when its conversation is not the one last looked from."""


class Seen(TypedDict):
    """One peer as this session last saw it: the facts a change is read against."""

    name: str
    worktree: str
    doing: str
    holding: list[str]


class Conversation(TypedDict):
    """Which conversation a look was taken from: the transcript, and its roots.

    Two looks from one conversation agree on both. A rewind appends a root to
    the same transcript and a clear opens another transcript, so either
    difference says the conversation this session's row described is gone.
    """

    transcript: str
    roots: int


class TranscriptEntry(TypedDict, total=False):
    """One line of a runtime's transcript, as far as counting roots needs it."""

    type: str
    uuid: str
    parentUuid: str | None


class Look(TypedDict):
    """Everything one look at the roster records, keyed so the next can diff it.

    ``contested`` is keyed by the claim rather than by the peer, because a
    contested path is one fact about two sessions and a reader is told it
    once, with every name on it.
    """

    peers: dict[str, Seen]
    contested: dict[str, list[str]]
    conversation: Conversation


class Folded(TypedDict):
    """One look, and the roster fold it was read from.

    The fold rides beside the look because a departure needs what the look
    deliberately leaves out: only running peers are recorded, so the file does
    not grow with every session that ever stopped, and a departed peer's
    summary is read from the fold at the moment it is reported.
    """

    look: Look
    members: dict[str, Member]


class Prompt(TypedDict, total=False):
    """What the runtime hands the hook on stdin, as far as this reads it.

    Partial because the runtime owns this record: both document more fields
    than these, and a field added there must not make the payload unreadable
    here.
    """

    session_id: str
    cwd: str
    transcript_path: str


class Pushed(TypedDict):
    """The runtime's own envelope fields, in the runtime's own spelling."""

    hookEventName: str
    additionalContext: str


class HookOutput(TypedDict):
    """What this hook prints. ``additionalContext`` nested here is what is read."""

    hookSpecificOutput: Pushed


def conversation(transcript: str) -> Conversation:
    """The conversation this prompt belongs to: which transcript, and how many roots.

    A turn of the conversation is a ``user`` or ``assistant`` entry; the
    attachments, snapshots and bookkeeping in the same file parent nothing a
    turn descends from. A turn with no parent is a root, and a conversation
    has exactly one until the runtime rewinds it: the rewind appends a new
    root to the same file, which is the one sign it leaves — measured on
    Claude Code, whose documentation is silent on it. Codex has no rewind, and
    its transcript yields no such root, so the count stays at zero there.

    Read at prompt time, so a root the runtime writes only after this hook has
    run is noticed at the next prompt. No transcript reads as no conversation,
    which two looks then agree on.
    """
    if not transcript:
        return Conversation(transcript="", roots=0)
    roots = sum(
        1
        for entry in loaded(Path(transcript), TranscriptEntry)
        if text(entry.get("type")) in ("user", "assistant")
        and text(entry.get("uuid"))
        and entry.get("parentUuid") is None
    )
    return Conversation(transcript=transcript, roots=roots)


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


def looked(root: Path, mine: str, checkout: str, transcript: str = "") -> Folded:
    """One look at the roster as this session reads it, and the fold behind it.

    The fold is :mod:`.store`'s, so a session the pulse has retired reads as
    finished here exactly as it does to a tool call, its claims stop being
    reported, and a description older than that session's conversation reset
    reads as unsaid — a peer is told the task that session is on rather than
    what a discarded conversation said.
    """
    members = {
        member["id"]: member
        for member in present(root, mine=mine)
        if member["kind"] == MEMBER_KIND
    }
    names = called(root)
    live = [member_id for member_id, member in members.items() if member["running"]]
    claims = [claim for claim in held(root, live) if concerns(claim, checkout)]

    def name(member_id: str) -> str:
        """What a peer is called, falling back to the id nothing has named."""
        return names.get(member_id) or member_id

    def holders(claim: Held) -> list[str]:
        """Every session on one claim, by id, as the look keys them."""
        return [text(holder.get("id")) for holder in claim["holders"]]

    peers = {
        member_id: Seen(
            name=name(member_id),
            worktree=Path(member["worktree"]).name if member["worktree"] else "",
            doing=member["description"] or member["task"],
            holding=sorted(
                claim["subject"] for claim in claims if member_id in holders(claim)
            ),
        )
        for member_id, member in members.items()
        if member_id != mine and member["running"]
    }
    contested = {
        claim["subject"]: [name(holder) for holder in holders(claim)]
        for claim in claims
        if len(claim["holders"]) > 1
    }
    return Folded(
        look=Look(
            peers=peers, contested=contested, conversation=conversation(transcript)
        ),
        members=members,
    )


def last_look(cursor: Path) -> Look | None:
    """What this session saw last time, or nothing where it never looked.

    A look that will not parse reads as never having looked, which re-baselines
    rather than replays: the cost is one pointer line, and the alternative —
    reporting every peer as arrived — is the replay the baseline exists to
    avoid.
    """
    try:
        stored: Look = json.loads(cursor.read_text("utf-8"))
        return Look(
            peers=stored["peers"],
            contested=stored["contested"],
            conversation=stored["conversation"],
        )
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


def changes(root: Path, mine: str, checkout: Path, transcript: str = "") -> list[str]:
    """What this session is told at this prompt, and nothing where nothing moved.

    The first look writes the baseline and answers with the pointer alone.
    Every later look answers with the differences and advances the baseline
    only where something differed, so a quiet roster costs no write either.

    A look from a conversation that is not the one last looked from — a rewind
    appended a root to the transcript, or a clear opened another — stamps the
    reset and starts over from a baseline, because what the row said and what
    this session last saw both belong to the conversation that is gone.
    """
    if not mine:
        return []
    folded = looked(root, mine, str(checkout), transcript)
    if not folded["members"]:
        return []
    beat(root, mine)
    cursor = root / LOOKS_DIR / f"{MEMBER_KIND}-{mine}.json"
    before = last_look(cursor)
    now = folded["look"]
    if before is None:
        remember(cursor, now)
        return [pointer(len(now["peers"]))]
    if before["conversation"] != now["conversation"]:
        reset(root, mine)
        remember(cursor, now)
        return [MOVED_LINE, pointer(len(now["peers"]))]
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
    stdin supplies the session's own id as the fallback, the checkout the
    prompt was submitted from, and the transcript it belongs to. Every failure
    is silence, because a prompt is not something a broken roster may stop.
    """
    try:
        root, member, event = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
        prompt: Prompt = json.load(sys.stdin)
        lines = changes(
            root,
            member or prompt.get("session_id", ""),
            Path(prompt.get("cwd", "")),
            prompt.get("transcript_path", ""),
        )
    except Exception:
        return
    if lines:
        print(json.dumps(envelope(event, lines)))


if __name__ == "__main__":
    main()
