"""Sessions held with no terminal, as the host service starts and reaches their launchers: real short-lived programs stand in for a launcher, and a socket served in-process for its own."""

import asyncio
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.programs import Apart, detached
from lup_dev import cli
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient, Outstanding, own_command
from lup_dev.host.held import (
    CalledUp,
    CallingUp,
    End,
    Ending,
    HeldLaunch,
    HeldUp,
    Interrupt,
    Interrupting,
    Launchers,
    Spawn,
    Spawning,
    launcher_command,
)
from lup_dev.host.holders import HeldEnd, HeldInterrupt, Holders
from lup_dev.host.protocol import (
    Activity,
    Done,
    HostError,
    Limits,
    Listed,
    Refused,
    Register,
    Reply,
    Request,
    Talker,
)
from lup_dev.host.service import Dispatcher, Route, unix_server
from lup_dev.host.watch import Changes
from lup_dev.inbox.protocol import (
    FileReport,
    FinishItem,
    Items,
    ListItems,
    SendItem,
    Shown,
)
from lup_dev.inbox.store import Item, Message
from lup_dev.inbox.texts import written
from lup_dev.launch.trial import TerminalRun, Trial, scratch_worktree, taking_over
from lup_dev.layout import HostLayout, Layout
from lup_ledger.parties import Conversation, Operator, Party

if TYPE_CHECKING:
    from conftest import FakeClock, Shell


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(
        state=tmp_path / "state",
        runtime=tmp_path / "run",
        cache=tmp_path / "cache",
        data=tmp_path / "data",
        config=tmp_path / "config",
    )


async def yielded(seconds: float) -> None:
    """Let the loop run what waits, and no time pass."""
    del seconds
    await asyncio.sleep(0)


def asking(worktree: Path) -> Spawn:
    return Spawn(runtime="claude", worktree=worktree, arguments=["--model", "haiku"])


def test_a_spawn_starts_its_launcher_and_answers_once_it_calls_its_session_up(
    layout: Layout, tmp_path: Path
) -> None:
    started: list[HeldLaunch] = []
    launchers = Launchers()
    loops: list[asyncio.AbstractEventLoop] = []

    def start(spec: HeldLaunch, log: Path) -> Apart:
        """Start a program that waits, and have the launch called up, as its launcher would once its session's first hook was heard."""
        started.append(spec)
        calling = CallingUp(launchers=launchers).answer(
            CalledUp(launch=spec.launch, name="dev", session="s-1")
        )
        asyncio.run_coroutine_threadsafe(calling, loops[0])
        return detached("sleep", "60", log=log)

    spawning = Spawning(layout=layout, launchers=launchers, start=start, pause=yielded)

    async def spawned() -> HeldUp | Refused:
        loops.append(asyncio.get_running_loop())
        answer = await spawning.answer(asking(tmp_path))
        assert isinstance(answer, HeldUp | Refused)
        return answer

    answer = asyncio.run(spawned())

    [spec] = started
    assert answer == HeldUp(
        launch=spec.launch,
        name="dev",
        session="s-1",
        log=layout.launch(spec.launch).log,
    )
    assert spec == HeldLaunch(
        launch=spec.launch,
        runtime="claude",
        worktree=tmp_path,
        arguments=["--model", "haiku"],
    )
    assert launchers.waiting == {}
    [launcher] = launchers.started
    launcher.process.kill()
    launcher.process.wait()
    launchers.reaped()
    assert launchers.started == []


def test_a_spawn_whose_launcher_ends_first_is_refused_with_what_it_wrote(
    layout: Layout, tmp_path: Path
) -> None:
    def start(spec: HeldLaunch, log: Path) -> Apart:
        return detached(
            "sh", "-c", f"echo 'the room never started: {spec.launch}'", log=log
        )

    spawning = Spawning(
        layout=layout, launchers=Launchers(), start=start, pause=yielded
    )

    answer = asyncio.run(spawning.answer(asking(tmp_path)))

    assert isinstance(answer, Refused)
    assert "ended before its session was up" in answer.error
    assert "\nthe room never started: " in answer.error


