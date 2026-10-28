"""The kept sessions as text, for `lup-dev transcripts`: listed, the operator's words each with what it answered, whole, and searched.

`packages/lup-transcripts/README.md`, *Reading them*. The operator's words
come first: a past session is read for what they said and what they were
answering, which is where a design's reasons are; the whole conversation, the
agent's text with each run of tool calls folded to a line, is there for what
happened between. Each says whose home its record was kept from, since what a
room's says is the room's word for it.
"""

from datetime import UTC, datetime
from itertools import groupby

from lup.types import Model
from lup_dev.host.records import Called, Entry, Said, Transcript, Whose
from lup_transcripts.errors import LupTranscriptsError


class TranscriptError(LupTranscriptsError):
    """A session asked for isn't among those kept, or more than one answers to it."""


class Session(Model):
    """A kept session: what its record says, and whose home it was kept from."""

    transcript: Transcript
    whose: Whose


def kept_from(whose: Whose) -> str:
    """Say whose home a record was kept from, as a line says it.

    >>> kept_from("rooms")
    "a room's home"
    """
    match whose:
        case "host":
            return "your own directory"
        case "rooms":
            return "a room's home"
        case "shared":
            return "the home rooms share"


def where(session: Session) -> str:
    """Say where a session ran; `?` where its record doesn't say."""
    return f"{session.transcript.directory or '?'}"


def when(at: datetime | None) -> str:
    """Say a moment by the operator's own clock, to the minute; `?` where it isn't known."""
    return "?" if at is None else f"{at.astimezone():%Y-%m-%d %H:%M}"


def begun(session: Session) -> datetime:
    """Return when a session started, for ordering: the earliest moment there is where it isn't known."""
    return session.transcript.started() or datetime.min.replace(tzinfo=UTC)


def called(session: Transcript) -> str:
    """Say a session by its name, and the runtime and id it's known by."""
    name = session.title or "untitled"
    return f"`{name}` ({session.runtime} {session.session})"


def listed(sessions: list[Session]) -> list[str]:
    """Return a line for each session, newest first: when it started, its name and id, how many times the operator spoke, where it ran, and whose home its record was kept from."""
    ordered = sorted(sessions, key=begun)
    return [
        f"{when(each.transcript.started())}  {called(each.transcript)}  "
        f"{len(each.transcript.operators())} from you  in {where(each)}, kept from "
        f"{kept_from(each.whose)}"
        for each in reversed(ordered)
    ]


def chosen(sessions: list[Session], named: str, whose: Whose | None = None) -> Session:
    """Return the session `named` names: by its id, the start of its id, or its name; among those kept from `whose` home, where it's given.

    A record a room kept carrying a host session's id is the room's, never
    taken for the host's, so a session kept from two homes is two, and
    `--from` reads one. Raise `TranscriptError` where none is, or several are,
    naming them.
    """
    found = [
        each
        for each in sessions
        if (each.transcript.session.startswith(named) or each.transcript.title == named)
        and (whose is None or each.whose == whose)
    ]
    match found:
        case [one]:
            return one
        case []:
            message = (
                f"no kept session is `{named}`, by its id, the start of its id or "
                "its name: `lup-dev transcripts list` lists them"
            )
        case _:
            message = (
                f"several kept sessions are `{named}`: "
                + ", ".join(
                    f"{called(each.transcript)} kept from {kept_from(each.whose)}"
                    for each in found
                )
                + "; a longer id, or `--from host`, `--from rooms` or `--from "
                "shared` for whose home it was kept from, chooses one"
            )
    raise TranscriptError(message)


def heading(session: Session) -> str:
    """Say a session as its reading opens: its name and id, when it started, where it ran, and whose home it was kept from, which a room's says the room writes."""
    said = session.transcript
    writes = "" if session.whose == "host" else ", which rooms write"
    return (
        f"{called(said)}, from {when(said.started())}, in {where(session)}, kept "
        f"from {kept_from(session.whose)}{writes}"
    )


def indented(text: str, by: str = "    ") -> str:
    """Return `text` with each line indented `by`."""
    return "\n".join(f"{by}{line}" if line else "" for line in text.splitlines())


def answered(kept: Session) -> str:
    """Return the operator's words in `kept`, numbered, each after what the agent last said before it: what it answered."""
    session = kept.transcript

    def part(number: int, said: Said) -> str:
        before = session.replied(said)
        answering = (
            "  (the session's first words)"
            if before is None
            else f"  answering the agent:\n{indented(before.text)}"
        )
        return f"[{number}] {when(said.at)}\n{answering}\n  you:\n{indented(said.text)}"

    parts = [part(at, said) for at, said in enumerate(session.operators(), start=1)]
    return "\n\n".join([heading(kept), *parts]) + "\n"


def whole(kept: Session) -> str:
    """Return everything said in `kept`, in order, each run of tool calls folded to a line naming them."""
    steps = stepped(kept.transcript.entries)
    return "\n\n".join([heading(kept), *steps]) + "\n"


def stepped(entries: list[Entry]) -> list[str]:
    """Say each step of `entries` in order: each thing said, and each run of tool calls folded to a line naming them."""
    runs = groupby(entries, key=lambda each: isinstance(each, Called))
    return [
        folded([each.tool for each in run if isinstance(each, Called)])
        if calling
        else "\n\n".join(spoken(each) for each in run if isinstance(each, Said))
        for calling, run in runs
    ]


def spoken(said: Said) -> str:
    """Say one thing said, by whom and when."""
    who = "you" if said.by == "operator" else "the agent"
    return f"{who}, {when(said.at)}:\n{indented(said.text)}"


def folded(tools: list[str]) -> str:
    """Say a run of tool calls in a line, each tool once with how many times in a row.

    >>> folded(["Read", "Read", "Bash", "Read"])
    '· called Read x2, Bash, Read'
    """
    named = [counted(tool, len(list(run))) for tool, run in groupby(tools)]
    return f"· called {', '.join(named)}"


def counted(tool: str, times: int) -> str:
    """Say a tool called `times` times in a row."""
    return tool if times == 1 else f"{tool} x{times}"


def found(sessions: list[Session], words: list[str], *, whole: bool = False) -> str:
    """Return each time the operator said all of `words`, any case, newest session first: the session, when, their words, and what they answered, its first line, or `whole`."""
    wanted = [word.casefold() for word in words]

    def matched(said: Said) -> bool:
        text = said.text.casefold()
        return all(word in text for word in wanted)

    def answering(before: Said | None) -> str:
        if before is None:
            return "  answering: "
        if whole:
            return f"  answering:\n{indented(before.text)}"
        return f"  answering: {first_line(before.text)}"

    def hit(kept: Session, said: Said) -> str:
        session = kept.transcript
        return (
            f"{called(session)}, {when(said.at)}, kept from {kept_from(kept.whose)}\n"
            f"{answering(session.replied(said))}\n  you:\n{indented(said.text)}"
        )

    hits = [
        hit(kept, said)
        for kept in sorted(sessions, key=begun, reverse=True)
        for said in kept.transcript.operators()
        if matched(said)
    ]
    if not hits:
        return f"You never said {' '.join(words)!r} in a kept session.\n"
    return "\n\n".join(hits) + "\n"


def first_line(text: str) -> str:
    """Return a text's first line that isn't empty."""
    return next((line for line in text.splitlines() if line.strip()), "")
