"""A module's methods, behind the library's doors: declared, checked, resolved, and served by the repository's process.

The modules here are small: `Echo`, whose one tool shouts what it's told and whose
request answers `ping`. Some tests start the real `lup-dev worker` process on a
repository whose declaration holds such a module, and talk to it as the host
service does.
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from pydantic import Field
from typer.testing import CliRunner

import lup
from lup.blocks import SHELL_FOLDS
from lup.programs import run
from lup.publishing import Part, Place, Post, Refusal
from lup.types import Model
from lup_dev import (
    Agent,
    Core,
    Lup,
    Module,
    Modules,
    ModuleServing,
    Project,
    ProjectError,
    Room,
    Serving,
    commanding,
)
from lup_dev.approval import Approval, ReleaseTool
from lup_dev.cli import module_command
from lup_dev.declaration.kinds import Folds, Mounted, Tones, Verbs
from lup_dev.declaration.looks import CORE_LOOKS
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import Operator
from lup_dev.errors import LupDevError
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Limits, Register, Reply, Request
from lup_dev.host.records import Call as RecordedCall
from lup_dev.host.records import Reader as RecordsReader
from lup_dev.host.records import Record, Recorded, Records, Transcript
from lup_dev.host.watch import Remarked
from lup_dev.host.workers import (
    Called,
    Calling,
    Happening,
    Sent,
    Viewing,
    Watching,
    Workers,
)
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarkStore, ReviewMark, StoredMarks
from lup_dev.inbox.protocol import Exchanged
from lup_dev.layout import HostLayout, Layout
from lup_dev.stored import write_model
from lup_dev.worker import RepositoryModules

if TYPE_CHECKING:
    from conftest import FakeClock, Kit

    from lup.blocks import OfAgent
    from lup_dev.host.homes import Found

CALLER = Conversation(id="c1", session="s1")


class Nothing(Records):
    """A runtime that keeps no records."""

    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        return []

    def held(self, session: str) -> bool:
        return False

    def conversation(self, session: str, agent: str | None) -> Found | None:
        return None


class Unread(RecordsReader):
    """A runtime whose copies hold no session to read."""

    def sessions(self, copies: Path) -> list[Path]:
        del copies
        return []

    def read(self, record: Path, root: Path | None = None) -> Transcript:
        message = f"no session is kept at {record}"
        raise FileNotFoundError(message)

    def calls(
        self, record: Path, ids: list[str], root: Path | None = None
    ) -> list[RecordedCall]:
        del record, ids
        return []


class Unexchanged(Exchanges):
    """An inbox where no conversation exchanged any item."""

    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        del viewed
        return Exchanged(sent=[], received=[])


class Said(Model):
    """What to shout."""

    text: str


class Ping(Request, reads=True):
    """Ask the module to answer."""

    kind: Literal["ping"] = "ping"
    text: str


class Pong(Reply):
    """The module's answer."""

    kind: Literal["pong"] = "pong"
    text: str


class EchoServing(ModuleServing):
    """Echo's tools, and its answer to `ping`."""

    module: Echo

    @lup.tool
    async def shout(self, said: Said, by: Agent) -> str:
        """Shout what you're told."""
        loud = said.text.upper() * self.module.volume
        return f"{loud}, for {by.conversation.id} of {by.launch.launch}"

    @lup.tool
    async def fail(self, said: Said) -> str:
        """Fail, saying why."""
        message = f"it can't: {said.text}"
        raise LupDevError(message)

    @lup.request
    async def ping(self, asked: Ping, by: Room) -> Pong:
        """Answer `ping`, as many times as the module's volume."""
        return Pong(text=f"{asked.text * self.module.volume} to {by.launch.launch}")


class Echo(Module):
    """Shouting what it's told."""

    name = "echo"

    volume: int = 1
    serving: Serving = Serving.of(EchoServing)


class OtherServing(ModuleServing):
    """Another module's tool of the same name."""

    module: Other

    @lup.tool
    async def shout(self, said: Said) -> str:
        """Shout too."""
        return said.text


class Other(Module):
    """Shouting too."""

    name = "other"

    serving: Serving = Serving.of(OtherServing)


class Borrowing(Module):
    """Listing another module's methods as its own."""

    name = "borrowing"

    serving: Serving = Serving.of(EchoServing)


def launch(tmp_path: Path) -> Register:
    judge = tmp_path / "judge"
    judge.touch()
    return Register(
        launch="one",
        runtime="claude",
        worktree=tmp_path,
        repository=tmp_path / ".git",
        judge=judge,
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
    )


def test_a_module_s_classes_resolve_with_their_module() -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Echo(volume=2))))
    [served] = resolved.served
    assert served.serving is EchoServing
    assert isinstance(served.module, Echo)
    assert served.module.volume == 2


def test_lup_s_defaults_serve_their_methods_until_dropped() -> None:
    names = [each.serving.__name__ for each in resolve(Project()).served]
    assert names == ["GitHubServing", "TranscriptsServing", "PrivateServing"]
    dropped = Project(modules=Modules.default().drop("github"))
    served = [each.module.name for each in resolve(dropped).served]
    assert served == ["transcripts", "private"]


