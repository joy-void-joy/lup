"""Sessions held with no terminal, as the host service starts and reaches their launchers: real short-lived programs stand in for a launcher, and a socket served in-process for its own."""

import asyncio
import json
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup.programs import Apart, Ran, detached, run
from lup.rooms.engine import Podman
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
    SpawnedLauncher,
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
    Spawner,
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
from lup_dev.inbox.store import How, Item, Message, Told
from lup_dev.inbox.texts import written
from lup_dev.launch import trial
from lup_dev.launch.trial import (
    Scratch,
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


def test_a_launcher_an_agent_s_spawn_started_is_counted_until_it_ends_and_one_never_up_is_handed_back(
    layout: Layout, tmp_path: Path
) -> None:
    """The limit counts a spawn from its launcher's start, before its launch registers; one whose session never came up is returned as it's collected, for its spawner to hear of, and one that came up isn't."""
    launchers = Launchers()
    ending: list[str] = []
    spawner = Spawner(
        launch="s0",
        conversation=Conversation(
            repository=tmp_path / ".git", runtime="claude", session="p1"
        ),
    )

    def start(spec: HeldLaunch, log: Path) -> Apart:
        return detached("sleep", "60", log=log)

    async def spawned() -> tuple[list[HeldLaunch], list[HeldLaunch]]:
        starting = Spawning(layout=layout, launchers=launchers, start=start)
        never = await starting.started(
            lambda launch: HeldLaunch(
                launch=launch, runtime="claude", worktree=tmp_path, spawner=spawner
            )
        )
        up = await starting.started(
            lambda launch: HeldLaunch(
                launch=launch, runtime="claude", worktree=tmp_path, spawner=spawner
            )
        )
        await CallingUp(launchers=launchers).answer(
            CalledUp(launch=up.launch, name="two", session="s-2")
        )
        counted = launchers.spawning(layout)
        for each in [never, up]:
            ending.append(each.launch)
            launcher = launchers.started[each.launch]
            launcher.process.kill()
            launcher.process.wait()
        return counted, launchers.reaped()

    counted, lost = asyncio.run(spawned())

    never, _ = ending
    assert len(counted) == 2
    assert [each.launch for each in lost] == [never]
    assert launchers.spawning(layout) == []
    assert launchers.specs == {}


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
    "single word DATE": "DATE",
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
    sessions: dict[str, Conversation] = {}
    """The conversation of each launch the trial's session spawned, by its id;
    the trial's own launches' is `conversation`."""
    briefing: list[How] = ["wake"]
    """How each brief is told, the last: given once as the first turn, or
    otherwise, as a brief told twice reads."""
    reporting: list[bool] = []
    """Holding anything, the side job puts its report before the operator too,
    as it mustn't."""
    fleeting: list[str] = []
    """Each launch served until the trial's next look at the launches after
    the one that found it: a side job, which ends at its report."""

    def party(self, launch: str) -> Conversation:
        """The conversation of `launch`'s session."""
        return self.sessions.get(launch, self.conversation)

    def spawned(self, name: str, concern: int | None) -> Conversation:
        """Serve a launch the trial's session spawned, named `name`, a side job unless `concern` is handed with it, in a worktree of its own, and return its session's conversation."""
        [spawner] = [each for each in self.served if each.spawner is None]
        launch = held(name).model_copy(
            update={
                "name": name,
                "worktree": Path("/w/.git/tree") / name,
                "session": f"s-{name}",
                "spawner": Spawner(
                    launch=spawner.launch,
                    conversation=self.conversation,
                    concern=concern,
                ),
            }
        )
        self.served.append(launch)
        if concern is None:
            self.fleeting.append(name)
        party = Conversation(
            repository=launch.repository, runtime="claude", session=f"s-{name}"
        )
        self.sessions[name] = party
        # Its brief, given once as its first turn, as the host gives it.
        brief = self.item(self.conversation, party, "The brief.", ending=False)
        self.items[-1] = brief.model_copy(
            update={"state": Told(at=brief.made, how=self.briefing[-1])}
        )
        return party

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
        looked = list(self.served)
        self.served[:] = [
            each for each in self.served if each.launch not in self.fleeting
        ]
        self.fleeting.clear()
        return looked

    @override
    def listed(self) -> Listed:
        def talkers(launch: str) -> list[Talker]:
            return [
                Talker(
                    path="t",
                    own="t",
                    session=self.party(launch).session,
                    activity=Activity(
                        state="calling", since=datetime(2026, 11, 8, tzinfo=UTC)
                    )
                    if self.calling and launch not in self.sessions
                    else None,
                )
            ]

        # What the host heard of a launch's session stays once it ended.
        heard = [*(each.launch for each in self.served), *self.sessions]
        return Listed(
            launches=self.served,
            talkers={launch: talkers(launch) for launch in heard},
        )

    @override
    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        self.asked.append(request)
        match request:
            case SendItem(launch=launch, text=text):
                party = self.party(launch)
                sent = self.item(Operator(), party, text)
                answer = next(
                    (word for cue, word in self.words.items() if cue in text), None
                )
                if "`send` with `to` `trial-side-job`" in text:
                    # Resumed by the send, it answers, and ends again.
                    [side] = [
                        each for each in self.served if each.launch == "trial-side-job"
                    ] or [
                        held("trial-side-job").model_copy(
                            update={"session": "s-trial-side-job"}
                        )
                    ]
                    again = side.model_copy(update={"launch": "trial-side-job-2"})
                    self.served.append(again)
                    self.fleeting.append(again.launch)
                    self.item(self.conversation, Operator(), "LIME")
                elif "`trial side job`" in text:
                    side = self.spawned("trial-side-job", None)
                    self.item(side, self.conversation, "LIME", ending=False)
                    if any(self.reporting):
                        self.item(side, Operator(), "LIME")
                    self.item(self.conversation, Operator(), "LIME")
                elif "`trial builder`" in text:
                    builder = self.spawned("trial-builder", 5)
                    self.item(self.conversation, Operator(), "SENT")
                    self.item(builder, Operator(), "FIG")
                elif "time.sleep" in text or "wait_inbox" in text:
                    self.calling.append(True)
                elif answer is not None:
                    self.item(party, Operator(), answer)
                return reply.model_validate(Shown(item=sent).model_dump())
            case ListItems(conversation=conversation):
                # As the host answers it: what the conversation sent, and what they were sent.
                def exchange(each: Item) -> Exchange:
                    return Exchange(
                        item=each, text=written(each), line=[], at=each.made
                    )

                exchanged = Exchanged(
                    sent=[
                        exchange(each)
                        for each in self.items
                        if each.sender == conversation
                    ],
                    received=[
                        exchange(each)
                        for each in self.items
                        if each.recipient == conversation
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
            # A side job ends with the launch that spawned it.
            self.served[:] = [
                each
                for each in self.served
                if each.launch != request.launch
                and not (
                    each.spawner is not None
                    and each.spawner.launch == request.launch
                    and each.spawner.concern is None
                )
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
        host.sessions.clear()
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
        running=lambda container: any(
            each.container == container for each in host.served
        ),
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
        ("spawns a side job", True),
        ("resumes its side job", True),
        ("hands a concern over", True),
        ("ends", True),
        ("a builder outlives its spawner", True),
        ("resumes held", True),
        ("a terminal takes it over", True),
        ("back to held", True),
    ], [each.seen for each in steps]
    report = written(host.items[number - 1])
    assert report.startswith(
        f"**Spawn's trial**, `lup-dev spawn trial`, in {tmp_path / 'spawn-trial-1'}: "
        "13 of 13 steps passed."
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
    assert "0 of 13 steps passed." in report
    assert (
        "- **held**, failed in 0 s: the launcher of launch h1 ended before its "
        "session was up"
    ) in report
    assert "**held** failing means no session is held on this machine" in report
    assert (
        "Not tried, after that: answers, the room can't type as the operator, "
        "interrupts, survives a restart, spawns a side job, resumes its side job, "
        "hands a concern over, ends, a builder outlives its spawner, resumes held, "
        "a terminal takes it over, back to held."
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
        "a process in the room wrote a turn the session took as yours, answering it, @"
    )
    assert forging.seen.endswith(": wrote a turn to /proc/7/fd/0")


def test_a_turn_written_where_the_session_never_takes_it_passes_the_trial_saying_where(
    tmp_path: Path, clock: FakeClock
) -> None:
    """A write that reaches nothing, as init's `/dev/null` takes one, is no turn of the session's: its answering FORGED alone says one got through."""
    _, trial = played(tmp_path, clock)

    def written(container: str, command: list[str]) -> TerminalRun:
        return TerminalRun(status=0, output='{"tried": ["9 (sh), a turn written"]}')

    trial.inside = written
    steps = trial.run()

    [forging] = [
        each for each in steps if each.name == "the room can't type as the operator"
    ]
    assert forging.passed
    assert forging.seen == (
        "A process in the room wrote a turn somewhere, and the session didn't take "
        "it within 0:01:00, so it didn't reach it: "
        '{"tried": ["9 (sh), a turn written"]}'
    )


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


def test_a_side_job_putting_its_report_before_the_operator_fails_its_step(
    tmp_path: Path, clock: FakeClock
) -> None:
    host, trial = played(tmp_path, clock)
    host.reporting.append(True)

    steps = trial.run()

    [side] = [each for each in steps if each.name == "spawns a side job"]
    assert not side.passed
    assert side.seen.startswith("the side job put @")
    assert side.seen.endswith("before you, where its report is its spawner's alone")
    # The trial goes on, and ends what the session spawned with the rest.
    assert [each.name for each in steps][-1] == "back to held"


def test_the_trial_removes_the_worktree_and_branch_of_each_launch_its_session_spawned(
    tmp_path: Path, shell: Shell
) -> None:
    repository, main, commit = repository_with_a_worktree(tmp_path, shell)
    made = repository / "tree" / "trial-side-job"
    shell.git(
        tmp_path,
        "--git-dir",
        str(repository),
        "worktree",
        "add",
        "-q",
        "--no-checkout",
        "-b",
        "trial-side-job",
        str(made),
        commit,
    )
    said: list[str] = []
    scratch = Scratch(path=main, repository=repository, git=Git.pinned(repository))
    outside = held("elsewhere").model_copy(update={"worktree": tmp_path / "elsewhere"})

    scratch.unspawned(
        [held("side").model_copy(update={"worktree": made}), outside], said.append
    )

    assert not made.exists()
    assert (
        shell.git(
            tmp_path, "--git-dir", str(repository), "branch", "--list", "trial-side-job"
        )
        == ""
    )
    assert said == [f"{tmp_path / 'elsewhere'} isn't one a spawn made, so it's left."]


def test_a_brief_told_twice_fails_its_spawn_step(
    tmp_path: Path, clock: FakeClock
) -> None:
    """Given as the first turn and told again beside a hook, it reads as told some other way than its wake."""
    host, trial = played(tmp_path, clock)
    host.briefing.append("turn's start")

    steps = trial.run()

    [side] = [each for each in steps if each.name == "spawns a side job"]
    assert not side.passed
    assert "was told \"turn's start\", where it's given once as the first turn" in (
        side.seen
    )


def test_a_launcher_a_service_before_started_for_a_spawn_is_counted_while_it_runs(
    layout: Layout, tmp_path: Path
) -> None:
    """Kept beside its lock: a service started since knows it by its process, and forgets it once that's gone."""
    spawner = Spawner(
        launch="s0",
        conversation=Conversation(
            repository=tmp_path / ".git", runtime="claude", session="p1"
        ),
    )
    layout.launches.mkdir(parents=True)

    def kept(launch: str, pid: int) -> None:
        spec = HeldLaunch(
            launch=launch, runtime="claude", worktree=tmp_path, spawner=spawner
        )
        layout.launch(launch).spawned.write_text(
            SpawnedLauncher(spec=spec, pid=pid).model_dump_json()
        )

    # A program that keeps the launch's id among its arguments, as the
    # launcher's command does: a shell may replace itself with what it runs.
    running = detached(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        "a1",
        log=tmp_path / "a1.log",
    )
    gone = detached("true", "b1", log=tmp_path / "b1.log")
    gone.process.wait()
    cmdline = Path("/proc") / str(running.process.pid) / "cmdline"
    for _ in range(600):
        if b"a1" in cmdline.read_bytes():
            break
        time.sleep(0.01)
    kept("a1", running.process.pid)
    kept("b1", gone.process.pid)
    try:
        counted = Launchers().spawning(layout)
    finally:
        running.process.kill()
        running.process.wait()

    assert [each.launch for each in counted] == ["a1"]
    assert layout.launch("a1").spawned.exists()
    assert not layout.launch("b1").spawned.exists()


def test_a_side_job_whose_spawner_s_launch_isn_t_served_is_orphaned_and_a_builder_isn_t() -> (
    None
):
    spawner = Spawner(
        launch="gone",
        conversation=Conversation(
            repository=Path("/w/.git"), runtime="claude", session="p1"
        ),
    )
    side = held("side").model_copy(update={"spawner": spawner})
    built = held("built").model_copy(
        update={"spawner": spawner.model_copy(update={"concern": 4})}
    )
    kept = held("kept").model_copy(
        update={"spawner": spawner.model_copy(update={"launch": "here"})}
    )

    assert cli.orphaned([side, built, kept, held("here")]) == [side]


def test_the_sweep_ends_each_side_job_whose_spawner_s_launch_isn_t_served(
    layout: Layout, tmp_path: Path, clock: FakeClock
) -> None:
    """One handed a concern runs on: it's the operator's to end."""
    host, _ = played(tmp_path, clock)
    spawner = Spawner(launch="gone", conversation=host.conversation)
    host.served[:] = [
        held("side").model_copy(update={"spawner": spawner, "name": "side"}),
        held("built").model_copy(
            update={"spawner": spawner.model_copy(update={"concern": 3})}
        ),
    ]
    said: list[str] = []
    sweeping = cli.Sweeping(
        layout=layout, host=host, podman=Podman(), say=said.append, running=list
    )

    async def swept() -> None:
        await sweeping.orphans_ended()
        await asyncio.gather(*sweeping.ending.values())

    asyncio.run(swept())

    assert [each.launch for each in host.asked if isinstance(each, End)] == ["side"]
    assert [each.launch for each in host.served] == ["built"]
    assert (
        "side: a side job whose spawner's launch gone ended, so it's ended too"
    ) in said


def process_table(root: Path, processes: dict[int, tuple[str, dict[int, str]]]) -> Path:
    """A processes' directory as `/proc` lays one out, each process's command line and its descriptors' links, Yama's scope at 1."""
    for pid, (command, descriptors) in processes.items():
        fds = root / str(pid) / "fd"
        fds.mkdir(parents=True)
        (root / str(pid) / "cmdline").write_bytes(
            b"".join(f"{word}\0".encode() for word in command.split())
        )
        for fd, target in descriptors.items():
            (fds / str(fd)).symlink_to(target)
    (root / "sys" / "kernel" / "yama").mkdir(parents=True)
    (root / "sys" / "kernel" / "yama" / "ptrace_scope").write_text("1\n")
    return root


def probed(tmp_path: Path, processes: dict[int, tuple[str, dict[int, str]]]) -> Ran:
    """Run the trial's probe over the processes given, as in a room."""
    table = process_table(tmp_path / "proc", processes)
    probe = Trial.model_fields["forging"].default
    assert isinstance(probe, str)
    return run(sys.executable, "-c", probe, str(table), checked=False)


INIT = (
    "catatonit -- python3 -I /l/connected.py /run/lup/session.sock lup-environment "
    "claude --output-format stream-json --input-format stream-json"
)
"""podman's `--init`, pid 1: its command line carries the whole command it runs,
`--input-format` among it, and its input is `/dev/null`."""


def test_the_room_s_probe_tries_the_runtime_s_socket_never_init_s_dev_null(
    tmp_path: Path,
) -> None:
    ran = probed(
        tmp_path,
        {
            1: (INIT, {0: "/dev/null"}),
            7: (
                "claude --input-format stream-json",
                {0: "socket:[42]", 1: "socket:[42]"},
            ),
            9: ("bash -c ls", {0: "pipe:[7]"}),
        },
    )

    said = json.loads(ran.output)
    assert ran.status == 2, said
    assert said["session"] == "7 (claude --input-format), its input socket:[42]"
    assert said["tried"] == [
        (
            "7 (claude --input-format), its input socket:[42]: opening it refused, "
            "No such file or directory"
        ),
        (
            "1 (catatonit --), its input /dev/null: not tried, its input is neither "
            "a socket nor a pipe"
        ),
    ]
    assert said["holding"] == []


def test_the_room_s_probe_finds_no_session_on_a_file_and_names_another_holding_its_socket(
    tmp_path: Path,
) -> None:
    writable = tmp_path / "input"
    writable.write_text("")
    ran = probed(
        tmp_path,
        {
            1: (INIT, {0: "/dev/null"}),
            7: ("claude --input-format stream-json", {0: str(writable)}),
            8: ("nc -l", {0: "socket:[5]"}),
        },
    )
    held_too = probed(
        tmp_path / "again",
        {
            7: ("claude --input-format stream-json", {0: "socket:[42]"}),
            12: ("sh", {0: "/dev/null", 3: "socket:[42]"}),
        },
    )

    # A runtime whose input isn't a socket isn't the session's; a socket's
    # process is tried, and the session answering alone says a turn got through.
    assert ran.status == 3, ran.output
    assert held_too.status == 4, held_too.output
    assert json.loads(held_too.output)["holding"] == ["12 (sh), its input /dev/null"]
