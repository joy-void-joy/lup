"""The judge in a repository's process: each hook answered at once, in a thread of its own, by the copy the repository approved, for every launch of it.

The first tests answer hooks in this process, through the routes the
repository's process serves. The others start real processes: `lup-dev worker`
itself, on a repository the judge reads, and a stand-in copy of `lup-dev` whose
process answers through the same routes with a judge the test drives, so a hold
waits until the test lets it go, and a hook can end its process. Nothing sleeps:
what must overlap meets at a barrier or on a socket the test serves, whose
timeouts only end a test that would otherwise hang, and a process nothing holds
ends at once where a test says it idles for no time.
"""

import asyncio
import json
import sys
import threading
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup.tools.serving import Answer
from lup_dev import cli
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import HostError, Limits, Refused, Register
from lup_dev.host.service import Dispatcher
from lup_dev.host.watch import Changes
from lup_dev.host.workers import (
    Called,
    HookJudged,
    JudgeCalling,
    JudgeHook,
    Worker,
    WorkerJudge,
    Workers,
    exchanged,
)
from lup_dev.layout import HostLayout
from lup_dev.policy.checkpoint import ConversationRecord
from lup_dev.policy.report import Quiet
from lup_dev.worker import routes

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from lup_dev.host.protocol import Reply
    from lup_dev.layout import Layout

PATIENCE = 60
"""How long a wait that should end at once may take before the test fails."""