def test_a_class_of_methods_is_dropped_by_its_name() -> None:
    quiet = Echo(serving=Serving().drop("EchoServing"))
    resolved = resolve(Project(modules=Modules.only(Core(), quiet)))
    assert resolved.served == []


def test_a_tool_named_alike_by_two_modules_is_refused_naming_both() -> None:
    with pytest.raises(ProjectError, match=r"`shout` from `echo` and `other`"):
        resolve(Project(modules=Modules.only(Core(), Echo(), Other())))


def test_methods_made_with_another_module_are_refused() -> None:
    with pytest.raises(ProjectError, match=r"`EchoServing` in `borrowing` narrows"):
        resolve(Project(modules=Modules.only(Core(), Borrowing())))


def serving(tmp_path: Path, volume: int = 1) -> RepositoryModules:
    resolved = resolve(Project(modules=Modules.only(Core(), Echo(volume=volume))))
    return RepositoryModules(
        repository=tmp_path / ".git",
        resolved=resolved,
        recorded={"claude": Recorded(records=Nothing(), reader=Unread())},
        layout=Layout(state=tmp_path, data=tmp_path),
        exchanges=Unexchanged(),
        marks=StoredMarks(layout=Layout(state=tmp_path, data=tmp_path)),
    )


def test_a_repository_s_modules_offer_their_tools_and_kinds(tmp_path: Path) -> None:
    offered = serving(tmp_path).offered()
    assert [spec.name for spec in offered.tools] == ["shout", "fail"]
    assert offered.kinds == ["ping"]


def test_a_call_is_made_with_its_module_the_launch_and_the_caller(
    tmp_path: Path,
) -> None:
    one = launch(tmp_path)
    two = one.model_copy(update={"launch": "two"})
    served = serving(tmp_path, volume=2)

    def shouted(registered: Register) -> str:
        calling = Calling(
            launch=registered, name="shout", arguments={"text": "hi"}, caller=CALLER
        )
        answer = asyncio.run(served.call(calling))
        assert not answer.error
        return answer.text

    # One repository's modules serve each of its launches, each call made with
    # the launch it carries.
    assert [shouted(one), shouted(two)] == [
        "HIHI, for c1 of one",
        "HIHI, for c1 of two",
    ]


def test_a_tool_that_can_t_says_why(tmp_path: Path) -> None:
    calling = Calling(
        launch=launch(tmp_path), name="fail", arguments={"text": "no"}, caller=CALLER
    )
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text == "`fail` didn't run: it can't: no"
    assert answer.error


def test_arguments_the_tool_doesn_t_take_are_refused(tmp_path: Path) -> None:
    calling = Calling(
        launch=launch(tmp_path), name="shout", arguments={"words": "hi"}, caller=CALLER
    )
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text.startswith("`shout` refused the call:")
    assert answer.error


def test_a_tool_no_module_serves_is_said(tmp_path: Path) -> None:
    calling = Calling(
        launch=launch(tmp_path), name="whisper", arguments={}, caller=CALLER
    )
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text == "no module of this launch serves `whisper`"


def test_a_room_s_request_is_answered_by_its_module_s_method_for_its_launch(
    tmp_path: Path,
) -> None:
    sent = Sent.model_validate({"kind": "ping", "text": "a"})
    served = serving(tmp_path, volume=3)
    one = launch(tmp_path)
    two = one.model_copy(update={"launch": "two"})
    answered = [
        asyncio.run(served.answer(sent, Room(launch=each))) for each in [one, two]
    ]
    assert answered == [Pong(text="aaa to one"), Pong(text="aaa to two")]


def test_a_method_answers_only_who_it_s_for(tmp_path: Path) -> None:
    sent = Sent.model_validate({"kind": "ping", "text": "a"})
    agent = Agent(launch=launch(tmp_path), conversation=CALLER)
    with pytest.raises(
        LupDevError,
        match=r"`EchoServing.ping` of `Echo` is asked by `Room`, never by `Agent`",
    ):
        asyncio.run(serving(tmp_path).answer(sent, agent))


def test_a_tool_leaving_by_out_is_its_door_s_default_askers(tmp_path: Path) -> None:
    calling = Calling(
        launch=launch(tmp_path), name="fail", arguments={"text": "x"}, caller=CALLER
    )
    # `fail` leaves `by` out: a tool's default askers, an agent, call it.
    assert asyncio.run(serving(tmp_path).call(calling)).text == (
        "`fail` didn't run: it can't: x"
    )


