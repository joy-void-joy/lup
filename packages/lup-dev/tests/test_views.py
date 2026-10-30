"""A module's view as the dashboard asks the host for it: answered by its repository's process, held while it's watched, and answered again at its own triggers alone.

The first tests drive the host's view route in this process, over a stand-in
for the repositories' processes that answers what the test sets and records
each asking, so which change answers a view again is seen by counting. The last
start a real host service and a repository's process from a stand-in copy of
`lup-dev`, serving a module whose view reads a file the test writes, and watch
it through the service's sockets as the dashboard does. Nothing sleeps: a watch
is read line by line, each line waited for.
"""

import asyncio
import json
import socket
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from lup import events
from lup.blocks import Blocks, Line, OfAgent
from lup_dev.host.client import Detached, HostClient
from lup_dev.host.courier import Courier, Heard, Telling
from lup_dev.host.protocol import (
    HostError,
    Limits,
    Listed,
    ListLaunches,
    Looks,
    Refused,
    Register,
    Reply,
    Request,
    Stop,
)
from lup_dev.host.service import Answerer, HostService, Route
from lup_dev.host.views import ModuleViews
from lup_dev.host.watch import Changes, Remarked, Touched
from lup_dev.host.workers import (
    Holder,
    RepositoryAsking,
    Viewed,
    Viewing,
    Watching,
    WorkerJudge,
    Workers,
    WorkersAsking,
)
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator
    from contextlib import AbstractAsyncContextManager

    from conftest import FakeClock

    from lup_dev.layout import Layout

PATIENCE = 60
"""How long a wait that should end at once may take before the test fails."""

REPOSITORY = Path("/r/.git")
AGENT = OfAgent(runtime="claude", session="s1", agent="a1")


def viewing(launch: Register | None = None) -> Viewing:
    return Viewing(
        repository=REPOSITORY,
        module="shown",
        view="said",
        argument=AGENT.model_dump(mode="json"),
        launch=launch,
    )


def touched(by: str, of: OfAgent = AGENT, repository: Path = REPOSITORY) -> Touched:
    return Touched(
        repository=repository,
        runtime=of.runtime,
        session=of.session,
        agent=of.agent,
        by=by,
    )


class Asked(RepositoryAsking):
    """Answers each view with the text the test sets, counting each asking, and records each watch's hold."""

    def __init__(self, watch: Watching) -> None:
        self.watch = watch
        self.text = "zero"
        self.count = 0
        self.held: list[str] = []
        self.approved = True

    @override
    async def asked(self, repository: Path, request: Request) -> Reply:
        self.count += 1
        blocks = Blocks(blocks=[Line.of("1", self.text)])
        return Viewed(blocks=blocks, watch=self.watch)

    @override
    def watching(self, repository: Path) -> AbstractAsyncContextManager[None]:
        return self.holding(repository)

    @asynccontextmanager
    async def holding(self, repository: Path) -> AsyncGenerator[None]:
        if not self.approved:
            message = f"nothing is approved for {repository}"
            raise HostError(message)
        self.held.append(f"held {repository}")
        try:
            yield
        finally:
            self.held.append(f"let go {repository}")

    @override
    def looks(self) -> dict[Path, Looks]:
        return {}


def views(
    asked: Asked, changes: Changes, said: list[str], clock: FakeClock
) -> ModuleViews:
    return ModuleViews(asking=asked, changes=changes, say=said.append, clock=clock)


async def settled() -> None:
    """Let every task the loop has ready run until none is left ready."""
    for _ in range(20):
        await asyncio.sleep(0)


def texts(reply: Reply) -> str:
    assert isinstance(reply, Viewed)
    return reply.blocks.text()


