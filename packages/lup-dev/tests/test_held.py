"""Sessions held with no terminal, as the host service starts and reaches their launchers: real short-lived programs stand in for a launcher, and a socket served in-process for its own."""

import asyncio
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.programs import Apart, Ran, detached
from lup_dev import cli
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient, Outstanding, own_command
from lup_dev.host.held import (
    Abandon,
    Abandoning,
    AwaitHeld,
    Awaiting,
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
    Starting,
    launcher_command,
    launching,
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
    Exchange,
    Exchanged,
    FileReport,
    FinishItem,
    ListItems,
    SendItem,
    Shown,
)
from lup_dev.inbox.store import Item, Message
from lup_dev.inbox.texts import written
from lup_dev.launch import trial
from lup_dev.launch.trial import (
    TerminalRun,
    Trial,
    TrialError,
    scratch_worktree,
    scratched,
    taken_over_there,
    taking_over,
)
from lup_dev.layout import HostLayout, HostPaths, Layout
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


def test_a_spawn_starts_its_launcher_and_its_await_answers_once_it_calls_its_session_up(
    layout: Layout, tmp_path: Path
) -> None:
    started: list[HeldLaunch] = []
    launchers = Launchers()

    def start(spec: HeldLaunch, log: Path) -> Apart:
        started.append(spec)
        return detached("sleep", "60", log=log)

    async def spawned() -> tuple[Starting, Reply]:
        starting = await Spawning(
            layout=layout, launchers=launchers, start=start
        ).answer(asking(tmp_path))
        assert isinstance(starting, Starting)
        # Called up before anyone awaits it, as a launcher may be.
        await CallingUp(launchers=launchers).answer(
            CalledUp(launch=starting.launch, name="dev", session="s-1")
        )
        awaited = await Awaiting(
            layout=layout, launchers=launchers, pause=yielded
        ).answer(AwaitHeld(launch=starting.launch, pid=starting.pid))
        return starting, awaited

    starting, awaited = asyncio.run(spawned())

    [spec] = started
    assert starting == Starting(
        launch=spec.launch,
        pid=launchers.started[spec.launch].process.pid,
        log=layout.launch(spec.launch).log,
    )
    assert awaited == HeldUp(
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
    launcher = launchers.started[spec.launch]
    launcher.process.kill()
    launcher.process.wait()
    launchers.reaped()
    assert launchers.started == {}
    assert launchers.waiting == {}


def test_a_spawn_whose_launcher_ends_first_is_refused_with_what_it_wrote(
    layout: Layout, tmp_path: Path
) -> None:
    launchers = Launchers()

    def start(spec: HeldLaunch, log: Path) -> Apart:
        return detached(
            "sh", "-c", f"echo 'the room never started: {spec.launch}'", log=log
        )

    async def refused() -> Reply:
        starting = await Spawning(
            layout=layout, launchers=launchers, start=start
        ).answer(asking(tmp_path))
        assert isinstance(starting, Starting)
        return await Awaiting(layout=layout, launchers=launchers, pause=yielded).answer(
            AwaitHeld(launch=starting.launch, pid=starting.pid)
        )

    answer = asyncio.run(refused())

    assert isinstance(answer, Refused)
    assert "ended before its session was up" in answer.error
    assert "\nthe room never started: " in answer.error


def test_a_spawn_abandoned_before_its_session_is_up_ends_its_launcher_and_one_up_is_refused(
    layout: Layout, tmp_path: Path
) -> None:
    launchers = Launchers()

    def start(spec: HeldLaunch, log: Path) -> Apart:
        return detached("sleep", "60", log=log)

    async def abandoned() -> tuple[Starting, Starting, str]:
        spawning = Spawning(layout=layout, launchers=launchers, start=start)
        first = await spawning.answer(asking(tmp_path))
        second = await spawning.answer(asking(tmp_path))
        assert isinstance(first, Starting)
        assert isinstance(second, Starting)
        await Abandoning(launchers=launchers).answer(
            Abandon(launch=first.launch, pid=first.pid)
        )
        await CallingUp(launchers=launchers).answer(
            CalledUp(launch=second.launch, name="dev", session="s-1")
        )
        try:
            await Abandoning(launchers=launchers).answer(
                Abandon(launch=second.launch, pid=second.pid)
            )
        except HostError as up:
            return first, second, str(up)
        return first, second, ""

    first, second, refusal = asyncio.run(abandoned())

    assert launchers.started[first.launch].ended()
    assert refusal == (
        f"launch {second.launch}'s session is up already: `lup-dev spawn end` ends it"
    )
    still = launchers.started[second.launch]
    still.process.kill()
    still.process.wait()


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
    "single word READY": "READY",
    "single word PEAR": "PEAR",
    "single word MANGO": "MANGO",
    "single word PLUM": "PLUM",
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

    def item(
        self, sender: Party, recipient: Party, text: str, *, ending: bool | None = None
    ) -> Item:
        """Keep an item, a turn's end where its sender is the session unless `ending` says otherwise."""
        made = Item(
            number=len(self.items) + 1,
            reason=Message(
                kind="note",
                text=text,
                ending=sender != Operator() if ending is None else ending,
            ),
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
                if "time.sleep" in text or "wait_inbox" in text:
                    self.calling.append(True)
                elif answer is not None:
                    self.item(self.conversation, Operator(), answer)
                return reply.model_validate(Shown(item=sent).model_dump())
            case ListItems():
                # As the host answers it: what the conversation sent, and what they were sent.
                def exchange(each: Item) -> Exchange:
                    return Exchange(
                        item=each, text=written(each), line=[], at=each.made
                    )

                exchanged = Exchanged(
                    sent=[
                        exchange(each)
                        for each in self.items
                        if each.sender == self.conversation
                    ],
                    received=[
                        exchange(each)
                        for each in self.items
                        if each.recipient == self.conversation
                    ],
                )
                return reply.model_validate(exchanged.model_dump())
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
            held(launch).model_copy(
                update={"container": "lup-trial", "name": "trial", "worktree": worktree}
            )
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
        inside=lambda container, command: TerminalRun(
            status=2, output="opening /proc/7/fd/0: [Errno 6] No such device or address"
        ),
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
    noted = host.item(host.conversation, Operator(), "A note.", ending=False)
    number = trial.filed(tmp_path / ".git", "claude")

    assert noted.number not in [
        each.number for each in host.asked if isinstance(each, FinishItem)
    ]
    assert [(each.name, each.passed) for each in steps] == [
        ("held", True),
        ("answers", True),
        ("the room can't type as the operator", True),
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
        "9 of 9 steps passed."
    )
    assert "**What it means:** a session lup holds with no terminal works" in report
    assert host.items[number - 1].sender == host.conversation
    finished = [each.number for each in host.asked if isinstance(each, FinishItem)]
    assert finished == [
        each.number
        for each in host.items[: number - 1]
        if each.recipient == Operator()
        and each.sender == host.conversation
        and each.number != noted.number
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
    assert "0 of 9 steps passed." in report
    assert (
        "- **held**, failed in 0 s: the launcher of launch h1 ended before its "
        "session was up"
    ) in report
    assert "**held** failing means no session is held on this machine" in report
    assert (
        "Not tried, after that: answers, the room can't type as the operator, "
        "interrupts, survives a restart, ends, resumes held, a terminal takes it "
        "over, back to held."
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


def repository_with_a_worktree(tmp_path: Path, shell: Shell) -> tuple[Path, Path, str]:
    """A bare repository laid out as lup's, a worktree of it under `tree/`, and its one commit, whose `.gitattributes` names a filter its `config` doesn't."""
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
    commit = shell.git(tmp_path, "--git-dir", str(repository), "rev-parse", "dev")
    return repository, main, commit


def test_the_trial_s_scratch_worktree_is_made_by_git_pinned_where_a_room_redirected_its_own(
    tmp_path: Path, shell: Shell
) -> None:
    """A room writes its worktree's git directory: a `commondir` there leading to a repository whose `config` names a filter, which a checkout runs, is never followed."""
    repository, main, commit = repository_with_a_worktree(tmp_path, shell)
    # A copy holding the objects, so git followed there would check out: it
    # does, and runs the filter, where git runs in the worktree unpinned.
    theirs = tmp_path / "theirs.git"
    shell.git(tmp_path, "clone", "-q", "--bare", str(repository), str(theirs))
    ran = tmp_path / "the-filter-ran"
    shell.git(theirs, "config", "filter.planted.smudge", f"touch {ran}; cat")
    (repository / "worktrees" / "dev" / "commondir").write_text(f"{theirs}\n")

    scratch = scratch_worktree(
        main.parent, Git.pinned(repository), "spawn-trial-1", commit
    )

    assert (scratch / "file").read_text() == "content\n"
    assert not ran.exists()


def test_the_trial_makes_its_worktree_pinned_at_the_approved_commit(
    tmp_path: Path, shell: Shell
) -> None:
    repository, main, commit = repository_with_a_worktree(tmp_path, shell)

    scratch = scratched(
        main, "spawn-trial-1", lambda found: commit if found == repository else None
    )

    assert scratch.path == main.parent / "spawn-trial-1"
    assert scratch.git == Git.pinned(repository)
    assert shell.git(scratch.path, "rev-parse", "HEAD") == commit
    scratch.removed()
    assert not scratch.path.exists()


def test_the_trial_refuses_a_worktree_a_room_led_to_a_repository_not_approved(
    tmp_path: Path, shell: Shell
) -> None:
    """A `commondir` a room planted leads the worktree's repository elsewhere: that one isn't approved, so nothing is checked out there, and its filter never runs."""
    repository, main, commit = repository_with_a_worktree(tmp_path, shell)
    theirs = tmp_path / "theirs.git"
    shell.git(tmp_path, "clone", "-q", "--bare", str(repository), str(theirs))
    ran = tmp_path / "the-filter-ran"
    shell.git(theirs, "config", "filter.planted.smudge", f"touch {ran}; cat")
    (repository / "worktrees" / "dev" / "commondir").write_text(f"{theirs}\n")

    with pytest.raises(TrialError, match="nothing is approved for"):
        scratched(
            main, "spawn-trial-1", lambda found: commit if found == repository else None
        )

    assert not ran.exists()
    assert not (main.parent / "spawn-trial-1").exists()


def test_the_service_and_the_trial_s_terminal_launch_start_with_nothing_of_where_they_run_on_their_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert own_command() == [sys.executable, "-P", "-m", "lup_dev.cli"]
    assert Detached().command == [*own_command(), "host"]
    started: list[tuple[list[str], Path | None]] = []

    async def recorded(
        program: str, *arguments: str, cwd: Path | None = None, **_: object
    ) -> Ran:
        started.append(([program, *arguments], cwd))
        return Ran(command=[program, *arguments], status=0, output=b"KIWI\n")

    monkeypatch.setattr(trial, "awaited", recorded)

    ran = taken_over_there(tmp_path, "s-1", "claude", "haiku")

    [(command, cwd)] = started
    assert command == taking_over(own_command(), "claude", "s-1", "haiku")
    assert cwd == tmp_path
    assert ran == TerminalRun(status=0, output="KIWI\n")


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


def test_a_turn_the_room_writes_to_the_session_s_input_fails_the_trial_saying_so(
    tmp_path: Path, clock: FakeClock
) -> None:
    host, trial = played(tmp_path, clock)

    def written(container: str, command: list[str]) -> TerminalRun:
        host.item(host.conversation, Operator(), "FORGED")
        return TerminalRun(status=0, output="wrote a turn to /proc/7/fd/0")

    trial.inside = written
    steps = trial.run()

    [forging] = [
        each for each in steps if each.name == "the room can't type as the operator"
    ]
    assert not forging.passed
    assert forging.seen.startswith(
        "a process in the room wrote a turn to the session's input, and the "
        "session answered it, @"
    )
    assert forging.seen.endswith(": wrote a turn to /proc/7/fd/0")


def test_another_room_process_holding_the_session_s_socket_fails_the_trial(
    tmp_path: Path, clock: FakeClock
) -> None:
    _, trial = played(tmp_path, clock)
    trial.inside = lambda container, command: TerminalRun(
        status=4,
        output="opening /proc/7/fd/0 (socket:[1]): [Errno 6]; but processes ['9'] hold it too",
    )

    steps = trial.run()

    [forging] = [
        each for each in steps if each.name == "the room can't type as the operator"
    ]
    assert not forging.passed
    assert "(status 4)" in forging.seen


def test_a_trial_whose_resume_fails_ends_no_launch_in_its_place(
    tmp_path: Path, clock: FakeClock
) -> None:
    """The held launch the trial ended stays the last it knew of; a start that failed after must not have the trial end some launch in its place."""
    host, trial = played(tmp_path, clock)
    spawn = trial.spawn

    def failing(worktree: Path, resume: str | None) -> HeldUp:
        if resume is not None:
            host.served[:] = [held("someone-else")]
            message = "the launcher ended before its session was up"
            raise HostError(message)
        return spawn(worktree, resume)

    trial.spawn = failing
    steps = trial.run()

    [resumed] = [each for each in steps if each.name == "resumes held"]
    assert not resumed.passed
    ends = [each.launch for each in host.asked if isinstance(each, End)]
    assert "someone-else" not in ends
    # What follows acts on no launch the trial no longer holds.
    [taking] = [each for each in steps if each.name == "a terminal takes it over"]
    assert taking.seen == "no held session is up"


def test_a_room_whose_kernel_lets_any_process_trace_another_fails_the_trial(
    tmp_path: Path, clock: FakeClock
) -> None:
    _, trial = played(tmp_path, clock)
    trial.inside = lambda container, command: TerminalRun(
        status=5,
        output=(
            "opening /proc/7/fd/0 (socket:[1]): [Errno 6]; but yama's ptrace_scope "
            "is 0, so a process of the room may trace the session"
        ),
    )

    steps = trial.run()

    [forging] = [
        each for each in steps if each.name == "the room can't type as the operator"
    ]
    assert not forging.passed
    assert "(status 5)" in forging.seen


def test_a_service_started_since_awaits_a_launcher_it_didn_t_start_by_its_process(
    layout: Layout, tmp_path: Path
) -> None:
    """An approval the launcher asked restarts the service: the one after hears the launcher call its session up, and the operator's wait asked again finds it; a launcher whose process is gone is said so."""
    paths = HostPaths(proc=tmp_path / "proc")
    running = paths.proc / "41"
    running.mkdir(parents=True)
    (running / "cmdline").write_bytes(
        b"python3\0-P\0-m\0lup_dev.cli\0spawn\0launcher\0{a1}"
    )
    launchers = Launchers()
    awaiting = Awaiting(layout=layout, launchers=launchers, paths=paths, pause=yielded)

    async def awaited() -> tuple[Reply, Reply]:
        await CallingUp(launchers=launchers).answer(
            CalledUp(launch="a1", name="dev", session="s-1")
        )
        up = await awaiting.answer(AwaitHeld(launch="a1", pid=41))
        gone = await awaiting.answer(AwaitHeld(launch="b2", pid=42))
        return up, gone

    up, gone = asyncio.run(awaited())

    assert up == HeldUp(
        launch="a1", name="dev", session="s-1", log=layout.launch("a1").log
    )
    assert isinstance(gone, Refused)
    assert "the launcher of launch b2 ended before its session was up" in gone.error


def test_a_launcher_is_never_taken_for_another_process_given_its_id_since(
    tmp_path: Path,
) -> None:
    paths = HostPaths(proc=tmp_path / "proc")
    other = paths.proc / "41"
    other.mkdir(parents=True)
    (other / "cmdline").write_bytes(b"vim\0notes.md")

    assert not launching(paths, 41, "a1")
    assert not launching(paths, 43, "a1")


def test_the_trial_ends_every_held_launch_left_in_its_worktree_before_removing_it(
    tmp_path: Path, clock: FakeClock
) -> None:
    """A start whose launcher came up after the trial stopped waiting on it, as through a restart of the service, leaves a launch the trial never knew."""
    host, trial = played(tmp_path, clock)
    spawn = trial.spawn

    def lost(worktree: Path, resume: str | None) -> HeldUp:
        if resume is None:
            return spawn(worktree, resume)
        host.served[:] = [
            held("lost").model_copy(update={"worktree": worktree, "name": "lost"}),
            held("elsewhere"),
        ]
        message = "the host service closed its wait on launch lost 3 times"
        raise HostError(message)

    trial.spawn = lost
    trial.run()

    ends = [each.launch for each in host.asked if isinstance(each, End)]
    assert "lost" in ends
    assert "elsewhere" not in ends