def test_who_may_ask_a_method_is_checked_as_its_class_is_defined() -> None:
    def roomy() -> type[ModuleServing]:
        class Roomy(ModuleServing):
            """A tool for a room, which never calls one."""

            module: Echo

            @lup.tool
            async def shout(self, said: Said, by: Room) -> str:
                """Shout."""
                return said.text

        return Roomy

    def nobody() -> type[ModuleServing]:
        class Nobody(ModuleServing):
            """A request that doesn't say who may ask it."""

            module: Echo

            @lup.request
            async def ping(self, asked: Ping) -> Pong:
                """Answer."""
                return Pong(text=asked.text)

        return Nobody

    def widened() -> type[ModuleServing]:
        class Widened(ModuleServing):
            """A tool naming an asker beside the one that calls it."""

            module: Echo

            @lup.tool
            async def shout(self, said: Said, by: Agent | Room) -> str:
                """Shout."""
                return said.text

        return Widened

    def stray() -> type[ModuleServing]:
        class Stray(ModuleServing):
            """A request taking a model that isn't a request's."""

            module: Echo

            @lup.request
            async def ping(self, asked: Said, by: Room) -> Pong:
                """Answer."""
                return Pong(text=asked.text)

        return Stray

    with pytest.raises(
        ProjectError,
        match=r"`Roomy.shout` takes `by: Room`, but a tool is asked by `Agent` alone",
    ):
        roomy()
    with pytest.raises(
        ProjectError, match=r"`Nobody.ping` is a request, which says who may ask it"
    ):
        nobody()
    with pytest.raises(ProjectError, match=r"never by `Room`"):
        widened()
    with pytest.raises(ProjectError, match=r"`Stray.ping` is a request, so it takes"):
        stray()


DECLARATION = '''"""A project with a module of its own."""

import lup
from lup.types import Model
from lup_dev import Module, Modules, ModuleServing, Project, Serving


class Said(Model):
    """What to shout."""

    text: str


class LoudServing(ModuleServing):
    """Loud's tool."""

    module: Loud

    @lup.tool
    async def shout(self, said: Said) -> str:
        """Shout what you're told."""
        return f"{said.text.upper()} from {self.module.name}"


class Loud(Module):
    """Shouting."""

    name = "loud"

    serving: Serving = Serving.of(LoudServing)


project = Project(modules=Modules.default().add(Loud()))
'''


@pytest.fixture
def host(tmp_path_factory: pytest.TempPathFactory) -> HostLayout:
    # A socket's path is limited in length, so the service's directory is short.
    base = tmp_path_factory.mktemp("host")
    return HostLayout(sockets=base / "run", state=base / "state")


def test_a_repository_s_process_serves_its_committed_declaration_s_modules(
    repo: Path, state: object, host: HostLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(DECLARATION)
    run("git", "add", "-A", cwd=repo)
    run("git", "commit", "-q", "-m", "a module of its own", cwd=repo)
    host.launches.mkdir(parents=True)
    # The worktree's own copy changes after the commit: the process reads the commit.
    (repo / "lup_project.py").write_text("raise SystemExit('not this one')\n")
    bin_directory = Path(sys.executable).parent
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}")
    registered = launch(repo).model_copy(
        update={"judge": Path(sys.executable).parent / "lup-dev"}
    )
    said: list[str] = []

    async def exercised() -> tuple[list[str], Called, Called, bool]:
        workers = Workers(
            layout=host,
            say=said.append,
            approval=lambda repository: None,
            approved=lambda repository: None,
        )
        offered = await workers.open(registered)
        calling = Calling(
            launch=registered, name="shout", arguments={"text": "hi"}, caller=CALLER
        )
        first = await workers.ask(registered, calling)
        processes = workers.processes(registered.repository)
        assert processes.running is not None
        process = processes.running.process.process
        process.kill()
        await process.wait()
        again = await workers.ask(registered, calling)
        await workers.close(registered)
        await workers.stop()
        gone = workers.commands() == []
        assert isinstance(first, Called)
        assert isinstance(again, Called)
        return [spec.name for spec in offered.tools], first, again, gone

    names, first, again, gone = asyncio.run(exercised())
    assert "shout" in names
    assert "read_issue" in names
    assert first.answer.text == "HI from loud"
    assert again.answer == first.answer
    assert gone
    assert not list(host.processes.iterdir())
    assert any("starting it again" in line for line in said)


LOCAL = '''"""The person's own layer: a module of theirs."""

import lup
from lup.types import Model
from lup_dev import Module, Modules, ModuleServing, Project, Serving


class Words(Model):
    """What to whisper."""

    text: str


class QuietServing(ModuleServing):
    """Quiet's tool."""

    module: Quiet

    @lup.tool
    async def whisper(self, words: Words) -> str:
        """Whisper what you're told."""
        return words.text.lower()


class Quiet(Module):
    """Whispering."""

    name = "quiet"

    serving: Serving = Serving.of(QuietServing)


project = Project(modules=Modules().add(Quiet()))
'''
"""The person's own layer, adding a module of theirs to the project's."""


