"""The demo over a copy of the operator's dashboard state, on a stand-in host: every request the page may send answered by the host's own handler over the copy, with no program run, no socket reached, and nothing written outside the copy's directory, the operator's worktree and the host's state among it."""

import asyncio
import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from lup.blocks import OfAgent
from lup.programs import ProgramError, run
from lup.types import Model, MutableModel
from lup_dashboard.api import Asked, Replied
from lup_dashboard.copied import Asking, CopyHost, Withholding, asked_kinds, taken
from lup_dashboard.errors import CopyError
from lup_dashboard.layout import CopyLayout
from lup_dashboard.server import Access, OfCopy, application
from lup_dev.adapters.claude import ClaudeRecords, ClaudeTranscripts
from lup_dev.host.copying import Copy, Copying, RecordOf
from lup_dev.host.courier import Conversation as Talker
from lup_dev.host.courier import Conversations
from lup_dev.host.homes import kept
from lup_dev.host.names import Names
from lup_dev.host.protocol import (
    Holding,
    Limits,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Rename,
    Renamed,
    SetHolding,
)
from lup_dev.host.records import Recorded
from lup_dev.host.workers import Viewed, Viewing
from lup_dev.inbox import marks
from lup_dev.inbox.marks import MarksFile, MarksMoved, MoveMarks, Moving, ReviewMark
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AnswerItem,
    Context,
    Conversed,
    Drafted,
    Files,
    FinishItem,
    Items,
    KeepDraft,
    KeepOrder,
    KeepTalk,
    ListInbox,
    Ordered,
    Reviewed,
    SendDraft,
    SendItem,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    ShowItem,
    Shown,
    ShowOrder,
    ShowTalk,
    Talked,
)
from lup_dev.inbox.store import (
    KINDS,
    Answered,
    Approval,
    ChangedFile,
    Comment,
    Decided,
    Decision,
    Done,
    Draft,
    Flagged,
    HeldChange,
    Inbox,
    Letter,
    Message,
    Question,
    Ruling,
    Talk,
    TalkComment,
    Text,
    Whereabouts,
)
from lup_dev.layout import Layout
from lup_dev.policy.since import ReviewSince, ShowSince, ViewedFile
from lup_dev.policy.waits import LandingsWaiting, ShowLandings
from lup_dev.stored import write_model
from lup_ledger.environment.layout import LedgerLayout
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from lup_dev.inbox.store import Item

AT = datetime(2026, 10, 29, 12, tzinfo=UTC)
TOKEN = "copy"


class Reach(MutableModel):
    """What the copy reached outside itself while it's watched: each program run, socket reached, and write outside its directory."""

    watched: Path | None = None
    """The copy's directory while it's watched; none otherwise."""
    reached: list[str] = []


REACH = Reach()

STARTING = {
    "subprocess.Popen",
    "os.posix_spawn",
    "os.spawn",
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.system",
    "pty.spawn",
}
"""Each audit event a program's start raises."""

REACHING = {
    "socket.connect",
    "socket.bind",
    "socket.sendto",
    "socket.sendmsg",
    "socket.getaddrinfo",
}
"""Each audit event reaching a socket, or a name on the network."""

WRITING: dict[str, list[int]] = {
    **{
        event: [0]
        for event in [
            "os.mkdir",
            "os.rmdir",
            "os.remove",
            "os.chmod",
            "os.chown",
            "os.truncate",
            "os.utime",
            "shutil.rmtree",
        ]
    },
    **{
        event: [0, 1]
        for event in [
            "os.rename",
            "os.link",
            "os.symlink",
            "shutil.copyfile",
            "shutil.copytree",
            "shutil.move",
        ]
    },
}
"""Each audit event writing a path, with the positions of its arguments naming one."""

OPENED_TO_WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def outside(given: object, copy: Path) -> bool:
    """Say whether `given` names a path outside `copy`: not a descriptor, nor the null device, nor Python's own bytecode, written as a module is first imported."""
    if not isinstance(given, str | bytes | Path):
        return False
    path = os.path.abspath(os.fsdecode(given))  # noqa: PTH100
    return not (
        path in {str(copy), os.devnull}
        or path.startswith(f"{copy}{os.sep}")
        or "__pycache__" in Path(path).parts
    )


