"""Sessions held with no terminal, as the host service starts and reaches their launchers: real short-lived programs stand in for a launcher, and a socket served in-process for its own."""

import asyncio
from pathlib import Path

import pytest

from lup.programs import Apart, detached
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
from lup_dev.host.protocol import Done, HostError, Limits, Refused, Register
from lup_dev.host.service import Dispatcher, Route, unix_server
from lup_dev.host.watch import Changes
from lup_dev.layout import Layout


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
