"""The judge in a launch's own process: each hook answered at once, in a thread of its own, by the copy the repository approved.

The first tests answer hooks in this process, through the routes the launch's
process serves. The others start real processes: `lup-dev worker` itself, on a
repository the judge reads, and a stand-in copy of `lup-dev` whose process
answers through the same routes with a judge the test drives, so a hold waits
until the test lets it go, and a hook can end its process. Nothing sleeps:
what must overlap meets at a barrier or on a socket the test serves, whose
timeouts only end a test that would otherwise hang.
"""

import asyncio
import json
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup_dev import cli
from lup_dev.host.protocol import HostError, Limits, Refused, Register
from lup_dev.host.service import Dispatcher
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    HookJudged,
    JudgeHook,
    WorkerJudge,
    Workers,
    exchanged,
)
from lup_dev.layout import HostLayout
from lup_dev.worker import routes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from lup_dev.layout import Layout

PATIENCE = 60
"""How long a wait that should end at once may take before the test fails."""


@pytest.fixture
def short(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A socket's path is limited in length, so the test's directory is short.
    return tmp_path_factory.mktemp("w")


async def served(
    judge: Callable[[str, str], str], at: Path, said: list[str]
) -> asyncio.Server:
    """Serve the routes a launch's process serves, its modules unmade, judging with `judge`, on `at`."""
    dispatcher = Dispatcher(
        routes={route.kind: route for route in routes(None, judge)},
        answering="a launch's process",
        say=said.append,
        changes=Changes(),
    )
    return await asyncio.start_unix_server(dispatcher.connection, path=at)


def test_each_hook_is_judged_at_once_in_a_thread_of_its_own(short: Path) -> None:
    together = threading.Barrier(2, timeout=PATIENCE)
    released = threading.Event()

    def judge(runtime: str, payload: str) -> str:
        # Two hooks meet at the barrier while a third waits as a hold does: a
        # hook queued behind another would never reach it.
        if payload == "hold":
            released.wait(PATIENCE)
        else:
            together.wait()
        return f"{runtime} judged {payload}"

    async def exercised() -> list[str]:
        server = await served(judge, short / "p.sock", [])
        try:
            held = asyncio.create_task(
                exchanged(short / "p.sock", JudgeHook(runtime="r", payload="hold"))
            )
            first, second = await asyncio.gather(
                exchanged(short / "p.sock", JudgeHook(runtime="r", payload="a")),
                exchanged(short / "p.sock", JudgeHook(runtime="r", payload="b")),
            )
            assert not held.done()
            released.set()
            return [first, second, await held]
        finally:
            server.close()
            await server.wait_closed()

    replies = [HookJudged.model_validate_json(raw) for raw in asyncio.run(exercised())]
    assert [reply.printed for reply in replies] == [
        "r judged a",
        "r judged b",
        "r judged hold",
    ]


def test_judging_that_ends_its_thread_fails_its_hook_and_no_other(
    short: Path,
) -> None:
    def judge(runtime: str, payload: str) -> str:
        if payload == "exit":
            raise SystemExit(3)
        return f"{runtime} judged {payload}"

    said: list[str] = []

    async def exercised() -> list[str]:
        server = await served(judge, short / "p.sock", said)
        try:
            return [
                await exchanged(short / "p.sock", JudgeHook(runtime="r", payload=each))
                for each in ["exit", "after"]
            ]
        finally:
            server.close()
            await server.wait_closed()

    ended, after = asyncio.run(exercised())
    refused = Refused.model_validate_json(ended)
    assert "judging ended its thread: SystemExit(3)" in refused.error
    assert HookJudged.model_validate_json(after).printed == "r judged after"
    assert any("LupDevError: judging ended its thread" in line for line in said)


def registered(worktree: Path, judge: Path) -> Register:
    return Register(
        launch="one",
        runtime="claude",
        worktree=worktree,
        repository=worktree / ".git",
        judge=judge,
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
    )


@pytest.fixture
def isolated(state: Layout, short: Path, monkeypatch: pytest.MonkeyPatch) -> HostLayout:
    """The host's layout, short enough for its sockets, with lup's state under the test's directories, its runtime directory among them: no process the test starts reaches the operator's own host service."""
    del state
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short / "run"))
    host = HostLayout(sockets=short / "host", state=short / "state")
    host.launches.mkdir(parents=True)
    return host


