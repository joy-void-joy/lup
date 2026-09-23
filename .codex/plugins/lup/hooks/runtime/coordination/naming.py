"""Naming a session for its work: the half every runtime's naming hook shares.

A session is called after its worktree until something renames it, and every
session opened in one checkout shares that worktree — so a roster of `dev`,
`dev-2` and `dev-3` tells a person nothing about which is doing what, and
neither does the runtime chrome that agrees with it. A person names a session
by its work, which the first prompt that says what the work is already
states. Each runtime's naming hook asks a model for that name through its own
CLI; everything around the asking is here.

**Naming is due while a session answers to nothing but the name it joined
with.** One name in its history is a default nobody chose; a second is a
rename, by a peer's tool, a person, or an earlier prompt's answer, and no
answer here overrides one. A runtime that reports what its chrome shows adds
one more condition: the chrome still shows that default or nothing, because a
title somebody set there is a choice too. A prompt that says nothing about the
work — a greeting, a "continue" — gets no name, and the next prompt is asked
again, up to the declared number of attempts.

**A name is settled against every live session's**, under the roster lock the
typed rename takes, and numbered where another session answers to it: the
model proposed it, nobody chose it, so it is a default in all but origin.

**The runtime follows the roster.** Whatever last renamed the roster — this
hook's answer or a peer's `coordination_rename` — is carried to the runtime's
own name for the session once, the next time this hook runs, and never again
until the roster's name moves. A title somebody set in the chrome in between
stands until then.

Only the root session's own prompts count. A child session that inherited its
launcher's environment carries the same member id, so a prompt is taken as
this member's only where nothing marks it as a child, its working directory is
the member's worktree, and — once the member records which native session it
is — its session id is that one: the checks the arrival binder makes.

Shipped into each plugin's ``hooks/runtime/coordination/`` beside the store it
reads, so it resolves on the bare interpreter a runtime spawns: the standard
library and nothing else. **Every failure is silence**; a prompt is not
something a name may hold up past its deadline or stop.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from .store import (
    MEMBER_KIND,
    TITLES_DIR,
    Member,
    Wake,
    conversation_of,
    current_name,
    loaded,
    member_path,
    names_of,
    names_taken,
    published,
    read_member,
    renamed,
    revised,
    roster_locked,
    session_actor,
    spoken_at,
    stamped,
    text,
    unique_cli_name,
)


class Naming(TypedDict):
    """How this project names a session, as its declaration compiled it.

    Written beside the hook by the generator, in the runtime's own spellings:
    ``model`` and ``effort`` are the words that runtime's CLI takes for the
    declared tier and rung.
    """

    model: str
    effort: str
    instruction: str
    attempts: int
    deadline_seconds: float
    longest: int


class Titling(TypedDict):
    """What one session's naming hook remembers between prompts.

    ``attempts`` counts the times a model was asked, answered or not;
    ``asked`` is when an ask still under way started, blank where none is,
    which keeps a slow ask from being started twice; ``pushed`` is the roster
    name the runtime was last given.
    """

    attempts: int
    asked: str
    pushed: str


class Arrival(TypedDict, total=False):
    """What a runtime hands its prompt hook on stdin, as far as naming reads it.

    Partial because the runtime owns the record, and both document more.
    """

    session_id: str
    cwd: str
    prompt: str
    agent_id: str
    agent_type: str


class Answer(TypedDict, total=False):
    """The structured answer the naming model is held to."""

    name: str | None


def answer_schema() -> str:
    """The JSON Schema the model's answer must meet: a name, or null for none.

    Handed to each runtime's CLI as the shape its structured output is held
    to, so an answer arrives as JSON :func:`named` reads rather than prose to
    be picked apart.
    """
    return json.dumps(
        {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
            "required": ["name"],
            "additionalProperties": False,
        }
    )


def settings(path: Path) -> Naming | None:
    """The compiled naming declaration beside the hook, or nothing unreadable.

    Checked field by field rather than trusted: the file is this generator's,
    but a hook that took a malformed one on faith would fail somewhere less
    obvious than here, where failing is silence.
    """
    found = loaded(path, Naming)
    if found is None:
        return None
    attempts, deadline, longest = (
        found.get("attempts"),
        found.get("deadline_seconds"),
        found.get("longest"),
    )
    if not (
        isinstance(attempts, int)
        and isinstance(deadline, int | float)
        and isinstance(longest, int)
    ):
        return None
    return Naming(
        model=text(found.get("model")),
        effort=text(found.get("effort")),
        instruction=text(found.get("instruction")),
        attempts=attempts,
        deadline_seconds=float(deadline),
        longest=longest,
    )


def compiled_for(host: Path) -> Naming | None:
    """The compiled declaration for the host half at *host*, or nothing unreadable.

    Under the host half's own name, beside the hooks manifest that registers
    it rather than beside the host half itself: everything under the runtime
    directory is source a policy evaluator's accepted snapshot is hashed over,
    and a data file there is refused as code nothing hashed.
    """
    return settings(host.parent.parent / host.with_suffix(".json").name)


def titling_path(root: Path, member_id: str) -> Path:
    """Where one member's naming hook keeps what it remembers."""
    return root / TITLES_DIR / f"{conversation_of(session_actor(member_id))}.json"