def test_a_watched_view_is_answered_again_at_its_agent_s_events_it_names_and_its_items_alone(
    clock: FakeClock,
) -> None:
    asked = Asked(Watching(of=AGENT, on=["call-finished"]))
    changes = Changes()

    async def exercised() -> list[tuple[str, int]]:
        watched = views(asked, changes, [], clock).watched(viewing())
        seen = [(texts(await anext(watched)), asked.count)]
        coming = asyncio.ensure_future(anext(watched))
        asked.text = "one"
        # Another agent's event, this agent's event its view doesn't name, and
        # another repository's conversation of the same ids: none answers it.
        changes.changed(
            [touched("call-finished", OfAgent(runtime="claude", session="s1"))]
        )
        changes.changed([touched("call-started")])
        changes.changed([touched("call-finished", repository=Path("/other/.git"))])
        changes.changed()
        await settled()
        assert not coming.done()
        changes.changed([touched("call-finished")])
        seen.append((texts(await asyncio.wait_for(coming, PATIENCE)), asked.count))
        asked.text = "two"
        coming = asyncio.ensure_future(anext(watched))
        changes.changed([touched("item")])
        seen.append((texts(await asyncio.wait_for(coming, PATIENCE)), asked.count))
        await watched.aclose()
        return seen

    assert asyncio.run(exercised()) == [("zero", 1), ("one", 2), ("two", 3)]
    assert asked.held == [f"held {REPOSITORY}", f"let go {REPOSITORY}"]


def test_a_watched_view_is_answered_again_as_a_review_mark_it_read_moves_alone(
    clock: FakeClock,
) -> None:
    read = Remarked(repository=REPOSITORY, module="shown", key='{"session":"s1"}')
    asked = Asked(Watching(marks=[read]))
    changes = Changes()

    async def exercised() -> list[str]:
        watched = views(asked, changes, [], clock).watched(viewing())
        seen = [texts(await anext(watched))]
        coming = asyncio.ensure_future(anext(watched))
        asked.text = "moved"
        # Another key of the module's, another module's mark of the same key, and
        # the same mark of another repository: none answers it.
        changes.changed([read.model_copy(update={"key": '{"session":"s2"}'})])
        changes.changed([read.model_copy(update={"module": "other"})])
        changes.changed([read.model_copy(update={"repository": Path("/other/.git")})])
        await settled()
        assert not coming.done()
        changes.changed([read])
        seen.append(texts(await asyncio.wait_for(coming, PATIENCE)))
        await watched.aclose()
        return seen

    assert asyncio.run(exercised()) == ["zero", "moved"]


def test_a_change_while_a_view_is_answered_answers_it_again_after(
    clock: FakeClock,
) -> None:
    asked = Asked(Watching(of=AGENT, on=["call-finished"]))
    changes = Changes()

    async def exercised() -> int:
        watched = views(asked, changes, [], clock).watched(viewing())
        await anext(watched)
        # The event came after the count the answer was asked at was taken.
        changes.changed([touched("call-finished")])
        await asyncio.wait_for(anext(watched), PATIENCE)
        await watched.aclose()
        return asked.count

    assert asyncio.run(exercised()) == 2


def test_a_view_is_answered_again_at_its_longest_wait_whatever_changes(
    clock: FakeClock,
) -> None:
    asked = Asked(Watching(longest=timedelta(0)))

    async def exercised() -> int:
        watched = views(asked, Changes(), [], clock).watched(viewing())
        await anext(watched)
        await asyncio.wait_for(anext(watched), PATIENCE)
        await watched.aclose()
        return asked.count

    assert asyncio.run(exercised()) == 2


def test_a_view_of_no_agent_with_no_longest_wait_is_answered_once(
    clock: FakeClock,
) -> None:
    asked = Asked(Watching())
    changes = Changes()

    async def exercised() -> int:
        watched = views(asked, changes, [], clock).watched(viewing())
        await anext(watched)
        coming = asyncio.ensure_future(anext(watched))
        changes.changed([touched("item"), touched("call-finished")])
        await settled()
        assert not coming.done()
        coming.cancel()
        await asyncio.wait([coming])
        return asked.count

    assert asyncio.run(exercised()) == 1
    assert asked.held == [f"held {REPOSITORY}", f"let go {REPOSITORY}"]


