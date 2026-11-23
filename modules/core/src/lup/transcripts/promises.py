"""Transcripts' promises: what an agent, or the operator, can count on of searching past sessions.

Each is checked through the harness, lup started on its default modules with
transcripts reading a rooms' home made for the promise, written as Claude Code
writes its records (`docs/field-notes.md`, *A session's record*), and none of
the machine's own.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

lazy from pydantic import JsonValue

import lup
from lup import Blocks, Modules, Operator, Part, Project
from lup.testing import Accepted, Started, Testing
from lup.transcripts import Searching, Showing

SESSION = "5f0b9a1e-3c2d-4e8f-9a7b-1c2d3e4f5a6b"
"""A session's id, as Claude Code names one."""


def line(**fields: JsonValue) -> bytes:
    """Return a line of a Claude Code session's record, its session and directory said."""
    return json.dumps({"sessionId": SESSION, "cwd": "/work", **fields}).encode() + b"\n"


def typed(text: str, uuid: str, at: str) -> bytes:
    """Return the line holding words the operator typed."""
    return line(
        type="user",
        uuid=uuid,
        timestamp=at,
        origin={"kind": "human"},
        message={"role": "user", "content": text},
    )


def answered(text: str, uuid: str, at: str) -> bytes:
    """Return the line holding the agent's words."""
    return line(
        type="assistant",
        uuid=uuid,
        timestamp=at,
        message={"role": "assistant", "content": [{"type": "text", "text": text}]},
    )


def ended(uuid: str, at: str) -> bytes:
    """Return the line ending the agent's turn."""
    return line(type="system", subtype="turn_duration", uuid=uuid, timestamp=at)


def recorded(homes: Path, *lines: bytes) -> Path:
    """Write a session's record holding `lines` in a project's rooms' home under `homes`, adding to it where it's there; return it."""
    folder = homes / "projects" / "digest" / "claude" / "projects" / "-work"
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / f"{SESSION}.jsonl"
    with record.open("ab") as written:
        written.write(b"".join(lines))
    return record


def project(homes: Path, ledger: Path | None = None) -> Project:
    """Return lup's default modules, transcripts reading the rooms' homes under `homes`, and `ledger` where given, and nothing of the machine's own."""
    return Project(
        modules=Modules.default().edit(
            lup.Transcripts(homes=homes, own=False, archive=None, ledger=ledger)
        )
    )


async def searched(started: Started, searching: Searching) -> str:
    """Search as the operator does, and return what the command prints."""
    found = await started.view("transcripts", "search", searching, Operator())
    assert isinstance(found, Accepted), found
    assert isinstance(found.output, Blocks)
    return found.output.text()