def test_a_bare_repository_s_modules_are_made_from_its_approved_declaration(
    bare: Path, kit: Kit
) -> None:
    """lup's own layout: a bare repository, its worktrees under `tree/`. The
    process reads the commit the operator approved, with the person's layer
    approved beside it, never a worktree's own copy of either."""
    main = bare / "tree" / "main"
    (main / "lup_project.py").write_text(DECLARATION)
    run("git", "add", "-A", cwd=main)
    run("git", "commit", "-q", "-m", "a module of its own", cwd=main)
    commit = run("git", "rev-parse", "HEAD", cwd=main).text().strip()
    (main / "lup_project.py").write_text("raise SystemExit('not this one')\n")
    (main / "lup_project.local.py").write_text("raise SystemExit('nor this')\n")
    approval = Approval(
        commit=commit,
        fingerprint="approved",
        paths=[Path("lup_project.py")],
        tool=ReleaseTool(name="lup-dev", version="0.4.0", registry="index", pins={}),
        time=kit.clock.now(),
        local=LOCAL,
    )
    write_model(kit.layout.approved(bare), approval)
    served = RepositoryModules.loaded(
        bare,
        kit.bench.services,
        {"claude": Recorded(records=Nothing(), reader=Unread())},
    )
    names = [spec.name for spec in served.offered().tools]
    assert {"shout", "whisper"} <= set(names)


# Hooks: what a module does at lup's events.


class NotedServing(ModuleServing):
    """Notes each event in its module's data directory, and fails when the launch stops."""

    module: Listening

    @lup.on(lup.Launched)
    @lup.on(lup.CallStarted)
    @lup.on(lup.Stopped)
    async def note(
        self, event: lup.Launched | lup.CallStarted | lup.Stopped, by: Lup
    ) -> None:
        """Note the event, the tool where there's one, and the conversation."""
        tool = event.tool if isinstance(event, lup.CallStarted) else None
        caller = None if by.conversation is None else by.conversation.id
        with (self.data / "events").open("a", encoding="utf-8") as notes:
            notes.write(f"{event.named()} {tool} {caller}\n")

    @lup.on(lup.Stopped)
    async def stopped(self, event: lup.Stopped) -> None:
        """Fail when the launch stops."""
        message = f"it broke at {event.named()}"
        raise RuntimeError(message)


class Listening(Module):
    """Listening to lup's events."""

    name = "listening"

    serving: Serving = Serving.of(NotedServing)
    data: Mounted = Mounted()


def listening(tmp_path: Path) -> RepositoryModules:
    resolved = resolve(Project(modules=Modules.only(Core(), Listening())))
    return RepositoryModules(
        repository=tmp_path / ".git",
        resolved=resolved,
        recorded={"claude": Recorded(records=Nothing(), reader=Unread())},
        layout=Layout(state=tmp_path, data=tmp_path / "data"),
        exchanges=Unexchanged(),
        marks=StoredMarks(layout=Layout(state=tmp_path, data=tmp_path / "data")),
    )


def test_a_module_s_hooks_offer_the_events_they_run_at(tmp_path: Path) -> None:
    assert listening(tmp_path).offered().events == [
        "launched",
        "stopped",
        "call-started",
    ]


def test_an_event_runs_each_hook_with_its_module_s_data_and_tells_what_failed(
    tmp_path: Path,
) -> None:
    serving = listening(tmp_path)
    registered = launch(tmp_path)
    started = Happening(
        launch=registered,
        event=lup.CallStarted(call="u1", tool="Bash"),
        conversation=CALLER,
    )
    assert asyncio.run(serving.happen(started)).failures == []
    ending = Happening(launch=registered, event=lup.Stopped())
    stopped = asyncio.run(serving.happen(ending))
    [failure] = stopped.failures
    assert failure.startswith("`NotedServing.stopped` failed at stopped:")
    assert "it broke at stopped" in failure
    data = tmp_path / "data" / "modules" / "listening"
    [notes] = list(data.rglob("events"))
    assert notes.read_text() == "call-started Bash c1\nstopped None None\n"


class Elsewhere(Nothing):
    """Another runtime, keeping no records either."""


class ReadingServing(ModuleServing):
    """Notes whose records each launch opening reads."""

    module: Reader

    @lup.on(lup.Launched)
    async def read(self, event: lup.Launched, by: Lup) -> None:
        """Note the launch, and its runtime's records."""
        del event
        records = type(self.recorded[by.launch.runtime].records).__name__
        with (self.data / "read").open("a", encoding="utf-8") as notes:
            notes.write(f"{by.launch.launch} {records}\n")


class Reader(Module):
    """Reading each launch's records."""

    name = "reader"

    serving: Serving = Serving.of(ReadingServing)


def test_each_launch_s_hooks_read_its_own_runtime_s_records(tmp_path: Path) -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Reader())))
    serving = RepositoryModules(
        repository=tmp_path / ".git",
        resolved=resolved,
        recorded={
            "claude": Recorded(records=Nothing(), reader=Unread()),
            "codex": Recorded(records=Elsewhere(), reader=Unread()),
        },
        layout=Layout(state=tmp_path, data=tmp_path / "data"),
        exchanges=Unexchanged(),
        marks=StoredMarks(layout=Layout(state=tmp_path, data=tmp_path / "data")),
    )
    one = launch(tmp_path)
    two = one.model_copy(update={"launch": "two", "runtime": "codex"})
    for each in [one, two]:
        happened = asyncio.run(
            serving.happen(Happening(launch=each, event=lup.Launched()))
        )
        assert happened.failures == []
    [notes] = list((tmp_path / "data").rglob("read"))
    assert notes.read_text() == "one Nothing\ntwo Elsewhere\n"


