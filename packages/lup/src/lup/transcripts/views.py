"""The kept sessions as text, for `lup-dev transcripts`: listed, the operator's words each with what it answered, whole, and searched.

`docs/declaration.md`, *Transcripts*. The operator's words come first: a past
session is read for what they said and what they were answering, which is where
a design's reasons are; the whole conversation, the agent's text with each run
of tool calls folded to a line, is there for what happened between.
"""

from datetime import UTC, datetime
from itertools import groupby

from lup.errors import LupError
from lup_dev.host.records import Called, Said, Transcript


class TranscriptError(LupError):
    """A session asked for isn't among those kept, or more than one answers to it."""


def when(at: datetime | None) -> str:
    """Say a moment by the operator's own clock, to the minute; `?` where it isn't known."""
    return "?" if at is None else f"{at.astimezone():%Y-%m-%d %H:%M}"


def begun(session: Transcript) -> datetime:
    """Return when a session started, for ordering: the earliest moment there is where it isn't known."""
    return session.started() or datetime.min.replace(tzinfo=UTC)


def called(session: Transcript) -> str:
    """Say a session by its name, and the runtime and id it's known by."""
    name = session.title or "untitled"
    return f"`{name}` ({session.runtime} {session.session})"


def listed(sessions: list[Transcript]) -> list[str]:
    """Return a line for each session, newest first: when it started, its name and id, how many times the operator spoke, and where it ran."""
    ordered = sorted(sessions, key=begun)
    return [
        f"{when(each.started())}  {called(each)}  {len(each.operators())} from you"
        f"  in {each.directory or '?'}"
        for each in reversed(ordered)
    ]


def chosen(sessions: list[Transcript], named: str) -> Transcript:
    """Return the session `named` names: by its id, the start of its id, or its name.

    Raise `TranscriptError` where none does, or several do, naming them.
    """
    found = [
        each
        for each in sessions
        if each.session.startswith(named) or each.title == named
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
            message = f"several kept sessions are `{named}`: " + ", ".join(
                called(each) for each in found
            )
    raise TranscriptError(message)


def indented(text: str, by: str = "    ") -> str:
    """Return `text` with each line indented `by`."""
    return "\n".join(f"{by}{line}" if line else "" for line in text.splitlines())


def answered(session: Transcript) -> str:
    """Return the operator's words in `session`, numbered, each after what the agent last said before it: what it answered."""
    heading = (
        f"{called(session)}, from {when(session.started())}, in "
        f"{session.directory or '?'}"
    )

    def part(number: int, said: Said) -> str:
        before = session.replied(said)
        answering = (
            "  (the session's first words)"
            if before is None
            else f"  answering the agent:\n{indented(before.text)}"
        )
        return f"[{number}] {when(said.at)}\n{answering}\n  you:\n{indented(said.text)}"

    parts = [part(at, said) for at, said in enumerate(session.operators(), start=1)]
    return "\n\n".join([heading, *parts]) + "\n"


def whole(session: Transcript) -> str:
    """Return everything said in `session`, in order, each run of tool calls folded to a line naming them."""
    heading = (
        f"{called(session)}, from {when(session.started())}, in "
        f"{session.directory or '?'}"
    )
    runs = groupby(session.entries, key=lambda each: isinstance(each, Called))
    parts = [
        folded([each.tool for each in run if isinstance(each, Called)])
        if calling
        else "\n\n".join(spoken(each) for each in run if isinstance(each, Said))
        for calling, run in runs
    ]
    return "\n\n".join([heading, *parts]) + "\n"


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


def found(sessions: list[Transcript], words: list[str]) -> str:
    """Return each time the operator said all of `words`, any case, newest session first: the session, when, their words, and the first line of what they answered."""
    wanted = [word.casefold() for word in words]

    def matched(said: Said) -> bool:
        text = said.text.casefold()
        return all(word in text for word in wanted)

    def hit(session: Transcript, said: Said) -> str:
        before = session.replied(said)
        answering = "" if before is None else first_line(before.text)
        return (
            f"{called(session)}, {when(said.at)}\n  answering: {answering}\n"
            f"  you:\n{indented(said.text)}"
        )

    hits = [
        hit(session, said)
        for session in sorted(sessions, key=begun, reverse=True)
        for said in session.operators()
        if matched(said)
    ]
    if not hits:
        return f"You never said {' '.join(words)!r} in a kept session.\n"
    return "\n\n".join(hits) + "\n"


def first_line(text: str) -> str:
    """Return a text's first line that isn't empty."""
    return next((line for line in text.splitlines() if line.strip()), "")
