"""A copy of what the operator's dashboard shows, for a room: the host's state files a copy holds, and nothing else of lup's state; a launched conversation's record, never the operator's own."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

from lup_dev.adapters.claude import ClaudeRecords, ClaudeTranscripts
from lup_dev.host.copying import Copy, Copying, RecordOf, ShowCopy
from lup_dev.host.courier import Conversations
from lup_dev.host.homes import kept
from lup_dev.host.names import Names
from lup_dev.host.protocol import HostError, Limits, Register
from lup_dev.host.records import Recorded
from lup_dev.inbox.marks import MarksFile, ReviewMark
from lup_dev.inbox.store import KINDS, Inbox, Message
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from lup_dev.layout import Layout

AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


def registered(tmp_path: Path, launch: str) -> Register:
    return Register(
        launch=launch,
        runtime="claude",
        worktree=tmp_path / "worktree",
        repository=tmp_path / "repo.git",
        judge=tmp_path / "judge",
        container=f"lup-{launch}",
        limits=Limits(actions=[], protected=[]),
        github=None,
        name=launch,
    )


def copied(answer: object) -> dict[tuple[str, str], bytes]:
    assert isinstance(answer, Copy)
    return {(each.under, str(each.place)): each.content() for each in answer.files}


def test_a_copy_holds_the_files_it_names_and_nothing_else_of_lups_state(
    state: Layout, tmp_path: Path
) -> None:
    ledger = Ledger.opened(LedgerLayout.of(state), KINDS)
    inbox = Inbox.opened(ledger)
    sender = Conversation(
        repository=tmp_path / "other.git", runtime="claude", session="s1"
    )
    inbox.made(Message(kind="note", text="done"), sender, Operator(), None, AT)
    digest = ledger.attached(b"a diff")
    attachments = LedgerLayout.of(state).attachments
    (attachments / f"{digest}.partial").write_bytes(b"half")
    write_model(
        state.marks(tmp_path / "repo.git").module("core"),
        MarksFile(
            module="core", marks=[ReviewMark(key={"session": "s1"}, up_to="3", at=AT)]
        ),
    )
    launch = registered(tmp_path, "one")
    state.host.launches.mkdir(parents=True)
    state.host.record("one").write_text(launch.model_dump_json())
    state.host.conversations("one").write_text(Conversations().model_dump_json())
    sockets = state.host.launch("one").directory
    sockets.mkdir()
    (sockets / "hook.sock").write_text("a room's own")
    Names(path=state.host.names).keep("s1", "parser")
    state.session_index.mkdir(parents=True)
    state.session("s1").write_text("{}")
    state.conversations("s1").write_text("{}")
    # What a copy never holds: the dashboard's token, what the judge keeps of a
    # repository, a session's home, the log, the data's logins and the
    # values lup keeps unpublished.
    state.host.dashboard_token.write_text("token")
    state.approved(tmp_path / "repo.git").write_text("{}")
    state.verdicts(tmp_path / "repo.git").write_text("")
    state.host.log.write_text("said")
    home = state.host.home_of("claude", "s1")
    home.parent.mkdir(parents=True)
    home.write_text(str(tmp_path / "home"))
    login = state.accounts.account("me").runtime("claude") / ".credentials.json"
    login.parent.mkdir(parents=True)
    login.write_text("secret")
    (state.data / "private").mkdir(parents=True)
    (state.data / "private" / "values.json").write_text("secret")
    (state.state / "told").mkdir()
    (state.state / "told" / "said").write_text("")
    (state.state / "later.json").write_text("a file a later lup keeps")
    handler = Copying(layout=state, ledger=ledger, recorded={})

    answer = asyncio.run(handler.answer(ShowCopy(), launch))

    found = copied(answer)
    marks = state.marks(tmp_path / "repo.git").module("core").relative_to(state.state)
    assert sorted(found) == sorted(
        [
            ("state", "ledger/ledger.sqlite3"),
            ("state", f"ledger/attachments/{digest}"),
            ("state", str(marks)),
            ("state", "host/session-names.json"),
            ("state", "session-index/s1.json"),
            ("state", "session-index/s1.conversations.json"),
            ("runtime", "host/launches/one.json"),
            ("runtime", "host/launches/one.conversations.json"),
        ]
    )
    assert isinstance(answer, Copy)
    assert answer.repository == tmp_path / "repo.git"
    assert found["state", f"ledger/attachments/{digest}"] == b"a diff"
    database = tmp_path / "copy" / "ledger.sqlite3"
    database.parent.mkdir()
    database.write_bytes(found["state", "ledger/ledger.sqlite3"])
    again = Inbox.opened(Ledger.opened(LedgerLayout(home=database.parent), KINDS))
    assert [each.reason for each in again.items.values()] == [
        Message(kind="note", text="done")
    ]


def test_a_launched_conversations_record_is_copied_from_its_home_alone(
    state: Layout, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    folder = home / "projects" / "-w"
    (folder / "s1" / "subagents").mkdir(parents=True)
    (folder / "s1.jsonl").write_text(json.dumps({"type": "user"}) + "\n")
    (folder / "s1" / "subagents" / "agent-a1.jsonl").write_text("{}\n")
    kept(state.host, "claude", "s1", home)
    operators = tmp_path / "operator" / "projects" / "-w"
    operators.mkdir(parents=True)
    (operators / "s2.jsonl").write_text("{}\n")
    records = ClaudeRecords(directory=tmp_path / "operator", host=state.host)
    handler = Copying(
        layout=state,
        ledger=Ledger.opened(LedgerLayout.of(state), KINDS),
        recorded={"claude": Recorded(records=records, reader=ClaudeTranscripts())},
    )
    launch = registered(tmp_path, "one")

    def asked(
        session: str, agent: str | None = None, runtime: str = "claude", held: int = 0
    ) -> Copy:
        record = RecordOf(runtime=runtime, session=session, agent=agent, held=held)
        answer = asyncio.run(handler.answer(ShowCopy(record=record), launch))
        assert isinstance(answer, Copy)
        return answer

    [own] = asked("s1").files
    assert (own.under, own.place) == ("home", PurePosixPath("projects/-w/s1.jsonl"))
    assert own.content() == (folder / "s1.jsonl").read_bytes()
    grown = (folder / "s1.jsonl").read_bytes() + b"{}\n"
    (folder / "s1.jsonl").write_bytes(grown)
    [tail] = asked("s1", held=len(own.content())).files
    assert (tail.start, tail.content()) == (len(own.content()), b"{}\n")
    [whole] = asked("s1", held=len(grown) + 1).files
    assert (whole.start, whole.content()) == (0, grown)
    [subagent] = asked("s1", "a1").files
    assert subagent.place == PurePosixPath("projects/-w/s1/subagents/agent-a1.jsonl")
    with pytest.raises(HostError, match="in no launch's home"):
        asked("s2")
    with pytest.raises(HostError, match="isn't on this machine"):
        asked("s1", "a2")
    with pytest.raises(HostError, match="doesn't read the records of"):
        asked("s1", runtime="other")