def audited(event: str, arguments: tuple[object, ...]) -> None:
    """Keep, and refuse, each program run, socket reached, and path written outside the copy's directory while it's watched."""
    copy = REACH.watched
    if copy is None:
        return
    match event:
        case _ if event in STARTING or event in REACHING:
            reached = f"{event}: {arguments!r}"
        case "open":
            [path, _, flags] = arguments
            written = isinstance(flags, int) and flags & OPENED_TO_WRITE
            reached = f"wrote {path}" if written and outside(path, copy) else None
        case "sqlite3.connect":
            [database, *_] = arguments
            outer = database != ":memory:" and outside(database, copy)
            reached = f"opened the database {database}" if outer else None
        case _ if event in WRITING:
            paths = [arguments[each] for each in WRITING[event]]
            named = [each for each in paths if outside(each, copy)]
            reached = f"{event}: {named!r}" if named else None
        case _:
            reached = None
    if reached is not None:
        REACH.reached = [*REACH.reached, reached]
        raise PermissionError(reached)


sys.addaudithook(audited)


class Host(Model):
    """The stand-in host: lup's state on it, the inbox's ledger open, the operator's worktree and the home a launch's records are kept in."""

    layout: Layout
    ledger: Ledger
    worktree: Path
    home: Path
    elsewhere: Path

    model_config = {"arbitrary_types_allowed": True}


class Standing(Model):
    """The items the stand-in host holds, by what each is."""

    question: int
    note: int
    theirs: int
    approval: int
    approved: int
    held: int
    held_too: int
    flag: int


class FromHost(Asking):
    """The host as the copy asks it, its answers the host's own handler's over the stand-in host, in this process."""

    handler: Copying
    launch: Register
    asked: list[RecordOf | None] = []

    @override
    def copied(self, record: RecordOf | None = None) -> Copy:
        self.asked.append(record)
        files = (
            self.handler.state()
            if record is None
            else self.handler.conversation(record)
        )
        return Copy(repository=self.launch.repository, files=files)


def line(**fields: object) -> str:
    return json.dumps({"timestamp": "2026-10-29T12:00:00.000Z", **fields})


def human(text: str) -> str:
    return line(
        type="user",
        origin={"kind": "human"},
        cwd="/w",
        message={"role": "user", "content": text},
    )


def agent(*blocks: dict[str, object], sidechain: bool = False) -> str:
    return line(
        type="assistant",
        isSidechain=sidechain,
        message={"role": "assistant", "content": list(blocks)},
    )


def recorded(home: Path, place: str, *lines: str) -> None:
    path = home / "projects" / "-w" / place
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{each}\n" for each in lines))


def registered(launch: str, worktree: Path, repository: Path, home: Path) -> Register:
    return Register(
        launch=launch,
        runtime="claude",
        worktree=worktree,
        repository=repository,
        judge=worktree / "judge",
        container=f"lup-{launch}",
        limits=Limits(actions=[], protected=[]),
        github=None,
        name=launch,
        home=home,
    )


def changed() -> list[ChangedFile]:
    return [
        ChangedFile(
            path=Path("a.py"), before=Text(text="x = 0\n"), after=Text(text="x = 1\n")
        )
    ]


REPOSITORY = Path("/work/lup.git")
OTHER = Path("/work/other.git")
MAIN = Conversation(repository=REPOSITORY, runtime="claude", session="s1")
PARSER = MAIN.model_copy(update={"agent": "a1"})
THEIRS = Conversation(repository=OTHER, runtime="claude", session="s9")