def test_a_view_is_the_operator_s_a_room_s_asking_refused(clock: FakeClock) -> None:
    route = views(Asked(Watching()), Changes(), [], clock)
    room = Register(
        launch="one",
        runtime="claude",
        worktree=Path("/r"),
        repository=REPOSITORY,
        judge=Path("/judge"),
        limits=Limits(actions=[], protected=[]),
        github=None,
    )
    with pytest.raises(HostError, match="operator's, asked with no launch"):
        asyncio.run(route.answer(viewing(room)))
    with pytest.raises(HostError, match="a room reads one with its module's command"):
        asyncio.run(route.scoped(viewing(), REPOSITORY))


def test_a_view_of_a_repository_nothing_is_approved_for_isn_t_watched(
    clock: FakeClock,
) -> None:
    asked = Asked(Watching())
    asked.approved = False

    async def exercised() -> None:
        await anext(views(asked, Changes(), [], clock).watched(viewing()))

    with pytest.raises(HostError, match="nothing is approved"):
        asyncio.run(exercised())
    assert asked.count == 0


def test_an_answer_past_the_size_said_is_said_in_the_service_s_output(
    clock: FakeClock,
) -> None:
    said: list[str] = []
    asked = Asked(Watching())
    small = views(asked, Changes(), said, clock)
    asyncio.run(small.answer(viewing()))
    assert said == []
    large = small.model_copy(update={"large": 10})
    asyncio.run(large.answer(viewing()))
    [line] = said
    assert line.startswith(f"{REPOSITORY}: `shown`'s view `said` answered ")
    assert line.endswith("past 10 bytes or 1 s: each answer that differs is sent whole")


def test_a_watch_holds_the_repository_s_process_while_it_s_open(
    isolated: HostLayout, short: Path
) -> None:
    command = short / "lup-dev"

    async def exercised() -> tuple[list[Holder], list[Holder]]:
        workers = Workers(
            layout=isolated,
            say=lambda line: None,
            approval=lambda repository: None,
            approved=lambda repository: command,
        )
        async with workers.watching(REPOSITORY):
            during = workers.processes(REPOSITORY).holders
        after = workers.processes(REPOSITORY).holders
        await workers.stop()
        return during, after

    during, after = asyncio.run(exercised())
    assert [each.what for each in during] == ["watch"]
    assert after == []


def test_nothing_approved_holds_no_watch(isolated: HostLayout) -> None:
    workers = Workers(
        layout=isolated,
        say=lambda line: None,
        approval=lambda repository: None,
        approved=lambda repository: None,
    )

    async def exercised() -> None:
        async with workers.watching(REPOSITORY):
            pass

    with pytest.raises(HostError, match="nothing is approved"):
        asyncio.run(exercised())