def test_a_module_s_data_each_room_mounts_resolves_by_its_name() -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Listening())))
    assert [(each.module, each.read_only) for each in resolved.shared] == [
        ("listening", True)
    ]


# `Publishing`: the one event a hook answers, refusing what would leave.


class GuardedServing(ModuleServing):
    """Refuses a post whose body says `hush`, failing where its body says `crash`; and a tool that publishes."""

    module: Guarding

    @lup.on(lup.Publishing)
    async def refuse(self, event: lup.Publishing, by: Lup) -> list[Refusal]:
        """Refuse each part saying `hush`, by its place, and a post an agent didn't make."""
        match event.published:
            case Post(parts=parts):
                if any("crash" in part.text for part in parts):
                    message = "the check broke"
                    raise RuntimeError(message)
                unmade = (
                    [Refusal(what="a post", place=Place(within="it"), steer="no")]
                    if by.conversation is None
                    else []
                )
                return [
                    *unmade,
                    *(
                        Refusal(
                            what="a word kept quiet",
                            place=Place(within=f"the {part.name}", line=1),
                            steer="say it another way",
                        )
                        for part in parts
                        if "hush" in part.text
                    ),
                ]
            case _:
                return []

    @lup.tool
    async def announce(self, said: Said, by: Agent) -> str:
        """Announce what you're told."""
        await self.publish(
            Post(what="an announcement", parts=[Part(name="body", text=said.text)]),
            "this announcement",
            by,
        )
        return f"announced: {said.text}"


class Guarding(Module):
    """Keeping a word quiet."""

    name = "guarding"

    serving: Serving = Serving.of(GuardedServing)


def guarding(tmp_path: Path) -> RepositoryModules:
    resolved = resolve(Project(modules=Modules.only(Core(), Guarding())))
    return RepositoryModules(
        repository=tmp_path / ".git",
        resolved=resolved,
        recorded={"claude": Recorded(records=Nothing(), reader=Unread())},
        layout=Layout(state=tmp_path, data=tmp_path / "data"),
        exchanges=Unexchanged(),
        marks=StoredMarks(layout=Layout(state=tmp_path, data=tmp_path / "data")),
    )


def publishing(tmp_path: Path, text: str) -> Happening:
    return Happening(
        launch=launch(tmp_path),
        event=lup.Publishing(published=post(text)),
        conversation=CALLER,
    )


def post(text: str) -> Post:
    return Post(
        what="a note",
        parts=[Part(name="title", text="t"), Part(name="body", text=text)],
    )


def test_publishing_is_an_event_a_module_s_hooks_offer(tmp_path: Path) -> None:
    assert "publishing" in guarding(tmp_path).offered().events


def test_a_hook_at_publishing_refuses_naming_what_and_where(tmp_path: Path) -> None:
    happening = publishing(tmp_path, "please hush")
    happened = asyncio.run(guarding(tmp_path).happen(happening))
    assert happened.failures == []
    assert happened.refusals == [
        Refusal(
            what="a word kept quiet",
            place=Place(within="the body", line=1),
            steer="say it another way",
        )
    ]
    quiet = publishing(tmp_path, "all fine")
    assert asyncio.run(guarding(tmp_path).happen(quiet)).refusals == []


def test_a_hook_failing_at_publishing_refuses_what_it_couldn_t_check(
    tmp_path: Path,
) -> None:
    happening = publishing(tmp_path, "crash")
    happened = asyncio.run(guarding(tmp_path).happen(happening))
    [failure] = happened.failures
    assert failure.startswith("`GuardedServing.refuse` failed at publishing:")
    [refusal] = happened.refusals
    assert refusal.what.startswith("a check that didn't run: `GuardedServing.refuse`")
    assert refusal.place == Place(within="all of it")


def test_a_tool_publishes_through_every_module_s_hooks_first(tmp_path: Path) -> None:
    calling = Calling(
        launch=launch(tmp_path),
        name="announce",
        arguments={"text": "hush now"},
        caller=CALLER,
    )
    answer = asyncio.run(guarding(tmp_path).call(calling))
    assert answer.error
    # The conversation calling is the one publishing, so the hook knows it.
    assert answer.text == (
        "`announce` didn't run: lup refused to publish this announcement: a "
        "module's check at `Publishing` found what isn't published, at each "
        "place below.\n"
        "  the body:1 - a word kept quiet\n"
        "      steer: say it another way"
    )
    fine = Calling(
        launch=launch(tmp_path),
        name="announce",
        arguments={"text": "hello"},
        caller=CALLER,
    )
    assert asyncio.run(guarding(tmp_path).call(fine)).text == "announced: hello"


# Views and commands: a module's views answered by its repository's process, and
# its commands on the command line.


class Greeting(Model):
    """Whom to greet, and how."""

    name: str = Field(description="Whom to greet.")
    loud: bool = Field(default=False, alias="shout", description="Shout it.")


class Shown(Model):
    """A view's own argument."""

    what: str