def test_a_launch_s_process_answers_a_hook_as_the_hook_command_does(
    repo: Path, isolated: HostLayout
) -> None:
    launch = registered(repo, Path(sys.executable).parent / "lup-dev")

    def write(call: str) -> str:
        return json.dumps(
            {
                "session_id": "s1",
                "cwd": str(repo),
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(repo / "README.md"),
                    "content": "# New\n",
                },
                "tool_use_id": call,
            }
        )

    started = json.dumps(
        {"session_id": "s1", "cwd": str(repo), "hook_event_name": "SessionStart"}
    )
    printed = CliRunner().invoke(cli.app, ["hook", "claude"], input=write("t1"))
    assert printed.exit_code == 0

    async def exercised() -> list[str]:
        workers = Workers(layout=isolated, say=lambda line: None)
        judge = WorkerJudge(modules=workers)
        try:
            heard = [
                await judge.judged(launch, each) for each in [started, write("t2")]
            ]
            with pytest.raises(HostError, match="Invalid JSON"):
                await judge.judged(launch, "not a payload")
            return heard
        finally:
            await workers.close(launch)

    begun, wrote = asyncio.run(exercised())
    assert begun == ""
    assert wrote == printed.output
    assert json.loads(wrote)["hookSpecificOutput"]["permissionDecision"] == "allow"


# A stand-in copy: its process answers through the routes `lup-dev worker`
# serves, each hook with its copy's name; `hold` tells the test it has arrived
# on the test's socket and waits there until the test answers, and `die` ends
# the process as it judges.
STAND_IN = """#!{python}
import asyncio
import os
import socket
import sys
from pathlib import Path

from lup_dev.host.protocol import Register
from lup_dev.worker import routes, serve

here = Path(__file__).parent


def judge(runtime: str, payload: str) -> str:
    if payload == "hold":
        with socket.socket(socket.AF_UNIX) as told:
            told.connect({holds!r})
            told.sendall(here.name.encode())
            told.recv(16)
    if payload == "die":
        os._exit(3)
    return f"{{here.name}} answers {{payload}}"


def said(line: str) -> None:
    sys.stderr.write(f"{{line}}\\n")


launch = Register.model_validate_json(sys.stdin.readline())
asyncio.run(serve(routes(None, judge), Path(sys.argv[2]), launch, said))
"""