@pytest.fixture
def short(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A socket's path is limited in length, so the test's directory is short.
    return tmp_path_factory.mktemp("w")


async def named(calling: JudgeCalling) -> Answer:
    """Run a call to the judge's own tools as a test does: by saying which tool, for which conversation and with what."""
    return Answer(
        text=f"{calling.name} for {calling.caller.id}: {json.dumps(calling.arguments)}"
    )


async def served(
    judge: Callable[[str, str], str], at: Path, said: list[str]
) -> asyncio.Server:
    """Serve the routes a repository's process serves, its modules unmade, judging with `judge` and running the judge's own tools with `named`, on `at`."""
    dispatcher = Dispatcher(
        routes={route.kind: route for route in routes(None, judge, named)},
        answering="a repository's process",
        say=said.append,
        changes=Changes(),
    )
    return await asyncio.start_unix_server(dispatcher.connection, path=at)


def test_a_repository_s_process_runs_the_judge_s_own_tools_for_the_conversation_calling(
    short: Path,
) -> None:
    calling = JudgeCalling(
        launch=registered(short, short / "lup-dev"),
        name="quiet",
        arguments={"kinds": ["importers"]},
        caller=Conversation(id="c1", session="s1", agent="a1"),
    )

    async def exercised() -> str:
        server = await served(lambda runtime, payload: "", short / "p.sock", [])
        try:
            return await exchanged(short / "p.sock", calling)
        finally:
            server.close()
            await server.wait_closed()

    reply = Called.model_validate_json(asyncio.run(exercised()))
    assert reply.answer == Answer(text='quiet for c1: {"kinds": ["importers"]}')


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


def registered(
    worktree: Path, judge: Path, launch: str = "one", repository: Path | None = None
) -> Register:
    return Register(
        launch=launch,
        runtime="claude",
        worktree=worktree,
        repository=repository or worktree / ".git",
        judge=judge,
        container=f"lup-{launch}",
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


def test_a_repository_s_process_answers_a_hook_as_the_hook_command_does(
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
        workers = Workers(
            layout=isolated, say=lambda line: None, approval=lambda repository: None
        )
        judge = WorkerJudge(modules=workers)
        try:
            await workers.open(launch)
            heard = [
                await judge.judged(launch, each) for each in [started, write("t2")]
            ]
            with pytest.raises(HostError, match="Invalid JSON"):
                await judge.judged(launch, "not a payload")
            return heard
        finally:
            await workers.stop()

    begun, wrote = asyncio.run(exercised())
    assert begun == ""
    assert wrote == printed.output
    assert json.loads(wrote)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_a_repository_s_process_runs_quiet_for_the_conversation_calling(
    repo: Path, isolated: HostLayout, state: Layout
) -> None:
    launch = registered(repo, Path(sys.executable).parent / "lup-dev")
    caller = Conversation(id="c1", session="s1", agent="a1")
    record = ConversationRecord(layout=state, session="s1")

    def quieting(*kinds: str) -> JudgeCalling:
        return JudgeCalling(
            launch=launch, name="quiet", arguments={"kinds": list(kinds)}, caller=caller
        )

    async def exercised() -> list[Reply]:
        workers = Workers(
            layout=isolated, say=lambda line: None, approval=lambda repository: None
        )
        try:
            await workers.open(launch)
            held = await workers.ask(launch, quieting("importers"))
            assert record.quiet("a1") == Quiet(kinds=["importers"])
            lifted = await workers.ask(launch, quieting())
            return [held, lifted]
        finally:
            await workers.stop()

    held, lifted = asyncio.run(exercised())
    assert isinstance(held, Called)
    assert held.answer.text.startswith(
        "This conversation is quiet: lup doesn't tell it type errors in the files "
        "importing what changed after its calls"
    )
    assert lifted == Called(
        answer=Answer(
            text=(
                "lup's quiet is lifted: it tells this conversation every finding "
                "after its calls again. Nothing stands in the files it touched that "
                "it wasn't told."
            )
        )
    )
    assert record.quiet("a1") == Quiet()


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

from lup.tools.serving import Answer
from lup_dev.worker import routes, serve

here = Path(__file__).parent


async def called(calling: object) -> Answer:
    return Answer(text=f"{{here.name}} runs no tool")


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


asyncio.run(
    serve(routes(None, judge, called), Path(sys.argv[2]), Path(sys.argv[3]), said)
)
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


class Approvals(dict[Path, str]):
    """What the operator approved last for each repository, by a fingerprint the test sets."""

    def of(self, repository: Path) -> str | None:
        return self.get(repository)


@asynccontextmanager
async def stand_ins(
    short: Path,
    isolated: HostLayout,
    said: list[str],
    idle: timedelta = timedelta(hours=1),
    approvals: Approvals | None = None,
) -> AsyncGenerator[tuple[Workers, Copies, Holds]]:
    """Workers starting stand-in copies, each repository's process running on for `idle` once nothing holds it, ended as the context closes."""
    copies = Copies(short)
    holds = Holds()
    copies.made("a")
    copies.made("b")
    copies.switch("a")
    workers = Workers(
        layout=isolated,
        say=said.append,
        approval=(approvals or Approvals()).of,
        idle=idle,
    )
    server = await asyncio.start_unix_server(holds.heard, path=short / "h.sock")
    try:
        yield workers, copies, holds
    finally:
        await holds.release()
        await workers.stop()
        server.close()
        await server.wait_closed()


def running(workers: Workers, launch: Register) -> Worker:
    """Return the process answering `launch`'s repository, which the test expects to run."""
    found = workers.processes(launch.repository).running
    assert found is not None
    return found


def test_launches_of_one_repository_share_its_process_and_another_s_has_its_own(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> None:
        async with stand_ins(short, isolated, said) as (workers, copies, _):
            one = registered(short, copies.command, "one")
            two = registered(short, copies.command, "two")
            other = registered(
                short, copies.command, "three", repository=short / "other.git"
            )
            judge = WorkerJudge(modules=workers)
            for each in [one, two, other]:
                await workers.open(each)
            assert await judge.judged(one, "x") == "a answers x"
            assert await judge.judged(two, "y") == "a answers y"
            assert await judge.judged(other, "z") == "a answers z"
            assert running(workers, one) is running(workers, two)
            assert running(workers, other) is not running(workers, one)
            assert len(workers.commands()) == 2

    asyncio.run(exercised())
    assert len([line for line in said if "its modules serve" in line]) == 2


def test_a_new_copy_takes_new_hooks_while_the_one_before_finishes_its_hold(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> list[str]:
        async with stand_ins(short, isolated, said) as (workers, copies, holds):
            launch = registered(short, copies.command)
            other = registered(short, copies.command, "two")
            judge = WorkerJudge(modules=workers)
            await workers.open(launch)
            await workers.open(other)
            assert await judge.judged(launch, "x") == "a answers x"
            first = running(workers, launch)
            held = asyncio.create_task(judge.judged(launch, "hold"))
            assert await holds.next() == "a"
            copies.switch("b")
            # The repository's next request, whichever launch's, reaches the new copy.
            after = await judge.judged(other, "y")
            # The process of `a` still answers the hold it was asked, and
            # nothing new reaches it.
            assert first.process.status is None
            assert sorted(each.parent.name for each in workers.commands()) == [
                "a",
                "b",
            ]
            await holds.release()
            answered = await asyncio.wait_for(held, timeout=PATIENCE)
            await asyncio.wait_for(asyncio.gather(*workers.retiring), PATIENCE)
            assert first.process.status is not None
            assert not first.socket.exists()
            assert [each.parent.name for each in workers.commands()] == ["b"]
            again = await judge.judged(launch, "z")
            return [after, answered, again]

    assert asyncio.run(exercised()) == ["b answers y", "a answers hold", "b answers z"]
    assert any(
        f"approved anew, its copy {short / 'b' / 'lup-dev'}" in line for line in said
    )
    assert any(
        f"its process from {short / 'a' / 'lup-dev'} has answered what it was asked"
        in line
        for line in said
    )


def test_an_approval_of_the_same_copy_switches_the_process_as_a_new_copy_does(
    short: Path, isolated: HostLayout
) -> None:
    """Approving the person's own layer alone installs no copy, but the
    declaration the modules are made from changed: a process of the approval
    answers from the next request, the one before finishing what it was asked."""
    approvals = Approvals({short / ".git": "before"})

    async def exercised() -> None:
        async with stand_ins(short, isolated, [], approvals=approvals) as (
            workers,
            copies,
            holds,
        ):
            launch = registered(short, copies.command)
            judge = WorkerJudge(modules=workers)
            await workers.open(launch)
            first = running(workers, launch)
            held = asyncio.create_task(judge.judged(launch, "hold"))
            assert await holds.next() == "a"
            approvals[short / ".git"] = "after"
            assert await judge.judged(launch, "y") == "a answers y"
            second = running(workers, launch)
            assert second is not first
            assert (first.approval, second.approval) == ("before", "after")
            assert first.process.status is None
            await holds.release()
            assert await asyncio.wait_for(held, PATIENCE) == "a answers hold"
            await asyncio.wait_for(asyncio.gather(*workers.retiring), PATIENCE)
            assert first.process.status is not None
            assert running(workers, launch) is second

    asyncio.run(exercised())


def test_a_repository_s_process_that_dies_fails_all_it_answers_and_starts_again(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> str:
        async with stand_ins(short, isolated, said) as (workers, copies, holds):
            launch = registered(short, copies.command)
            other = registered(short, copies.command, "two")
            judge = WorkerJudge(modules=workers)
            await workers.open(launch)
            await workers.open(other)
            dying = running(workers, launch)
            # Another launch's hook waits in the same process as it dies.
            held = asyncio.create_task(judge.judged(other, "hold"))
            assert await holds.next() == "a"
            with pytest.raises(HostError, match="ended before it answered"):
                await judge.judged(launch, "die")
            with pytest.raises(HostError, match="ended before it answered"):
                await asyncio.wait_for(held, PATIENCE)
            await asyncio.wait_for(dying.process.process.wait(), timeout=PATIENCE)
            again = await judge.judged(other, "x")
            assert running(workers, launch) is not dying
            assert not dying.socket.exists()
            return again

    assert asyncio.run(exercised()) == "a answers x"
    assert f"{short / '.git'}: its process is gone; starting it again" in said


def test_a_launch_s_end_lets_go_and_the_last_one_s_ends_the_process_once_idle(
    short: Path, isolated: HostLayout
) -> None:
    said: list[str] = []

    async def exercised() -> None:
        async with stand_ins(short, isolated, said, idle=timedelta(0)) as (
            workers,
            copies,
            _,
        ):
            one = registered(short, copies.command, "one")
            two = registered(short, copies.command, "two")
            judge = WorkerJudge(modules=workers)
            await workers.open(one)
            await workers.open(two)
            assert await judge.judged(one, "x") == "a answers x"
            shared = running(workers, one)
            await workers.close(one)
            processes = workers.processes(one.repository)
            # Another launch holds it still: it runs on, and the ended launch's
            # request still on its way starts nothing.
            assert processes.stopping is None
            with pytest.raises(HostError, match="launch one has ended"):
                await judge.judged(one, "late")
            assert await judge.judged(two, "y") == "a answers y"
            assert running(workers, two) is shared
            await workers.close(two)
            stopping = processes.stopping
            assert stopping is not None
            await asyncio.wait_for(stopping, PATIENCE)
            assert shared.process.status is not None
            assert not shared.socket.exists()
            assert workers.commands() == []
            # A launch opening afterwards starts it again.
            three = registered(short, copies.command, "three")
            await workers.open(three)
            assert await judge.judged(three, "z") == "a answers z"
            assert running(workers, three) is not shared

    asyncio.run(exercised())
    assert (
        f"{short / '.git'}: nothing has held its process for 0:00:00, so it ended"
        in said
    )


def test_a_hold_taken_while_the_process_idles_keeps_it_running(
    short: Path, isolated: HostLayout
) -> None:
    async def exercised() -> None:
        async with stand_ins(short, isolated, []) as (workers, copies, _):
            one = registered(short, copies.command, "one")
            judge = WorkerJudge(modules=workers)
            await workers.open(one)
            assert await judge.judged(one, "x") == "a answers x"
            warm = running(workers, one)
            await workers.close(one)
            stopping = workers.processes(one.repository).stopping
            assert stopping is not None
            two = registered(short, copies.command, "two")
            await workers.open(two)
            await asyncio.wait([stopping], timeout=PATIENCE)
            assert stopping.cancelled()
            assert await judge.judged(two, "y") == "a answers y"
            assert running(workers, two) is warm
            assert warm.process.status is None

    asyncio.run(exercised())


def test_the_last_launch_ending_ends_its_processes_once_idle_a_replaced_one_holding_among_them(
    short: Path, isolated: HostLayout
) -> None:
    async def exercised() -> None:
        async with stand_ins(short, isolated, [], idle=timedelta(0)) as (
            workers,
            copies,
            holds,
        ):
            launch = registered(short, copies.command)
            judge = WorkerJudge(modules=workers)
            await workers.open(launch)
            held = asyncio.create_task(judge.judged(launch, "hold"))
            assert await holds.next() == "a"
            first = running(workers, launch)
            copies.switch("b")
            assert await judge.judged(launch, "y") == "b answers y"
            second = running(workers, launch)
            await workers.close(launch)
            stopping = workers.processes(launch.repository).stopping
            assert stopping is not None
            await asyncio.wait_for(stopping, PATIENCE)
            assert first.process.status is not None
            assert second.process.status is not None
            assert workers.commands() == []
            assert not list(isolated.processes.iterdir())
            with pytest.raises(HostError):
                await asyncio.wait_for(held, timeout=PATIENCE)
            # A hook still on its way as the launch ends starts no process.
            with pytest.raises(HostError, match="launch one has ended"):
                await judge.judged(launch, "late")
            assert workers.commands() == []

    asyncio.run(exercised())


def test_stopping_ends_every_repository_s_process_whatever_holds_it(
    short: Path, isolated: HostLayout
) -> None:
    async def exercised() -> None:
        async with stand_ins(short, isolated, []) as (workers, copies, _):
            one = registered(short, copies.command, "one")
            other = registered(
                short, copies.command, "two", repository=short / "other.git"
            )
            judge = WorkerJudge(modules=workers)
            for each in [one, other]:
                await workers.open(each)
                await judge.judged(each, "x")
            started = [running(workers, each) for each in [one, other]]
            await workers.stop()
            assert all(each.process.status is not None for each in started)
            assert workers.commands() == []
            assert not list(isolated.processes.iterdir())
            with pytest.raises(HostError, match="launch one has ended"):
                await judge.judged(one, "late")

    asyncio.run(exercised())