class TranscriptsPromises(Part):
    """What searching past sessions can count on."""

    @lup.promise
    async def the_operators_words_are_found_under_what_they_answered(
        self, by: Testing
    ) -> None:
        """Each time the operator typed words is found by a search for them, under the agent's last words before them, and the agent's words mid-turn aren't found unless asked for."""
        with tempfile.TemporaryDirectory() as made:
            homes = Path(made)
            recorded(
                homes,
                typed("start the port", "u1", "2026-11-19T10:00:00Z"),
                answered("thinking aloud mid-turn", "a1", "2026-11-19T10:00:05Z"),
                answered("I propose readers per runtime", "a2", "2026-11-19T10:00:10Z"),
                ended("e1", "2026-11-19T10:00:11Z"),
                typed("yes, readers per runtime", "u2", "2026-11-19T10:01:00Z"),
            )
            started = await by.started(machine=True, declared=project(homes))
            found = await searched(started, Searching(words=["readers"]))
            assert "yes, readers per runtime" in found
            assert "I propose readers per runtime" in found
            mid = await searched(started, Searching(words=["thinking"], by="agent"))
            assert "thinking aloud" not in mid
            proposed = await searched(started, Searching(words=["propose"], by="agent"))
            assert "I propose readers per runtime" in proposed

    @lup.promise
    async def a_record_that_grows_is_found_again(self, by: Testing) -> None:
        """A record that grew since a search is read again for what it added, so the next search finds it."""
        with tempfile.TemporaryDirectory() as made:
            homes = Path(made)
            recorded(homes, typed("first words", "u1", "2026-11-19T10:00:00Z"))
            started = await by.started(machine=True, declared=project(homes))
            assert "first words" in await searched(started, Searching(words=["first"]))
            assert "second words" not in await searched(
                started, Searching(words=["second"])
            )
            recorded(homes, typed("second words", "u2", "2026-11-19T10:05:00Z"))
            assert "second words" in await searched(
                started, Searching(words=["second"])
            )

    @lup.promise
    async def a_hit_opens_the_conversation_around_it(self, by: Testing) -> None:
        """A hit names the step it's at, and showing the conversation there gives what was said around it."""
        with tempfile.TemporaryDirectory() as made:
            homes = Path(made)
            recorded(
                homes,
                typed("before it", "u1", "2026-11-19T10:00:00Z"),
                answered("the proposal", "a1", "2026-11-19T10:00:10Z"),
                ended("e1", "2026-11-19T10:00:11Z"),
                typed("the hit itself", "u2", "2026-11-19T10:01:00Z"),
            )
            started = await by.started(machine=True, declared=project(homes))
            found = await started.view(
                "transcripts", "search", Searching(words=["hit"]), Operator()
            )
            assert isinstance(found, Accepted)
            assert isinstance(found.output, Blocks)
            steps = [
                span.refers.given
                for block in found.output.blocks
                for span in spans(block)
                if span.refers is not None and span.refers.view == "show"
            ]
            [given] = steps
            showing = Showing.model_validate(given)
            shown = await started.view("transcripts", "show", showing, Operator())
            assert isinstance(shown, Accepted)
            assert isinstance(shown.output, Blocks)
            text = shown.output.text()
            assert "before it" in text
            assert "the hit itself" in text

    @lup.promise
    async def the_operators_words_through_lup_are_found(self, by: Testing) -> None:
        """What the operator said through lup's inbox is found by a search for it, with the moment it was said."""
        with tempfile.TemporaryDirectory() as made:
            started = await by.started(machine=True, declared=project(Path(made)))
            piled = await started.run(
                "inbox", "pile", {"repository": "harness", "path": "ideas"}, Operator()
            )
            assert isinstance(piled, Accepted), piled
            told = await started.run(
                "inbox",
                "address",
                {
                    "repository": "harness",
                    "to": "ideas",
                    "text": "readers per runtime, said through the inbox",
                },
                Operator(),
            )
            assert isinstance(told, Accepted), told
            found = await searched(started, Searching(words=["readers", "inbox"]))
            assert "readers per runtime, said through the inbox" in found

    @lup.promise
    async def the_second_lups_ledger_is_searched(self, by: Testing) -> None:
        """A comment of the operator's in the second lup's ledger is found by a search, under the passage it quoted, once though its review reached several conversations."""
        with tempfile.TemporaryDirectory() as made:
            ledger = ledgered(Path(made) / "ledger.sqlite3", copies=1 + by.any(bool))
            started = await by.started(
                machine=True, declared=project(Path(made) / "homes", ledger=ledger)
            )
            found = await searched(started, Searching(words=["ledger"], whole=True))
            assert found.count("from the ledger, my answer") == 1
            assert "the passage quoted" in found


def spans(block: lup.Model) -> list[lup.Span]:
    """Return every span a block holds, its fold's summary and what's under it among them."""
    match block:
        case lup.Line(spans=held):
            return held
        case lup.Fold(summary=summary, content=list() as content):
            return [*summary, *(each for inner in content for each in spans(inner))]
        case lup.Fold(summary=summary):
            return summary
        case _:
            return []


def ledgered(path: Path, copies: int) -> Path:
    """Write a ledger of the second lup's at `path`: an agent's question, and the operator's review commenting on it, kept once for each of `copies` conversations it reached."""
    agent: JsonValue = {
        "party": "conversation",
        "repository": "/work",
        "runtime": "claude",
        "session": SESSION,
        "agent": None,
    }
    question: JsonValue = {
        "kind": "inbox:item",
        "number": 1,
        "repository": "/work",
        "by": agent,
        "recipient": {"party": "operator"},
        "made": "2026-10-20T10:00:00Z",
        "reason": {
            "reason": "question",
            "text": "the passage quoted, and more",
            "decisions": [],
        },
    }
    reviews: list[JsonValue] = [
        {
            "kind": "inbox:item",
            "number": 2 + each,
            "repository": "/work",
            "by": {"party": "operator"},
            "recipient": agent,
            "made": "2026-10-20T11:00:00Z",
            "reason": {
                "reason": "review",
                "comments": [
                    {
                        "item": 1,
                        "text": "from the ledger, my answer",
                        "quote": {"text": "the passage quoted"},
                    }
                ],
                "letters": [],
                "remarks": [],
            },
        }
        for each in range(copies)
    ]
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE nodes (number INTEGER PRIMARY KEY, version INTEGER, kind TEXT)"
        )
        database.execute(
            "CREATE TABLE versions (version INTEGER PRIMARY KEY, record TEXT)"
        )
        database.execute(
            "CREATE TABLE edges (drawn INTEGER PRIMARY KEY, kind TEXT, target INTEGER, record TEXT)"
        )
        for number, record in enumerate([question, *reviews], start=1):
            database.execute(
                "INSERT INTO versions VALUES (?, ?)", (number, json.dumps(record))
            )
            database.execute(
                "INSERT INTO nodes VALUES (?, ?, ?)", (number, number, "inbox:item")
            )
    return path