class ViewerServing(ModuleServing):
    """A view placed in a drawer, one a fold reads, and a command."""

    module: Viewer

    @lup.view(
        place=lup.Drawer(letter="w", called="the greeting", colour="cyan"),
        watch=lup.Watch(on=[lup.TurnEnded], longest=timedelta(minutes=1)),
    )
    async def greeting(self, viewed: lup.OfAgent) -> lup.Blocks:
        """Greet the agent."""
        line = lup.Line.of("1", f"hello {viewed.session}", "warm")
        return lup.Blocks(summary=[lup.Span(text="greeting")], blocks=[line])

    @lup.view
    async def wrong(self, viewed: Shown) -> lup.Blocks:
        """Name a tone nobody declares."""
        return lup.Blocks(blocks=[lup.Line.of("1", viewed.what, "nobody's")])

    @lup.view
    async def plain(self, viewed: Shown) -> lup.Blocks:
        """Show what it's given, of no agent."""
        return lup.Blocks(blocks=[lup.Line.of("1", viewed.what)])

    @lup.view
    async def remembered(self, viewed: lup.OfAgent) -> lup.Blocks:
        """Say how far the operator read the agent, by their review mark, and offer reading it all."""
        key = {"session": viewed.session}
        mark = await self.marks.mark(key)
        said = "nothing read" if mark is None else f"read to {mark.up_to}"
        return lup.Blocks(
            blocks=[lup.Line.of("1", said)],
            offers=[self.marks.offer(key, "9", "mark it read")],
        )

    @lup.view(place=lup.Banner())
    async def mood(self, viewed: lup.OfAgent) -> lup.Blocks:
        """Say the agent's mood on their banner."""
        return lup.Blocks(
            summary=[lup.Span(text=f"{viewed.session} is glad", tone="warm")]
        )

    @lup.command
    async def greet(self, asked: Greeting, by: Operator) -> str:
        """Greet someone, as the operator."""
        del by
        said = f"hello {asked.name}"
        return said.upper() if asked.loud else said


class Viewer(Module):
    """Greeting, as views and a command."""

    name = "viewer"

    serving: Serving = Serving.of(ViewerServing)
    tones: Tones = Tones.of(lup.Tone(name="warm", colour="orange"))
    folds: Folds = Folds()
    verbs: Verbs = Verbs()


def viewing(tmp_path: Path) -> RepositoryModules:
    resolved = resolve(Project(modules=Modules.only(Core(), Viewer())))
    return RepositoryModules(
        repository=tmp_path / ".git",
        resolved=resolved,
        recorded={"claude": Recorded(records=Nothing(), reader=Unread())},
        layout=Layout(state=tmp_path, data=tmp_path),
        exchanges=Unexchanged(),
        marks=StoredMarks(layout=Layout(state=tmp_path, data=tmp_path)),
    )


def test_a_view_placed_in_a_drawer_resolves_with_its_letter_after_the_core_s(
    tmp_path: Path,
) -> None:
    looks = viewing(tmp_path).resolved.looks
    assert [(each.view, each.place.letter) for each in looks.drawers] == [
        *((each.view, each.place.letter) for each in CORE_LOOKS.drawers),
        ("greeting", "w"),
    ]
    assert [tone.name for tone in looks.tones] == [
        *(tone.name for tone in CORE_LOOKS.tones),
        "warm",
    ]
    assert looks.folds == SHELL_FOLDS


def test_the_core_s_looks_are_the_shell_s_the_runtime_adapters_and_the_judge_s() -> (
    None
):
    # The shell's fold kinds are `Core`'s, first among the modules'.
    looks = resolve(Project(modules=Modules.only(Core()))).looks
    assert CORE_LOOKS.folds == []
    assert [fold.name for fold in looks.folds] == [
        "group",
        "item",
        "file",
        "body",
        "lines",
        "context",
    ]
    assert [
        (each.module, each.view, each.place.letter) for each in CORE_LOOKS.drawers
    ] == [
        ("adapters", "tasks", "t"),
        ("judge", "since", "s"),
    ]
    assert [(each.module, each.view) for each in CORE_LOOKS.banners] == [
        ("adapters", "banner"),
        ("judge", "banner"),
    ]


def test_a_view_placed_on_the_banner_resolves_as_a_part_of_it_after_the_core_s(
    tmp_path: Path,
) -> None:
    looks = viewing(tmp_path).resolved.looks
    assert [(each.module, each.view) for each in looks.banners] == [
        ("adapters", "banner"),
        ("judge", "banner"),
        ("viewer", "mood"),
    ]


def test_the_repository_s_process_says_how_its_views_look_as_it_lists_them(
    tmp_path: Path,
) -> None:
    modules = viewing(tmp_path)
    assert modules.offered().looks == modules.resolved.looks