def recorded(root: Path, member_id: str, titling: Titling) -> Titling:
    """Remember *titling* for this member's next prompt, and hand it back."""
    published(titling_path(root, member_id), titling)
    return titling


def recalled(root: Path, member_id: str) -> Titling | None:
    """What this member's naming hook remembers, or nothing where it never looked."""
    found = loaded(titling_path(root, member_id), Titling)
    if found is None:
        return None
    attempts = found.get("attempts")
    return Titling(
        attempts=attempts if isinstance(attempts, int) else 0,
        asked=text(found.get("asked")),
        pushed=text(found.get("pushed")),
    )


def looked(root: Path, member_id: str, member: Member) -> Titling:
    """What this member's naming hook remembers, begun on a first look.

    A first look takes the roster's name as the one the runtime was given: a
    launched session's runtime was handed it at launch, and one nobody
    launched has nothing better to show than its own default.
    """
    found = recalled(root, member_id)
    if found is not None:
        return found
    return recorded(
        root, member_id, Titling(attempts=0, asked="", pushed=current_name(member))
    )


def owning(root: Path, member_id: str, arrival: Arrival) -> Member | None:
    """This member, where the prompt is its own root session's, and nothing else.

    A missing member is nothing to name: a session that has not joined yet is
    named at a later prompt, once its tool server has put it on the roster.
    """
    if not member_id or arrival.get("agent_id") or arrival.get("agent_type"):
        return None
    member = read_member(member_path(root, session_actor(member_id)), running=True)
    if member is None or member.get("kind") != MEMBER_KIND:
        return None
    cwd, worktree = text(arrival.get("cwd")), text(member.get("worktree"))
    if not cwd or not worktree or Path(cwd).resolve() != Path(worktree).resolve():
        return None
    bound = text(member.get("wake", Wake()).get("session"))
    if bound and bound != text(arrival.get("session_id")):
        return None
    return member


def due(
    member: Member,
    titling: Titling,
    naming: Naming,
    shown: str | None,
    now: datetime | None = None,
) -> bool:
    """Whether this prompt should ask a model what the session is called.

    *shown* is what the runtime reports its chrome showing, or ``None`` where
    it reports nothing. An ask still inside its deadline is not started again:
    the answer it is waiting for settles the name either way, and one that
    died without concluding stops counting as under way once the deadline it
    was given has passed.
    """
    if len(names_of(member)) != 1 or titling["attempts"] >= naming["attempts"]:
        return False
    if shown is not None and shown not in ("", current_name(member)):
        return False
    started = spoken_at(titling["asked"]) if titling["asked"] else None
    return (
        started is None
        or ((now or datetime.now(UTC)) - started).total_seconds()
        >= naming["deadline_seconds"]
    )


def asking(root: Path, member_id: str, titling: Titling) -> Titling:
    """Record that one more ask has started, before it starts."""
    return recorded(
        root,
        member_id,
        Titling(
            attempts=titling["attempts"] + 1, asked=stamped(), pushed=titling["pushed"]
        ),
    )


def concluded(root: Path, member_id: str, titling: Titling, given: str) -> Titling:
    """Record that no ask is under way, and that the runtime was *given* a name.

    Blank *given* is an ask that named nothing, which leaves what the runtime
    was last given where it was.
    """
    return recorded(
        root,
        member_id,
        Titling(
            attempts=titling["attempts"], asked="", pushed=given or titling["pushed"]
        ),
    )


def fitting(name: str, longest: int) -> bool:
    """Whether *name* has the shape a session name takes.

    Lowercase letters and digits in words joined by single hyphens, as a
    worktree is named, and no longer than the declaration allows: it is what a
    person types to reach the session, and what its runtime shows.
    """
    return (
        0 < len(name) <= longest
        and all(
            character.isascii()
            and (character.islower() or character.isdigit() or character == "-")
            for character in name
        )
        and not name.startswith("-")
        and not name.endswith("-")
        and "--" not in name
    )


def named(answer: Answer | None, longest: int) -> str:
    """The name a model's structured answer carries, blank for none or a malformed one."""
    name = answer.get("name") if isinstance(answer, dict) else None
    return name if isinstance(name, str) and fitting(name, longest) else ""


def answered(reply: str, longest: int) -> str:
    """The name a model's answer carries where it arrives as JSON text."""
    try:
        answer: Answer = json.loads(reply)
    except ValueError:
        return ""
    return named(answer, longest)


def settled(root: Path, member_id: str, wanted: str) -> str:
    """Rename this member to *wanted*, numbered past any live session's name.

    Decided under the roster lock and against the member as it is then: a
    member renamed since this hook read it keeps that rename, and nothing is
    written. Hands back the name taken, or blank where none was.
    """
    taken = ""

    def rename(member: Member) -> Member:
        nonlocal taken
        if len(names_of(member)) != 1:
            return member
        taken = unique_cli_name(wanted, names_taken(root, member_id))
        return renamed(member, taken)

    try:
        with roster_locked(root):
            written = revised(root, session_actor(member_id), rename)
    except OSError:
        return ""
    return taken if written is not None else ""


def pending(member: Member, titling: Titling) -> str:
    """The roster's name where the runtime has not been given it yet, else blank."""
    name = current_name(member)
    return name if name != titling["pushed"] else ""
