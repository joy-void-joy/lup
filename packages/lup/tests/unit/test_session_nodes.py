"""Sessions and outputs are indexed in the ledger as pointers at notes/, never as bytes.

Written against the writers rather than the types: a session directory
opened and a factory closed record and then amend one node with the journal
pinned at close; a result written records an output about its session; a
writer handed no recorder records nothing and works; a ledger that refuses
is logged and the writer goes on; and the console refuses bytes on either
kind before anything reaches the blob store.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel
from rich.text import Text
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
import lup.sessions.capabilities as capabilities
from lup.channels.models import utc_now
from lup.coordination.refs import ActorRef
from lup.devtools.harness import launch
from lup.ledger.files import digest_of
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, Surroundings
from lup.ledger.tools import NoInput, RecordInput, create_ledger_tools
from lup.observability.sessions import (
    Output,
    Session,
    SessionRecorder,
    recorded_session_factory,
    session_recorder,
)
from lup.providers.claude.transcripts import ClaudeTranscripts
from lup.sessions.client import Client
from lup.sessions.events import SessionHandle, SessionId, TurnHandle, TurnRequest
from lup.tools.mcp import ToolError
from lup.workspace.history import save_session
from lup.workspace.notes import setup_notes

AUTHOR = ActorRef(kind="test", id="t")


class About(LedgerEdge, frozen=True):
    """The descriptive edge a project draws from an output to its session."""

    kind: Literal["test:about"] = "test:about"


class Result(BaseModel):
    summary: str


class IdleSession(capabilities.Session):
    """A session nothing starts a turn on: the factory around it is the subject."""

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        raise NotImplementedError(f"no turn is started here: {request}")


def idle_factory() -> Client:
    @asynccontextmanager
    async def open_session(
        resume: SessionId | None = None,
    ) -> AsyncGenerator[SessionHandle]:
        del resume
        yield SessionHandle(session=IdleSession())

    return Client(open_session)


def recorder_at(root: Path) -> SessionRecorder:
    return SessionRecorder(LedgerStore(root, AUTHOR), about=About)


async def test_opening_and_closing_a_session_records_then_amends_one_node(
    tmp_lup_project: Path,
) -> None:
    store = LedgerStore(tmp_lup_project, AUTHOR)
    recorder = recorder_at(tmp_lup_project)

    notes = setup_notes("s1", "t1", recorder=recorder, runtime="fake")

    assert notes.record is not None and notes.session.is_dir()
    [opened] = store.read(Session)
    assert opened.id == notes.record.id and opened.title == "s1"
    assert opened.directory == "notes/traces/1.2.3/sessions/s1"
    assert opened.journal == notes.trace_log.relative_to(tmp_lup_project).as_posix()
    assert opened.checkout == str(tmp_lup_project)
    assert opened.runtime == "fake" and opened.agent_version == "1.2.3"
    assert opened.ended is None and opened.outcome == ""
    assert store.standing(opened).label == "open"

    factory = recorded_session_factory(idle_factory(), recorder, notes.record)
    async with factory.open():
        notes.trace_log.write_text("# Trace\n", encoding="utf-8")

    [closed] = store.read(Session)
    assert closed.id == opened.id and closed.ended is not None
    assert closed.outcome == "completed" and closed.finished()
    assert closed.journal_digest == digest_of(notes.trace_log)
    # One record and one amendment: nothing was rewritten, the log grew.
    assert len(store.lines()) == 2


async def test_standing_reads_open_then_fresh_stale_and_missing(
    tmp_lup_project: Path,
) -> None:
    store = LedgerStore(tmp_lup_project, AUTHOR)
    recorder = recorder_at(tmp_lup_project)
    notes = setup_notes("s1", recorder=recorder, runtime="fake")
    assert notes.record is not None
    assert store.standing(notes.record).label == "open"

    async with recorded_session_factory(idle_factory(), recorder, notes.record).open():
        notes.trace_log.write_text("one\n", encoding="utf-8")

    [closed] = store.read(Session)
    assert store.standing(closed).label == "fresh"
    with notes.trace_log.open("a", encoding="utf-8") as journal:
        journal.write("two\n")
    grown = store.standing(closed)
    assert grown.label == "stale" and not grown.sound and closed.journal in grown.reason
    notes.trace_log.unlink()
    assert store.standing(closed).label == "missing"
    assert closed.standing(Surroundings()).label == "unchecked"


async def test_a_session_that_raises_closes_as_failed_or_interrupted(
    tmp_lup_project: Path,
) -> None:
    store = LedgerStore(tmp_lup_project, AUTHOR)
    recorder = recorder_at(tmp_lup_project)
    notes = setup_notes("s1", recorder=recorder, runtime="fake")
    assert notes.record is not None
    factory = recorded_session_factory(idle_factory(), recorder, notes.record)

    with pytest.raises(RuntimeError):
        async with factory.open():
            raise RuntimeError("the provider fell over")
    assert store.read(Session)[0].outcome == "failed"

    with pytest.raises(asyncio.CancelledError):
        async with factory.open():
            raise asyncio.CancelledError()
    assert store.read(Session)[0].outcome == "interrupted"


def test_an_output_records_a_node_pointing_at_its_session(
    tmp_lup_project: Path,
) -> None:
    store = LedgerStore(tmp_lup_project, AUTHOR)
    recorder = recorder_at(tmp_lup_project)
    notes = setup_notes("s1", recorder=recorder, runtime="fake")
    assert notes.record is not None

    written = save_session(
        Result(summary="done"), session_id="s1", recorder=recorder, session=notes.record
    )

    [output] = store.read(Output)
    assert output.path == written.relative_to(tmp_lup_project).as_posix()
    assert output.title == output.path and output.checkout == str(tmp_lup_project)
    assert output.session == notes.record.id and output.digest == digest_of(written)
    assert store.standing(output).label == "fresh"
    [edge] = store.edges()
    assert (edge.kind, edge.source, edge.target) == (
        "test:about",
        output.id,
        notes.record.id,
    )
    written.write_text("{}", encoding="utf-8")
    assert store.standing(output).label == "stale"
    written.unlink()
    assert store.standing(output).label == "missing"


def test_a_writer_with_no_recorder_records_nothing_and_still_works(
    tmp_lup_project: Path,
) -> None:
    notes = setup_notes("s2", "t2")
    written = save_session(Result(summary="quiet"), session_id="s2")

    assert notes.record is None and notes.session.is_dir() and written.is_file()
    assert not (tmp_lup_project / "lup").exists()


def test_a_refusing_store_is_logged_and_the_writer_goes_on(
    tmp_lup_project: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The ledger's root cannot be made: a file sits where its directory goes.
    (tmp_lup_project / "lup").write_text("not a directory", encoding="utf-8")
    store = LedgerStore(tmp_lup_project, AUTHOR)
    recorder = recorder_at(tmp_lup_project)

    with caplog.at_level(logging.ERROR):
        notes = setup_notes("s3", recorder=recorder, runtime="fake")
        written = save_session(
            Result(summary="still written"), session_id="s3", recorder=recorder
        )
        standing = Session.model_validate(
            {
                "id": "abc",
                "author": AUTHOR.model_dump(),
                "at": utc_now(),
                "runtime": "fake",
                "started": utc_now(),
                "directory": "notes/traces/1.2.3/sessions/s3",
                "checkout": str(tmp_lup_project),
            }
        )
        assert standing.title == "s3"
        assert recorder.closed(standing, "completed") is None

    assert notes.record is None and notes.session.is_dir() and written.is_file()
    assert store.lines() == []
    assert caplog.text.count("the ledger refused") == 3


def test_a_recorder_exists_only_where_both_kinds_are_declared(
    tmp_lup_project: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        assert session_recorder(tmp_lup_project, AUTHOR, [Session]) is None
    assert "observability:output" in caplog.text
    found = session_recorder(tmp_lup_project, AUTHOR, [Session, Output], about=About)
    assert found is not None and found.about is About


@pytest.fixture
def launched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root a harness launch would record its transcript under."""
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        launch, "harness_runs_path", lambda: tmp_path / "notes" / "harness"
    )
    monkeypatch.setattr(launch, "agent_version", lambda: "1.2.3")
    return tmp_path