def test_the_repository_s_process_answers_a_view_for_the_operator_with_when_it_s_answered_again(
    tmp_path: Path,
) -> None:
    asked = Viewing(
        repository=tmp_path / ".git",
        module="viewer",
        view="greeting",
        argument={"runtime": "r", "session": "s1"},
    )
    viewed = asyncio.run(viewing(tmp_path).view(asked))
    assert viewed.blocks.text() == "greeting\nhello s1"
    assert viewed.watch == Watching(
        of=lup.OfAgent(runtime="r", session="s1"),
        on=["turn-ended"],
        longest=timedelta(minutes=1),
    )


def test_a_view_reads_its_module_s_review_marks_watched_as_each_it_read_moves(
    tmp_path: Path, clock: FakeClock
) -> None:
    repository = tmp_path / ".git"
    asked = Viewing(
        repository=repository,
        module="viewer",
        view="remembered",
        argument={"runtime": "r", "session": "s1"},
    )
    unread = asyncio.run(viewing(tmp_path).view(asked))
    assert unread.blocks.text() == "nothing read"
    read = Remarked(repository=repository, module="viewer", key='{"session":"s1"}')
    assert unread.watch.marks == [read]
    [offer] = unread.blocks.offers
    assert (offer.action, offer.argument["module"], offer.argument["up_to"]) == (
        "review-mark",
        "viewer",
        "9",
    )
    marks = MarkStore(layout=Layout(state=tmp_path, data=tmp_path).marks(repository))
    marks.moved(
        "viewer", [ReviewMark(key={"session": "s1"}, up_to="4", at=clock.now())]
    )
    # Another module's mark of the same key is its own.
    marks.moved("other", [ReviewMark(key={"session": "s1"}, up_to="8", at=clock.now())])
    assert asyncio.run(viewing(tmp_path).view(asked)).blocks.text() == "read to 4"


def test_a_view_of_no_agent_is_watched_at_nothing_of_one(tmp_path: Path) -> None:
    asked = Viewing(
        repository=tmp_path / ".git",
        module="viewer",
        view="plain",
        argument={"what": "hi"},
    )
    assert asyncio.run(viewing(tmp_path).view(asked)).watch == Watching()


def test_a_view_of_another_repository_is_refused(tmp_path: Path) -> None:
    asked = Viewing(
        repository=tmp_path / "other.git",
        module="viewer",
        view="greeting",
        argument={"runtime": "r", "session": "s1"},
    )
    with pytest.raises(LupDevError, match="was asked of"):
        asyncio.run(viewing(tmp_path).view(asked))


def test_a_view_naming_a_tone_nobody_declares_is_refused(tmp_path: Path) -> None:
    asked = Viewing(
        repository=tmp_path / ".git",
        module="viewer",
        view="wrong",
        argument={"what": "hi"},
    )
    with pytest.raises(LupDevError, match="names tones no module declares: nobody's"):
        asyncio.run(viewing(tmp_path).view(asked))


def test_a_view_given_what_it_doesn_t_take_is_refused(tmp_path: Path) -> None:
    asked = Viewing(
        repository=tmp_path / ".git",
        module="viewer",
        view="greeting",
        argument={"what": "hi"},
    )
    with pytest.raises(LupDevError, match="doesn't take what it was given"):
        asyncio.run(viewing(tmp_path).view(asked))


def test_two_modules_taking_one_fold_letter_fail_the_load() -> None:
    clashing = Viewer(
        folds=Folds.of(
            lup.FoldKind(
                name="mine", letter="w", called="mine", one="mine", level=1, colour="ok"
            )
        )
    )
    with pytest.raises(ProjectError, match="Fold keys"):
        resolve(Project(modules=Modules.only(Core(), clashing)))


@pytest.mark.parametrize(
    ("letter", "whose"),
    [("f", "core"), ("s", "judge"), ("t", "adapters")],
)
def test_a_module_taking_a_letter_of_the_core_s_fails_the_load(
    letter: str, whose: str
) -> None:
    clashing = Viewer(
        folds=Folds.of(
            lup.FoldKind(
                name="mine",
                letter=letter,
                called="mine",
                one="mine",
                level=1,
                colour="ok",
            )
        )
    )
    with pytest.raises(ProjectError, match=rf"Fold keys: .*`{letter}` from `{whose}`"):
        resolve(Project(modules=Modules.only(Core(), clashing)))


def test_a_person_s_layer_changes_how_a_shell_s_fold_kind_starts_and_whether_zr_reaches_it() -> (
    None
):
    lines = next(each for each in SHELL_FOLDS if each.name == "lines")
    kept = lines.model_copy(update={"by_all": False, "starts_open": False})
    project = Project(
        modules=Modules.only(Core()).edit(Core(folds=Folds().replace("lines", kept)))
    )
    looks = resolve(project).looks
    [changed] = [each for each in looks.folds if each.name == "lines"]
    assert (changed.by_all, changed.starts_open, changed.letter) == (False, False, "u")
    # Every other kind as the shell declares it: starting as its view lays it out, reached by zR.
    others = [each for each in looks.folds if each.name != "lines"]
    assert all(each.by_all and each.starts_open is None for each in others)