def held_by_host(tmp_path: Path) -> tuple[Host, Standing]:
    """The stand-in host's state: two repositories' launches and items, the operator's real worktree each item names, and the records of the launched sessions."""
    layout = Layout(
        state=tmp_path / "host" / "state",
        runtime=tmp_path / "host" / "run",
        data=tmp_path / "host" / "data",
        config=tmp_path / "host" / "config",
        cache=tmp_path / "host" / "cache",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "a.py").write_text("x = 1\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home = tmp_path / "home"
    ledger = Ledger.opened(LedgerLayout.of(layout), KINDS)
    inbox = Inbox.opened(ledger)
    for party, launch, where in [
        (MAIN, "one", worktree),
        (PARSER, "one", worktree),
        (THEIRS, "two", elsewhere),
    ]:
        inbox.placed(
            Whereabouts(
                conversation=party,
                launch=launch,
                worktree=where,
                since=AT,
                parent=MAIN if party == PARSER else None,
            )
        )

    def made(reason: object, sender: object, where: Path, **more: object) -> Item:
        return inbox.made(reason, sender, Operator(), where, AT, **more)  # pyright: ignore[reportArgumentType]

    question = made(
        Question(text="Which?", decisions=[Decision(text="A or B", lean="A")]),
        PARSER,
        worktree,
        call="toolu_q",
    )
    note = made(Message(kind="note", text="done"), MAIN, worktree)
    theirs = made(Message(kind="note", text="theirs"), THEIRS, elsewhere)
    approval = made(
        Approval(
            text="Approve?",
            summary="lup's host zone",
            repository=REPOSITORY,
            fingerprint="f1",
            pushed_by=MAIN,
        ),
        Operator(),
        worktree,
    )
    approved = made(
        Approval(text="Approve?", summary="theirs", repository=OTHER, fingerprint="f2"),
        Operator(),
        elsewhere,
    )
    held = made(
        HeldChange(text="Let it land?", summary="a.py", worktree=worktree, key="h1"),
        PARSER,
        worktree,
    )
    held_too = made(
        HeldChange(text="Let it land?", summary="a.py", worktree=worktree, key="h2"),
        PARSER,
        worktree,
    )
    flag = made(
        Flagged(
            text="wrote a.py",
            summary="a.py: flagged",
            worktree=worktree,
            path=Path("a.py"),
            branch="feat",
        ),
        PARSER,
        worktree,
    )
    for each in [approval, approved, held, held_too, flag]:
        inbox.attached(each.number, "diff --git a/a.py b/a.py", changed())
    # An earlier lup's marks, a file of the module's, which the copy converts onto
    # its ledger as the host would.
    write_model(
        layout.marks(REPOSITORY).module("core"),
        MarksFile(
            module="core",
            marks=[ReviewMark(key=marks.seen(MAIN), up_to=str(note.number), at=AT)],
        ),
    )
    layout.host.launches.mkdir(parents=True)
    for launch, worked, repository, sessions in [
        (
            "one",
            worktree,
            REPOSITORY,
            [("c1", "s1", None, None), ("c2", "s1", "a1", "c1")],
        ),
        ("two", elsewhere, OTHER, [("c9", "s9", None, None)]),
    ]:
        record = registered(launch, worked, repository, home)
        layout.host.record(launch).write_text(record.model_dump_json())
        known = [
            Talker(id=id_, session=session, agent=agent_, parent=parent, linked=True)
            for id_, session, agent_, parent in sessions
        ]
        conversations = Conversations(known=known, session=sessions[0][1])
        layout.host.conversations(launch).write_text(conversations.model_dump_json())
    Names(path=layout.host.names).keep("s1", "one")
    calling = agent(
        {"type": "tool_use", "id": "toolu_q", "name": "mcp__lup__ask", "input": {}},
        sidechain=True,
    )
    result = line(
        type="user",
        message={
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_q", "content": "x"}
            ],
        },
    )
    recorded(
        home,
        "s1.jsonl",
        human("Build the parser."),
        agent({"type": "text", "text": "On it."}),
    )
    recorded(home, "s1/subagents/agent-a1.jsonl", human("Parse."), calling, result)
    recorded(
        home, "s9.jsonl", human("Theirs."), agent({"type": "text", "text": "Done."})
    )
    for session in ["s1", "s9"]:
        kept(layout.host, "claude", session, home)
    standing = Standing(
        question=question.number,
        note=note.number,
        theirs=theirs.number,
        approval=approval.number,
        approved=approved.number,
        held=held.number,
        held_too=held_too.number,
        flag=flag.number,
    )
    host = Host(
        layout=layout, ledger=ledger, worktree=worktree, home=home, elsewhere=elsewhere
    )
    return host, standing


def asking(host: Host) -> FromHost:
    records = ClaudeRecords(
        directory=host.layout.state / "operator", host=host.layout.host
    )
    handler = Copying(
        layout=host.layout,
        ledger=host.ledger,
        recorded={"claude": Recorded(records=records, reader=ClaudeTranscripts())},
    )
    launch = registered("one", host.worktree, REPOSITORY, host.home)
    return FromHost(handler=handler, launch=launch)


def files(*roots: Path) -> dict[Path, bytes]:
    """Every file under `roots`, with what it holds; the index SQLite keeps of its write-ahead log apart, which the host's own read of its ledger, as it copies it, writes."""
    return {
        each: each.read_bytes()
        for root in roots
        for each in sorted(root.rglob("*"))
        if each.is_file() and not each.name.endswith("-shm")
    }