class Holds:
    """The test's side of each hold: told when one arrives, by its copy's name, and letting each go."""

    def __init__(self) -> None:
        self.arrived: asyncio.Queue[str] = asyncio.Queue()
        self.waiting: list[asyncio.StreamWriter] = []

    async def heard(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.waiting.append(writer)
        await self.arrived.put((await reader.read(16)).decode())

    async def next(self) -> str:
        return await asyncio.wait_for(self.arrived.get(), timeout=PATIENCE)

    async def release(self) -> None:
        """Let each hold waiting go; one whose process ended has nothing to hear."""
        for writer in self.waiting:
            try:
                writer.write(b"go")
                await writer.drain()
            except ConnectionError:
                continue
            finally:
                writer.close()
        self.waiting = []


class Copies:
    """Stand-in copies of `lup-dev` under `home`, and the approved command, a link switched from one to the next."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.link = home / "bin"

    def made(self, name: str) -> Path:
        copy = self.home / name
        copy.mkdir()
        command = copy / "lup-dev"
        command.write_text(
            STAND_IN.format(python=sys.executable, holds=str(self.home / "h.sock"))
        )
        command.chmod(0o755)
        return command

    def switch(self, name: str) -> None:
        swapped = self.home / "bin.next"
        swapped.symlink_to(self.home / name)
        swapped.replace(self.link)

    @property
    def command(self) -> Path:
        return self.link / "lup-dev"


@asynccontextmanager
async def stand_ins(
    short: Path, isolated: HostLayout, said: list[str]
) -> AsyncGenerator[tuple[Workers, Copies, Holds]]:
    copies = Copies(short)
    holds = Holds()
    copies.made("a")
    copies.made("b")
    copies.switch("a")
    workers = Workers(layout=isolated, say=said.append)
    server = await asyncio.start_unix_server(holds.heard, path=short / "h.sock")
    try:
        yield workers, copies, holds
    finally:
        await holds.release()
        server.close()
        await server.wait_closed()


def test_a_new_copy_takes_new_hooks_while_the_one_before_finishes_its_hold(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> list[str]:
        async with stand_ins(short, isolated, said) as (workers, copies, holds):
            launch = registered(short, copies.command)
            judge = WorkerJudge(modules=workers)
            assert await judge.judged(launch, "x") == "a answers x"
            first = workers.running["one"]
            held = asyncio.create_task(judge.judged(launch, "hold"))
            assert await holds.next() == "a"
            copies.switch("b")
            after = await judge.judged(launch, "y")
            # The process of `a` still answers the hold it was asked, and
            # nothing new reaches it.
            assert first.process.returncode is None
            assert sorted(each.parent.name for each in workers.commands()) == [
                "a",
                "b",
            ]
            await holds.release()
            answered = await asyncio.wait_for(held, timeout=PATIENCE)
            await asyncio.wait_for(asyncio.gather(*workers.retiring), PATIENCE)
            assert first.process.returncode is not None
            assert not first.socket.exists()
            assert [each.parent.name for each in workers.commands()] == ["b"]
            again = await judge.judged(launch, "z")
            await workers.close(launch)
            return [after, answered, again]

    assert asyncio.run(exercised()) == ["b answers y", "a answers hold", "b answers z"]
    assert any(
        f"its repository's approved copy is {short / 'b' / 'lup-dev'}" in line
        for line in said
    )
    assert any(
        f"its process from {short / 'a' / 'lup-dev'} has answered what it was asked"
        in line
        for line in said
    )


def test_a_launch_s_process_that_dies_judging_fails_that_hook_and_starts_again(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> str:
        async with stand_ins(short, isolated, said) as (workers, copies, _):
            launch = registered(short, copies.command)
            judge = WorkerJudge(modules=workers)
            await workers.open(launch)
            dying = workers.running["one"]
            with pytest.raises(HostError, match="ended before it answered"):
                await judge.judged(launch, "die")
            await asyncio.wait_for(dying.process.wait(), timeout=PATIENCE)
            again = await judge.judged(launch, "x")
            assert workers.running["one"] is not dying
            assert not dying.socket.exists()
            await workers.close(launch)
            return again

    assert asyncio.run(exercised()) == "a answers x"
    assert "one: its process is gone; starting it again" in said


def test_a_launch_ending_ends_its_processes_a_replaced_one_holding_among_them(
    short: Path, isolated: HostLayout
) -> None:
    async def exercised() -> None:
        async with stand_ins(short, isolated, []) as (workers, copies, holds):
            launch = registered(short, copies.command)
            judge = WorkerJudge(modules=workers)
            held = asyncio.create_task(judge.judged(launch, "hold"))
            assert await holds.next() == "a"
            first = workers.running["one"]
            copies.switch("b")
            assert await judge.judged(launch, "y") == "b answers y"
            second = workers.running["one"]
            await workers.close(launch)
            assert first.process.returncode is not None
            assert second.process.returncode is not None
            assert workers.commands() == []
            assert not list(isolated.launches.glob("one.modules.*"))
            with pytest.raises(HostError):
                await asyncio.wait_for(held, timeout=PATIENCE)

    asyncio.run(exercised())