def test_a_module_naming_a_fold_kind_or_a_tone_as_the_core_does_fails_the_load() -> (
    None
):
    named = Viewer(
        folds=Folds.of(
            lup.FoldKind(
                name="since",
                letter="z",
                called="mine",
                one="mine",
                level=1,
                colour="ok",
            )
        )
    )
    with pytest.raises(ProjectError, match=r"Fold kinds: .*`since` from `judge`"):
        resolve(Project(modules=Modules.only(Core(), named)))
    toned = Viewer(tones=Tones.of(lup.Tone(name="summary", colour="ok")))
    with pytest.raises(ProjectError, match=r"Tones: .*`summary` from `the core`"):
        resolve(Project(modules=Modules.only(Core(), toned)))


def test_a_tone_taking_an_unknown_tone_s_look_fails_the_load() -> None:
    odd = Viewer(tones=Tones.of(lup.Tone(name="odd", like="nowhere")))
    with pytest.raises(ProjectError, match="takes the look of `nowhere`"):
        resolve(Project(modules=Modules.only(Core(), odd)))


def test_a_module_s_commands_and_views_run_on_the_command_line(
    tmp_path: Path,
) -> None:
    modules = viewing(tmp_path)
    app = commanding.commands("viewer", modules.resolved.served, modules.made, Operator)
    runner = CliRunner()
    greeted = runner.invoke(app, ["greet", "you", "--shout"])
    assert greeted.output == "HELLO YOU\n"
    shown = runner.invoke(app, ["greeting", "claude", "s1"])
    assert shown.output == "greeting\nhello s1\n"
    helped = runner.invoke(app, ["greet", "--help"])
    assert "Greet someone, as the operator." in helped.output
    assert "--shout" in helped.output


def test_a_command_its_runner_may_not_run_is_refused_as_it_runs(
    tmp_path: Path,
) -> None:
    modules = viewing(tmp_path)
    room = Room(launch=launch(tmp_path))
    app = commanding.commands(
        "viewer", modules.resolved.served, modules.made, lambda: room
    )
    ran = CliRunner().invoke(app, ["greet", "you"])
    assert isinstance(ran.exception, LupDevError)
    assert "never by `Room`" in str(ran.exception)


def test_a_module_command_names_one_of_the_repository_s_modules(
    tmp_path: Path,
) -> None:
    modules = viewing(tmp_path)
    with pytest.raises(commanding.CommandError, match="its modules are viewer"):
        commanding.commands("nobody", modules.resolved.served, modules.made, Operator)


def test_the_approved_copy_runs_a_module_s_command_itself(tmp_path: Path) -> None:
    copy = tmp_path / "copy" / "bin" / "lup-dev"
    copy.parent.mkdir(parents=True)
    copy.touch()
    link = tmp_path / "lup-dev"
    link.symlink_to(copy)
    assert commanding.approved(link, copy)
    assert not commanding.approved(tmp_path / "installed", copy)
    assert not commanding.approved(link, None)


def test_nothing_approved_hands_no_command_over(tmp_path: Path) -> None:
    with pytest.raises(commanding.CommandError, match="`lup-dev trust` approves it"):
        commanding.handed_over(["transcripts", "list"], None, tmp_path)


def test_a_first_word_that_isn_t_lup_dev_s_own_names_a_module() -> None:
    assert module_command(["transcripts", "list"])
    assert not module_command(["inbox"])
    assert not module_command(["--help"])
    assert not module_command([])


def test_the_verbs_are_the_core_s_the_judge_s_and_the_runtime_s_then_each_module_s(
    tmp_path: Path,
) -> None:
    assert [(each.name, each.key) for each in resolve(Project()).looks.verbs] == [
        ("done", "d"),
        ("decline", "x"),
        ("send", "s"),
        ("comment", "c"),
        ("hold", "h"),
        ("pause", "p"),
    ]
    tagging = Viewer(verbs=Verbs.of(lup.Verb(name="tag", key="t", called="tag")))
    looks = resolve(Project(modules=Modules.only(Core(), tagging))).looks
    assert [each.name for each in looks.verbs][-1] == "tag"
    del tmp_path


@pytest.mark.parametrize(
    ("verb", "says"),
    [
        (lup.Verb(name="tag", key="d", called="tag"), r"Verb keys: .*`d` from `core`"),
        (lup.Verb(name="hold", key="q", called="hold"), r"Verbs: .*`hold`"),
        (lup.Verb(name="find", key="f", called="find"), r"Verb keys: .*`f`"),
    ],
)
def test_a_verb_taking_a_key_or_a_name_another_has_fails_the_load(
    verb: lup.Verb, says: str
) -> None:
    clashing = Viewer(verbs=Verbs.of(verb))
    with pytest.raises(ProjectError, match=says):
        resolve(Project(modules=Modules.only(Core(), clashing)))


def test_a_layer_gives_a_verb_another_key() -> None:
    moved = Core(
        verbs=Verbs.default().replace(
            "hold", lup.Verb(name="hold", key="H", called="hold")
        )
    )
    looks = resolve(Project(modules=Modules.only(moved))).looks
    assert [(each.name, each.key) for each in looks.verbs if each.name == "hold"] == [
        ("hold", "H")
    ]