# Through a real host service: a stand-in copy of `lup-dev` whose repository's
# process serves one module, `shown`, its drawer view `said` showing what the
# test last wrote to a file and answered again as the agent's call finishes.
STAND_IN = """#!{python}
import asyncio
import sys
from pathlib import Path

import lup
from lup.tools.serving import Answer
from lup_dev import Core, Module, Modules, ModuleServing, Project, Serving
from lup_dev.declaration.resolve import resolve
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarkStore, StoredMarks
from lup_dev.inbox.protocol import Exchanged
from lup_dev.layout import Layout
from lup_dev.worker import RepositoryModules, routes, serve


class SaidServing(ModuleServing):
    \"\"\"What the test said, as a view.\"\"\"

    module: Shown

    @lup.view(
        place=lup.Drawer(letter="g", called="what's said", colour="cyan"),
        watch=lup.Watch(on=[lup.CallFinished]),
    )
    async def said(self, viewed: lup.OfAgent) -> lup.Blocks:
        \"\"\"What the test wrote last.\"\"\"
        text = Path({said!r}).read_text()
        return lup.Blocks(blocks=[lup.Line.of("1", f"{{viewed.agent}}: {{text}}")])


class Shown(Module):
    \"\"\"Shows what the test said.\"\"\"

    name = "shown"
    serving: Serving = Serving.of(SaidServing)


class Unexchanged(Exchanges):
    async def exchanged(self, viewed: lup.OfAgent) -> Exchanged:
        return Exchanged(sent=[], received=[])


async def called(calling: object) -> Answer:
    return Answer(text="no tool")


def judge(runtime: str, payload: str, environments: object) -> str:
    return ""


def said(line: str) -> None:
    sys.stderr.write(f"{{line}}\\n")


modules = RepositoryModules(
    repository=Path(sys.argv[3]),
    resolved=resolve(Project(modules=Modules.only(Core(), Shown()))),
    recorded={{}},
    layout=Layout(state=Path({data!r}), data=Path({data!r})),
    exchanges=Unexchanged(),
    marks=StoredMarks(store=MarkStore.kept_in(Layout(state=Path({data!r}), data=Path({data!r})))),
)
asyncio.run(
    serve(routes(modules, judge, called), Path(sys.argv[2]), Path(sys.argv[3]), said)
)
"""


class Unanswered(Answerer):
    def runtimes(self) -> list[str]:
        return ["claude"]

    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        return failure


class Reads(Courier):
    """Hears each payload as the `Heard` it is, and adds nothing."""

    def heard(self, runtime: str, payload: str) -> Heard:
        return Heard.model_validate_json(payload)

    def told(self, runtime: str, payload: str, answer: str, telling: Telling) -> str:
        return answer


def hook(event: events.SessionEvent, agent: str = "a1") -> str:
    """A hook of subagent `agent` of session `s1`, which the judge doesn't read."""
    heard = {"event": event.model_dump(), "session": "s1", "agent": agent}
    return json.dumps({**heard, "judged": False, "fits": 10_000})


def sent(path: Path, payload: str) -> str:
    """Send `payload` on the socket at `path`, its end marked, and read the answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(PATIENCE)
        connection.connect(str(path))
        connection.sendall(payload.encode())
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as stream:
            return stream.read().decode()


@contextmanager
def watched(layout: HostLayout, request: Request) -> Generator[Callable[[], str]]:
    """Watch `request` on the service's watch socket: each call reads its next reply's line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(PATIENCE)
        connection.connect(str(layout.watch))
        connection.sendall(f"{request.model_dump_json()}\n".encode())
        with connection.makefile("rb") as stream:
            yield lambda: stream.readline().decode()