def transcript_at(root: Path, recorder: SessionRecorder) -> launch.HarnessTranscript:
    return launch.start_harness_transcript(
        "claude",
        ClaudeTranscripts(root / "config"),
        model=None,
        profile=None,
        arguments=[],
        transcribe=False,
        recorder=recorder,
    )


def test_a_harness_launch_records_its_transcript_directory(launched: Path) -> None:
    store = LedgerStore(launched, AUTHOR)
    transcript = transcript_at(launched, SessionRecorder(store))

    [opened] = store.read(Session)
    assert opened.runtime == "claude" and opened.agent_version == "1.2.3"
    assert opened.directory.startswith("notes/harness/claude/")
    assert opened.journal == f"{opened.directory}/observable.jsonl"
    assert opened.title == Path(opened.directory).name
    assert store.standing(opened).label == "open"

    transcript.close(succeeded=True)

    [closed] = store.read(Session)
    assert closed.outcome == "completed"
    assert closed.journal_digest == digest_of(launched / closed.journal)
    assert store.standing(closed).label == "fresh"


def test_a_launch_that_failed_or_was_interrupted_says_so(launched: Path) -> None:
    store = LedgerStore(launched, AUTHOR)
    transcript_at(launched, SessionRecorder(store)).close(succeeded=False)
    transcript_at(launched, SessionRecorder(store)).close(
        succeeded=False, interrupted=True
    )

    assert [each.outcome for each in store.read(Session)] == ["failed", "interrupted"]