def test_a_launcher_is_started_from_its_worktree_with_nothing_there_on_its_path(
    layout: Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launcher starts in its worktree, which a room writes: a module planted there is never what it imports."""
    started: list[list[str]] = []
    places: list[Path | None] = []

    def recorded(
        program: str, *arguments: str, log: Path, cwd: Path | None = None
    ) -> Apart:
        started.append([program, *arguments])
        places.append(cwd)
        return detached("true", log=log)

    monkeypatch.setattr(cli, "detached", recorded)
    [spawning, *_] = cli.held_routes(layout, Holders(layout=layout), Launchers())
    spec = HeldLaunch(launch="a1", runtime="claude", worktree=tmp_path)

    asyncio.run(
        spawning.answer(Spawn(runtime="claude", worktree=tmp_path).model_dump_json())
    )

    [command] = started
    assert command[:5] == [sys.executable, "-P", "-m", "lup_dev.cli", "spawn"]
    assert HeldLaunch.model_validate_json(command[-1]).worktree == spec.worktree
    assert places == [tmp_path]


def test_a_launcher_is_started_as_the_hidden_command_given_its_launch() -> None:
    spec = HeldLaunch(launch="a1", runtime="claude", worktree=Path("/w"))

    command = launcher_command(["python", "-m", "lup_dev.cli"], spec)

    assert command[:5] == ["python", "-m", "lup_dev.cli", "spawn", "launcher"]
    assert HeldLaunch.model_validate_json(command[-1]) == spec


def held(launch: str, *, holding: bool = True) -> Register:
    return Register(
        launch=launch,
        runtime="claude",
        worktree=Path("/w"),
        repository=Path("/w/.git"),
        judge=Path("/judge"),
        limits=Limits(actions=[], protected=[]),
        github=None,
        held=holding,
    )


def test_an_interrupt_and_an_end_reach_a_held_launch_s_launcher(
    layout: Layout,
) -> None:
    holders = Holders(layout=layout)
    holders.opened(held("h1"))
    holders.opened(held("t1", holding=False))
    heard: list[str] = []

    async def reached() -> list[object]:
        async def connection(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            heard.append((await reader.read()).decode())
            writer.write(Done().model_dump_json().encode())
            await writer.drain()
            writer.close()

        socket = layout.launch("h1").held
        socket.parent.mkdir(parents=True)
        server = await unix_server(socket, connection)
        try:
            answers: list[object] = [
                await Interrupting(holders=holders).answer(Interrupt(launch="h1")),
                await Ending(holders=holders).answer(End(launch="h1")),
            ]
        finally:
            server.close()
        for launch in ["t1", "gone"]:
            try:
                await Interrupting(holders=holders).answer(Interrupt(launch=launch))
            except HostError as refused:
                answers.append(str(refused))
        return answers

    answers = asyncio.run(reached())

    assert answers == [
        Done(),
        Done(),
        "launch `t1` isn't a held session: its terminal is its own",
        "launch `gone` isn't a held session: its terminal is its own",
    ]
    assert heard == [
        HeldInterrupt().model_dump_json(),
        HeldEnd().model_dump_json(),
    ]
    holders.closed("h1")
    assert not holders.holds("h1")


def test_a_launcher_that_s_gone_is_said_where_it_was_looked_for(
    layout: Layout,
) -> None:
    holders = Holders(layout=layout)
    holders.opened(held("h1"))

    with pytest.raises(HostError, match=r"launch `h1`'s launcher.*h1\.sock"):
        asyncio.run(holders.asked("h1", HeldInterrupt()))


def test_a_launcher_s_requests_are_answered_on_its_socket_as_the_service_s_are(
    layout: Layout,
) -> None:
    """The launcher serves its socket with the service's own dispatcher: an unknown kind is refused, naming what it answers."""
    dispatcher = Dispatcher(
        routes={},
        answering="launch h1's launcher",
        say=lambda _: None,
        changes=Changes(),
    )

    answer = asyncio.run(dispatcher.answered(HeldEnd().model_dump_json()))

    assert answer == Refused(
        error="no handler for `held-end`; launch h1's launcher answers no kind"
    )
    assert Route.to(Ending(holders=Holders(layout=layout))).kind == "end"


# The operator's one command, against a host that answers as a held session would


WORDS = {
    "single word PAPAYA": "PAPAYA",
    "single word PEAR": "PEAR",
    "single word MANGO": "MANGO",
    "first ask you": "PAPAYA",
    "List, in order": "PAPAYA PEAR MANGO KIWI",
}
"""What the stand-in session answers to each of the trial's questions, by a passage of it."""


class Played(HostClient):
    """The host service as the trial meets it, one held launch at a time, its session answering each question, with no service behind."""

    log: Path
    conversation: Conversation
    served: list[Register] = []
    items: list[Item] = []
    asked: list[Request] = []
    calling: list[bool] = []
    restarts: list[int] = []
    words: dict[str, str] = WORDS
    """What the session answers, by a passage of the question."""

    def item(self, sender: Party, recipient: Party, text: str) -> Item:
        made = Item(
            number=len(self.items) + 1,
            reason=Message(kind="note", text=text, ending=sender != Operator()),
            sender=sender,
            recipient=recipient,
            made=datetime(2026, 11, 8, tzinfo=UTC),
        )
        self.items.append(made)
        return made

    @override
    def ensure(self) -> None:
        self.restarts.append(len(self.restarts))

    @override
    def stop(self) -> bool:
        return True

    @override
    def launches(self) -> list[Register]:
        return self.served

    @override
    def listed(self) -> Listed:
        talkers = [
            Talker(
                path="t",
                own="t",
                session=self.conversation.session,
                activity=Activity(
                    state="calling", since=datetime(2026, 11, 8, tzinfo=UTC)
                )
                if self.calling
                else None,
            )
        ]
        return Listed(
            launches=self.served, talkers={each.launch: talkers for each in self.served}
        )

    @override
    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        self.asked.append(request)
        match request:
            case SendItem(text=text):
                sent = self.item(Operator(), self.conversation, text)
                answer = next(
                    (word for cue, word in self.words.items() if cue in text), None
                )
                if "time.sleep" in text:
                    self.calling.append(True)
                elif answer is not None:
                    self.item(self.conversation, Operator(), answer)
                return reply.model_validate(Shown(item=sent).model_dump())
            case ListItems():
                return reply.model_validate(Items(items=self.items).model_dump())
            case Interrupt():
                self.log.write_text(
                    "Session: A turn ended: error_during_execution, aborted_tools, an error.\n"
                )
                return reply.model_validate(Done().model_dump())
            case FileReport(sender=sender, text=text):
                filed = self.item(sender, Operator(), text)
                return reply.model_validate(Shown(item=filed).model_dump())
            case FinishItem(number=number):
                return reply.model_validate(
                    Shown(item=self.items[number - 1]).model_dump()
                )
            case _:
                return reply.model_validate(Done().model_dump())

    @override
    def held(self, request: Request) -> Outstanding:
        self.asked.append(request)
        if isinstance(request, End):
            self.served[:] = [
                each for each in self.served if each.launch != request.launch
            ]
        mine, theirs = socket.socketpair()
        theirs.sendall(Done().model_dump_json().encode())
        theirs.close()
        return Outstanding(connection=mine)


def played(tmp_path: Path, clock: FakeClock) -> tuple[Played, Trial]:
    conversation = Conversation(
        repository=tmp_path / ".git", runtime="claude", session="s-1"
    )
    host = Played(
        layout=HostLayout(sockets=tmp_path / "run", state=tmp_path / "state"),
        clock=clock,
        starter=Detached(),
        log=tmp_path / "h1.log",
        conversation=conversation,
    )
    host.log.write_text("")

    def spawn(worktree: Path, resume: str | None) -> HeldUp:
        launch = f"h{len([each for each in host.asked if isinstance(each, End)]) + 1}"
        host.served[:] = [
            held(launch).model_copy(update={"container": "lup-trial", "name": "trial"})
        ]
        return HeldUp(launch=launch, name="trial", session="s-1", log=host.log)

    def terminal(worktree: Path, session: str) -> TerminalRun:
        host.served.clear()
        host.item(conversation, Operator(), "KIWI")
        return TerminalRun(
            status=0,
            output="Launch `trial` ended; its session is taken over here.\nKIWI\n",
        )

    trial = Trial(
        host=host,
        spawn=spawn,
        terminal=terminal,
        running=lambda container: bool(host.served),
        clock=clock,
        say=lambda _: None,
        worktree=tmp_path / "spawn-trial-1",
    )
    return host, trial


def test_the_trial_tries_each_step_and_files_what_it_saw_under_the_session(
    tmp_path: Path, clock: FakeClock
) -> None:
    host, trial = played(tmp_path, clock)

    steps = trial.run()
    number = trial.filed(tmp_path / ".git", "claude")

    assert [(each.name, each.passed) for each in steps] == [
        ("held", True),
        ("answers", True),
        ("interrupts", True),
        ("survives a restart", True),
        ("ends", True),
        ("resumes held", True),
        ("a terminal takes it over", True),
        ("back to held", True),
    ], [each.seen for each in steps]
    report = written(host.items[number - 1])
    assert report.startswith(
        f"**Spawn's trial**, `lup-dev spawn trial`, in {tmp_path / 'spawn-trial-1'}: "
        "8 of 8 steps passed."
    )
    assert "**What it means:** a session lup holds with no terminal works" in report
    assert host.items[number - 1].sender == host.conversation
    finished = [each.number for each in host.asked if isinstance(each, FinishItem)]
    assert finished == [
        each.number
        for each in host.items[: number - 1]
        if each.recipient == Operator() and each.sender == host.conversation
    ]
    assert host.restarts == [0]


def test_a_trial_whose_session_never_starts_says_so_and_files_it_anyway(
    tmp_path: Path, clock: FakeClock
) -> None:
    host, trial = played(tmp_path, clock)

    def refused(worktree: Path, resume: str | None) -> HeldUp:
        message = "the launcher of launch h1 ended before its session was up"
        raise HostError(message)

    trial.spawn = refused
    steps = trial.run()
    number = trial.filed(tmp_path / ".git", "claude")

    assert [(each.name, each.passed) for each in steps] == [("held", False)]
    report = written(host.items[number - 1])
    assert "0 of 8 steps passed." in report
    assert (
        "- **held**, failed in 0 s: the launcher of launch h1 ended before its "
        "session was up"
    ) in report
    assert "**held** failing means no session is held on this machine" in report
    assert (
        "Not tried, after that: answers, interrupts, survives a restart, ends, "
        "resumes held, a terminal takes it over, back to held."
    ) in report
    sender = host.items[number - 1].sender
    assert isinstance(sender, Conversation)
    assert sender.session.startswith("spawn-trial-")


def test_a_trial_whose_answer_never_comes_fails_that_step_past_its_patience_and_goes_on(
    tmp_path: Path, clock: FakeClock
) -> None:
    host, trial = played(tmp_path, clock)
    host.words.pop("single word PAPAYA")

    steps = trial.run()

    [answers] = [each for each in steps if each.name == "answers"]
    assert not answers.passed
    assert answers.seen == "no answer holding PAPAYA came within 0:04:00"
    assert answers.took == timedelta(minutes=4)
    assert [each.name for each in steps][-1] == "back to held"


def test_the_trial_s_scratch_worktree_is_made_by_git_pinned_where_a_room_redirected_its_own(
    tmp_path: Path, shell: Shell
) -> None:
    """A room writes its worktree's git directory: a `commondir` there leading to a repository whose `config` names a filter, which a checkout runs, is never followed."""
    repository = tmp_path / "work.git"
    shell.git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(repository))
    seed = tmp_path / "seed"
    shell.git(tmp_path, "clone", "-q", str(repository), str(seed))
    (seed / ".gitattributes").write_text("* filter=planted\n")
    (seed / "file").write_text("content\n")
    shell.commit(seed, "first")
    shell.git(seed, "push", "-q", "origin", "HEAD:refs/heads/dev")
    main = tmp_path / "tree" / "dev"
    shell.git(
        tmp_path,
        "--git-dir",
        str(repository),
        "worktree",
        "add",
        "-q",
        str(main),
        "dev",
    )
    # A copy holding the objects, so git followed there would check out: it
    # does, and runs the filter, where git runs in the worktree unpinned.
    theirs = tmp_path / "theirs.git"
    shell.git(tmp_path, "clone", "-q", "--bare", str(repository), str(theirs))
    ran = tmp_path / "the-filter-ran"
    shell.git(theirs, "config", "filter.planted.smudge", f"touch {ran}; cat")
    (repository / "worktrees" / "dev" / "commondir").write_text(f"{theirs}\n")
    commit = shell.git(tmp_path, "--git-dir", str(repository), "rev-parse", "dev")

    scratch = scratch_worktree(
        main.parent, Git.pinned(repository), "spawn-trial-1", commit
    )

    assert (scratch / "file").read_text() == "content\n"
    assert not ran.exists()


def test_the_trial_s_terminal_launch_takes_over_by_its_flag_from_nothing_on_its_path() -> (
    None
):
    command = taking_over(own_command(), "claude", "s-1", "haiku")

    assert command[:4] == [sys.executable, "-P", "-m", "lup_dev.cli"]
    assert command[4:9] == ["launch", "claude", "--take-over", "--resume", "s-1"]


def test_a_terminal_launch_that_asks_anything_fails_its_step_unanswered(
    tmp_path: Path, clock: FakeClock
) -> None:
    _, trial = played(tmp_path, clock)

    def asking(worktree: Path, session: str) -> TerminalRun:
        return TerminalRun(
            status=-1,
            output="Approve the host zone at the tip of dev? [y/N]: ",
        )

    trial.terminal = asking
    steps = trial.run()

    [taking] = [each for each in steps if each.name == "a terminal takes it over"]
    assert not taking.passed
    assert taking.seen.startswith(
        "the terminal launch asked something, which the trial answers nothing to"
    )