class Hosted:
    """A host service on its own event loop in a thread, its repositories' processes started from the stand-in copy."""

    def __init__(self, layout: HostLayout, command: Path, said: list[str]) -> None:
        workers = Workers(
            layout=layout,
            say=said.append,
            approval=lambda repository: None,
            approved=lambda repository: command,
        )
        self.workers = workers
        asking = WorkersAsking(workers=workers)
        changes = Changes()
        route = ModuleViews(asking=asking, changes=changes, say=said.append)
        self.service = HostService(
            layout=layout,
            answerer=Unanswered(),
            courier=Reads(),
            judge=WorkerJudge(modules=workers),
            say=said.append,
            routes=[Route.reading(route, watch=route.watched)],
            modules=workers,
            asking=asking,
            changes=changes,
        )
        self.bound = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        async def serve() -> None:
            async with self.service.serving() as serving:
                self.bound.set()
                await serving.stopped.wait()

        try:
            asyncio.run(serve())
        finally:
            self.bound.set()

    @contextmanager
    def serving(self) -> Generator[Hosted]:
        self.thread.start()
        self.bound.wait(PATIENCE)
        try:
            yield self
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the service where it still serves, and wait for its thread."""
        if self.thread.is_alive():
            sent(self.service.layout.control, Stop().model_dump_json())
        self.thread.join(timeout=PATIENCE)
        assert not self.thread.is_alive()


@pytest.fixture
def short(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A socket's path is limited in length, so the test's directory is short.
    return tmp_path_factory.mktemp("v")


@pytest.fixture
def isolated(state: Layout, short: Path, monkeypatch: pytest.MonkeyPatch) -> HostLayout:
    """The host's layout, short enough for its sockets, with lup's state under the test's directories: no process the test starts reaches the operator's own host service."""
    del state
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short / "run"))
    host = HostLayout(sockets=short / "host", state=short / "state")
    host.launches.mkdir(parents=True)
    return host


def copy(short: Path) -> tuple[Path, Path]:
    """Make the stand-in copy under `short`, and return its command and the file its view reads."""
    said = short / "said.txt"
    said.write_text("hello")
    command = short / "copy" / "lup-dev"
    command.parent.mkdir()
    command.write_text(
        STAND_IN.format(python=sys.executable, said=str(said), data=str(short / "data"))
    )
    command.chmod(0o755)
    return command, said


def registered(short: Path, judge: Path) -> Register:
    return Register(
        launch="one",
        runtime="claude",
        worktree=short,
        repository=short / ".git",
        judge=judge,
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
        name="one",
    )


def test_the_dashboard_s_view_is_asked_through_the_host_and_answered_again_as_its_agent_s_call_finishes(
    isolated: HostLayout, short: Path, clock: FakeClock
) -> None:
    command, said = copy(short)
    repository = short / ".git"
    asked = Viewing(
        repository=repository,
        module="shown",
        view="said",
        argument=AGENT.model_dump(mode="json"),
    )
    host = HostClient(layout=isolated, clock=clock, starter=Detached())
    logged: list[str] = []
    with Hosted(isolated, command, logged).serving():
        host.register(registered(short, command))
        once = Viewed.model_validate_json(
            sent(isolated.control, asked.model_dump_json())
        )
        listed = host.ask(ListLaunches(), Listed)
        room = sent(isolated.launch("one").request, asked.model_dump_json())
        hooks = isolated.launch("one").hook
        with watched(isolated, asked) as following:
            first = Viewed.model_validate_json(following())
            said.write_text("goodbye")
            # The call's start isn't among the events the view names, and
            # another agent's call isn't its agent's: neither answers it again,
            # so the next line is the one its own call's finish brings.
            sent(hooks, hook(events.CallStarted(call="c1", tool="Bash")))
            sent(hooks, hook(events.CallFinished(call="c2", tool="Bash"), agent="a2"))
            said.write_text("again")
            sent(hooks, hook(events.CallFinished(call="c1", tool="Bash")))
            second = Viewed.model_validate_json(following())
    assert once.blocks.text() == "a1: hello"
    assert once.watch == Watching(of=AGENT, on=["call-finished"])
    assert [each.view for each in listed.looks[repository].drawers] == [
        "tasks",
        "since",
        "said",
    ]
    assert "the operator's" in Refused.model_validate_json(room).error
    assert first.blocks.text() == "a1: hello"
    assert second.blocks.text() == "a1: again"


def test_a_view_watched_as_the_service_stops_ends_with_it(
    isolated: HostLayout, short: Path, clock: FakeClock
) -> None:
    command, _ = copy(short)
    asked = Viewing(
        repository=short / ".git",
        module="shown",
        view="said",
        argument=AGENT.model_dump(mode="json"),
    )
    host = HostClient(layout=isolated, clock=clock, starter=Detached())
    logged: list[str] = []
    hosted = Hosted(isolated, command, logged)
    with hosted.serving():
        host.register(registered(short, command))
        with watched(isolated, asked) as following:
            first = Viewed.model_validate_json(following())
            hosted.stop()
            end = following()
    assert first.blocks.text() == "a1: hello"
    assert end == ""
    assert not [line for line in logged if "failed" in line]