def session_fields(root: Path) -> str:
    return json.dumps(
        {
            "runtime": "claude",
            "started": "2026-09-10T12:00:00+00:00",
            "directory": "notes/traces/1.2.3/sessions/s1",
            "checkout": str(root),
        }
    )


def output_fields(root: Path) -> str:
    return json.dumps(
        {
            "path": "notes/traces/1.2.3/sessions/s1/20260910_120000.json",
            "checkout": str(root),
            "produced": "2026-09-10T12:00:00+00:00",
        }
    )


def unwrapped(panel: str) -> str:
    """The console's error panel read as one line: its words, without the box's edges.

    The console wraps a refusal mid-sentence inside a drawn box, so the
    sentence is read back as words rather than matched against the drawing.
    Where the terminal colours the box, its edges arrive wrapped in escape
    codes, so the panel is read through Rich's own parser first.
    """
    plain = Text.from_ansi(panel).plain
    return " ".join(word for word in plain.split() if word != "│")


def test_the_console_refuses_bytes_on_either_kind_before_they_are_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    trace = tmp_path / "trace.md"
    trace.write_text("hundreds of megabytes, in spirit", encoding="utf-8")
    app = ledger_app.create_ledger_app([Session, Output])
    runner = CliRunner()

    session = runner.invoke(
        app,
        ["record", "observability:session", "", "--json", session_fields(tmp_path)]
        + ["--attach", str(trace)],
    )
    output = runner.invoke(
        app,
        ["record", "observability:output", "", "--json", output_fields(tmp_path)]
        + ["--attach", str(trace)],
    )
    types = runner.invoke(app, ["types"])

    assert session.exit_code != 0 and "pointers only" in unwrapped(session.output)
    assert output.exit_code != 0 and "pointers only" in unwrapped(output.output)
    assert "observability:session" in types.output
    assert "observability:output" in types.output
    # Nothing reached the log or the blob store: the refusal came first.
    assert LedgerStore(tmp_path, AUTHOR).lines() == []
    assert not (tmp_path / "lup" / "ledger" / "blobs").exists()


async def test_the_session_tools_refuse_bytes_the_same_way(tmp_path: Path) -> None:
    (tmp_path / "trace.md").write_text("bytes", encoding="utf-8")
    served = {
        tool.name: tool
        for tool in create_ledger_tools(tmp_path, AUTHOR, [Session, Output], [])
    }

    listed = await served["ledger_types"](NoInput())
    assert [kind.kind for kind in listed.nodes] == [
        "observability:session",
        "observability:output",
    ]
    with pytest.raises(ToolError, match="pointers only"):
        await served["ledger_record"](
            RecordInput(
                kind="observability:session",
                title="",
                fields=json.loads(session_fields(tmp_path)),
                attach=["trace.md"],
            )
        )
    assert not (tmp_path / "lup" / "ledger" / "blobs").exists()