def checkout(tmp_path: Path) -> Path:
    """A checkout with no declaration of its own: lup's defaults answer its repository's views."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".git").touch()
    return root


def test_every_request_the_page_may_send_acts_on_the_copy_alone(tmp_path: Path) -> None:
    host, standing = held_by_host(tmp_path)
    from_host = asking(host)
    copy = CopyLayout(home=tmp_path / "copy")
    root = checkout(tmp_path)
    before = files(tmp_path / "host", host.worktree, host.elsewhere, host.home, root)
    sent: list[str] = []
    REACH.reached = []
    REACH.watched = copy.home
    try:
        copied = taken(
            copy,
            from_host,
            root,
            {"claude": ClaudeTranscripts()},
        )
        app = application(
            copied,
            Access(token=TOKEN, port=8766),
            None,
            demo=True,
            copied=OfCopy(defaults=copied.views.by_defaults()),
        )
        client = TestClient(app, base_url="http://127.0.0.1:8766")

        def ask[R](request: Asked, reply: type[R]) -> R:
            sent.append(request.kind)
            response = client.post(
                "/api/ask",
                json=request.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert response.status_code == 200, response.text
            answered = TypeAdapter[Replied](Replied).validate_python(response.json())
            assert isinstance(answered, reply), answered
            return answered

        listed = ask(ListLaunches(), Listed)
        assert [each.launch for each in listed.launches] == ["one", "two"]
        assert set(listed.looks) == {REPOSITORY, OTHER}
        assert [each.path for each in listed.talkers["one"]] == [
            "one",
            "one/subagent·a1",
        ]
        about = client.get(
            "/api/about", headers={"Authorization": f"Bearer {TOKEN}"}
        ).json()
        assert about["copied"] == {"defaults": [str(OTHER)]}
        renamed = ask(Rename(launch="one", name="renamed"), Renamed)
        assert renamed.launch.name == "renamed"
        holding = SetHolding(launch="one", session="s1", agent="a1", on=True)
        assert ask(holding, Holding).on
        waiting = ask(ListInbox(), Items)
        assert standing.theirs in [each.number for each in waiting.items]
        # The host's earlier marks file, converted onto the copy's ledger as the
        # host would convert it once this checkout is approved.
        assert [(each.conversation, each.item) for each in waiting.seen] == [
            (MAIN, standing.note)
        ]
        assert ask(ShowItem(number=standing.question), Shown).item.number == (
            standing.question
        )
        assert ask(ShowFiles(number=standing.approval), Files).files == changed()
        assert ask(ShowContext(number=standing.question), Context).entries
        conversed = ask(ShowConversation(runtime="claude", session="s1"), Conversed)
        assert conversed.total == 2
        # The agent works on, on the host: their record grows, and the copy reads what came.
        record = host.home / "projects" / "-w" / "s1.jsonl"
        more = agent({"type": "text", "text": "More."}).encode() + b"\n"
        before[record] = record.read_bytes() + more
        REACH.watched = None
        record.write_bytes(before[record])
        REACH.watched = copy.home
        grown = ask(ShowConversation(runtime="claude", session="s1"), Conversed)
        assert grown.total == 3
        assert ask(ShowDraft(), Drafted).draft == Draft()
        draft = Draft(
            comments=[
                Comment(item=standing.held_too, text="yes, but name it"),
                Comment(item=standing.flag, text="why?"),
            ],
            letters=[Letter(to=MAIN, text="carry on")],
            done=[standing.approved],
        )
        assert ask(KeepDraft(draft=draft), Drafted).draft == draft
        ask(ShowOrder(), Ordered)
        assert ask(KeepOrder(places=["one"]), Ordered).order.places == ["one"]
        talk = Talk(comments=[TalkComment(step=1, text="hm")])
        assert ask(ShowTalk(conversation=MAIN), Talked).talk == Talk()
        assert ask(KeepTalk(conversation=MAIN, talk=talk), Talked).talk == talk
        since = ask(ShowSince(conversation=PARSER), Refused)
        assert since.error == Withholding().why
        marking = ReviewSince(
            conversation=PARSER,
            branch="feat",
            files=[ViewedFile(path=Path("a.py"), version="0" * 40)],
        )
        assert ask(marking, Refused).error == Withholding().why
        assert ask(ShowLandings(), LandingsWaiting).waiting == []
        moving = MoveMarks(
            repository=REPOSITORY,
            module="core",
            marks=[Moving(key=marks.seen(MAIN), up_to=str(standing.flag))],
        )
        assert ask(moving, MarksMoved).marks[0].up_to == str(standing.flag)
        for repository, of in [
            (REPOSITORY, OfAgent(runtime="claude", session="s1", agent="a1")),
            (OTHER, OfAgent(runtime="claude", session="s9")),
        ]:
            viewing = Viewing(
                repository=repository,
                module="transcripts",
                view="conversation",
                argument=of.model_dump(mode="json"),
            )
            assert ask(viewing, Viewed).blocks.blocks
        rulings = [Ruling(decision=1, verdict="leaning")]
        ask(AnswerItem(number=standing.question, rulings=rulings), Shown)
        ask(FinishItem(number=standing.note), Shown)
        ask(SendItem(launch="one", text="hello", agent="a1"), Shown)
        approving = AnswerApproval(
            number=standing.approval, approved=True, comment="ok"
        )
        assert ask(approving, Settled).here
        holding_answered = AnswerApproval(number=standing.held, approved=False)
        assert ask(holding_answered, Settled).here
        reviewed = ask(SendDraft(), Reviewed)
        watched = asyncio.run(anext(aiter(copied.watch(ListInbox()))))
    finally:
        REACH.watched = None
    assert REACH.reached == []
    assert sorted(set(sent)) == sorted(asked_kinds())
    assert files(tmp_path / "host", host.worktree, host.elsewhere, host.home, root) == (
        before
    )
    assert [each.number for each in reviewed.approved] == [
        standing.approved,
        standing.held_too,
    ]
    withheld = copied.withheld
    assert withheld.settled == [standing.approval, standing.approved]
    assert [(each.change.key, each.approved) for each in withheld.holds] == [
        ("h1", False),
        ("h2", True),
    ]
    assert withheld.notices == []
    inbox = Inbox.opened(Ledger.opened(LedgerLayout.of(copy.lup), KINDS))
    assert isinstance(inbox.item(standing.question).state, Answered)
    assert isinstance(inbox.item(standing.note).state, Done)
    assert isinstance(inbox.item(standing.approval).state, Decided)
    assert isinstance(watched, Items)
    sent_to = {
        (each.recipient, type(each.reason).__name__)
        for each in inbox.items.values()
        if each.sender == Operator()
    }
    assert {(PARSER, "Message"), (MAIN, "Message"), (MAIN, "Review")} <= sent_to
    assert from_host.asked[:3] == [
        None,
        RecordOf(runtime="claude", session="s1", agent="a1"),
        RecordOf(runtime="claude", session="s1"),
    ]
    assert (
        RecordOf(runtime="claude", session="s1", held=len(before[record]) - len(more))
        in from_host.asked
    )


def test_the_watch_on_the_copy_catches_a_program_a_socket_and_a_write_outside_it(
    tmp_path: Path,
) -> None:
    inside = tmp_path / "copy"
    inside.mkdir()
    REACH.reached = []
    REACH.watched = inside
    try:
        (inside / "kept").write_text("the copy's own")
        with pytest.raises(PermissionError):
            (tmp_path / "worktree.py").write_text("x = 1\n")
        with pytest.raises(ProgramError):
            run("true")
        with (
            socket.socket(socket.AF_UNIX) as connecting,
            pytest.raises(PermissionError),
        ):
            connecting.connect(str(tmp_path / "messages.sock"))
    finally:
        REACH.watched = None
    assert len(REACH.reached) == 3
    REACH.reached = []


def test_a_file_the_checkout_doesnt_read_stops_the_copy_naming_it(
    tmp_path: Path,
) -> None:
    host, _ = held_by_host(tmp_path)
    host.layout.host.record("one").write_text(json.dumps({"launch": "one"}))
    copy = CopyLayout(home=tmp_path / "copy")

    with pytest.raises(CopyError, match=r"run/host/launches/one\.json, copied from"):
        taken(copy, asking(host), checkout(tmp_path), {})


def test_a_session_the_operator_ran_on_the_host_is_never_read_into_the_copy(
    tmp_path: Path,
) -> None:
    host, _ = held_by_host(tmp_path)
    operator = host.layout.state / "operator" / "projects" / "-w"
    operator.mkdir(parents=True)
    (operator / "s5.jsonl").write_text(human("mine") + "\n")
    copy = CopyLayout(home=tmp_path / "copy")
    copied: CopyHost = taken(
        copy, asking(host), checkout(tmp_path), {"claude": ClaudeTranscripts()}
    )

    answered = asyncio.run(copied.ask(ShowConversation(runtime="claude", session="s5")))

    assert isinstance(answered, Refused)
    assert "in no launch's home" in answered.error
    assert not (copy.records("claude") / "projects" / "-w" / "s5.jsonl").exists()
