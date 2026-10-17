"""A module's tools and its answers to the room's requests: declared, resolved, and served by a launch's own process.

The modules here are small: `Echo`, whose one tool shouts what it's told and whose
handler answers `ping`. The last tests start the real `lup-dev worker` process
on a repository whose declaration holds such a module, and talk to it as the
host service does.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Literal, override

import pytest
import sh

from lup.tools.hook import lup_hook
from lup.tools.tool import ToolError, lup_tool
from lup.types import Model
from lup_dev import (
    Core,
    Handlers,
    Hooks,
    Module,
    ModuleHandler,
    Modules,
    ModuleTools,
    Project,
    ProjectError,
    Toolsets,
)
from lup_dev.declaration.kinds import Mounted
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import ModuleHooks, Moment
from lup_dev.errors import LupDevError
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Limits, Register, Reply, Request
from lup_dev.host.records import Record, Records
from lup_dev.host.workers import Called, Calling, Happening, Sent, Workers
from lup_dev.layout import HostLayout, Layout
from lup_dev.worker import Serving

CALLER = Conversation(id="c1", session="s1")


class Nothing(Records):
    """A runtime that keeps no records."""

    def kept(self, under: list[Path]) -> list[Record]:
        return []


class Said(Model):
    """What to shout."""

    text: str


class EchoTools(ModuleTools):
    """Echo's tool."""

    module: Echo

    @lup_tool
    async def shout(self, said: Said) -> str:
        """Shout what you're told."""
        loud = said.text.upper() * self.module.volume
        return f"{loud}, for {self.caller.id} of {self.launch.launch}"

    @lup_tool
    async def fail(self, said: Said) -> str:
        """Fail, saying why."""
        message = f"it can't: {said.text}"
        raise LupDevError(message)


class Ping(Request):
    """Ask the module to answer."""

    kind: Literal["ping"] = "ping"
    text: str


class Pong(Reply):
    """The module's answer."""

    kind: Literal["pong"] = "pong"
    text: str


class Ponging(ModuleHandler):
    """Answers `ping`, as many times as the module's volume."""

    module: Echo
    request: Ping

    @override
    async def answer(self) -> Reply:
        return Pong(text=self.request.text * self.module.volume)


class Echo(Module):
    """Shouting what it's told."""

    name = "echo"

    volume: int = 1
    tools: Toolsets = Toolsets.of(EchoTools)
    handlers: Handlers = Handlers.of(Ponging)


class OtherTools(ModuleTools):
    """Another module's tool of the same name."""

    module: Other

    @lup_tool
    async def shout(self, said: Said) -> str:
        """Shout too."""
        return said.text


class Other(Module):
    """Shouting too."""

    name = "other"

    tools: Toolsets = Toolsets.of(OtherTools)


class Borrowing(Module):
    """Listing another module's tools as its own."""

    name = "borrowing"

    tools: Toolsets = Toolsets.of(EchoTools)


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


def test_a_module_s_tools_and_handlers_resolve_with_their_module() -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Echo(volume=2))))
    [served] = resolved.served
    assert served.tools is EchoTools
    assert isinstance(served.module, Echo)
    assert served.module.volume == 2
    [handled] = resolved.handled
    assert handled.handler is Ponging
    assert handled.module is served.module


def test_lup_s_defaults_serve_github_s_tools_until_it_s_dropped() -> None:
    names = [each.tools.__name__ for each in resolve(Project()).served]
    assert names == ["GitHubTools"]
    dropped = Project(modules=Modules.default().drop("github"))
    assert resolve(dropped).served == []
    assert resolve(dropped).handled == []


def test_a_toolset_is_dropped_by_its_class_s_name() -> None:
    quiet = Echo(tools=Toolsets().drop("EchoTools"))
    resolved = resolve(Project(modules=Modules.only(Core(), quiet)))
    assert resolved.served == []


def test_a_tool_named_alike_by_two_modules_is_refused_naming_both() -> None:
    with pytest.raises(ProjectError, match=r"`shout` from `echo` and `other`"):
        resolve(Project(modules=Modules.only(Core(), Echo(), Other())))


def test_tools_made_with_another_module_are_refused() -> None:
    with pytest.raises(ProjectError, match=r"`EchoTools` in `borrowing` narrows"):
        resolve(Project(modules=Modules.only(Core(), Borrowing())))


def serving(tmp_path: Path, volume: int = 1) -> Serving:
    resolved = resolve(Project(modules=Modules.only(Core(), Echo(volume=volume))))
    return Serving(
        launch=launch(tmp_path),
        resolved=resolved,
        records=Nothing(),
        layout=Layout(state=tmp_path, data=tmp_path),
    )


def test_a_launch_s_modules_offer_their_tools_and_kinds(tmp_path: Path) -> None:
    offered = serving(tmp_path).offered()
    assert [spec.name for spec in offered.tools] == ["shout", "fail"]
    assert offered.kinds == ["ping"]


def test_a_call_is_made_with_its_module_the_launch_and_the_caller(
    tmp_path: Path,
) -> None:
    calling = Calling(name="shout", arguments={"text": "hi"}, caller=CALLER)
    answer = asyncio.run(serving(tmp_path, volume=2).call(calling))
    assert answer.text == "HIHI, for c1 of one"
    assert not answer.error


def test_a_tool_that_can_t_says_why(tmp_path: Path) -> None:
    calling = Calling(name="fail", arguments={"text": "no"}, caller=CALLER)
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text == "`fail` didn't run: it can't: no"
    assert answer.error


def test_arguments_the_tool_doesn_t_take_are_refused(tmp_path: Path) -> None:
    calling = Calling(name="shout", arguments={"words": "hi"}, caller=CALLER)
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text.startswith("`shout` refused the call:")
    assert answer.error


def test_a_tool_no_module_serves_is_said(tmp_path: Path) -> None:
    calling = Calling(name="whisper", arguments={}, caller=CALLER)
    answer = asyncio.run(serving(tmp_path).call(calling))
    assert answer.text == "no module of this launch serves `whisper`"


def test_a_room_s_request_is_answered_by_its_module_s_handler(tmp_path: Path) -> None:
    sent = Sent.model_validate({"kind": "ping", "text": "a"})
    assert asyncio.run(serving(tmp_path, volume=3).answer(sent)) == Pong(text="aaa")


DECLARATION = '''"""A project with a module of its own."""

from lup.tools.tool import lup_tool
from lup.types import Model
from lup_dev import Module, ModuleTools, Modules, Project, Toolsets


class Said(Model):
    """What to shout."""

    text: str


class LoudTools(ModuleTools):
    """Loud's tool."""

    module: Loud

    @lup_tool
    async def shout(self, said: Said) -> str:
        """Shout what you're told."""
        return f"{said.text.upper()} from {self.module.name}"


class Loud(Module):
    """Shouting."""

    name = "loud"

    tools: Toolsets = Toolsets.of(LoudTools)


project = Project(modules=Modules.default().add(Loud()))
'''


@pytest.fixture
def host(tmp_path_factory: pytest.TempPathFactory) -> HostLayout:
    # A socket's path is limited in length, so the service's directory is short.
    base = tmp_path_factory.mktemp("host")
    return HostLayout(sockets=base / "run", state=base / "state")


def test_a_launch_s_own_process_serves_its_committed_declaration_s_modules(
    repo: Path, state: object, host: HostLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "lup_project.py").write_text(DECLARATION)
    sh.git("add", "-A", _cwd=str(repo))
    sh.git("commit", "-q", "-m", "a module of its own", _cwd=str(repo))
    host.launches.mkdir(parents=True)
    # The worktree's own copy changes after the commit: the process reads the commit.
    (repo / "lup_project.py").write_text("raise SystemExit('not this one')\n")
    bin_directory = Path(sys.executable).parent
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}")
    registered = launch(repo).model_copy(
        update={"judge": Path(sys.executable).parent / "lup-dev"}
    )
    said: list[str] = []

    async def run() -> tuple[list[str], Called, Called, bool]:
        workers = Workers(layout=host, say=said.append)
        offered = await workers.open(registered)
        calling = Calling(name="shout", arguments={"text": "hi"}, caller=CALLER)
        first = await workers.ask(registered, calling)
        process = workers.running["one"].process
        process.kill()
        await process.wait()
        again = await workers.ask(registered, calling)
        await workers.close(registered)
        gone = workers.running.get("one") is None
        assert isinstance(first, Called)
        assert isinstance(again, Called)
        return [spec.name for spec in offered.tools], first, again, gone

    names, first, again, gone = asyncio.run(run())
    assert "shout" in names
    assert "read_issue" in names
    assert first.answer.text == "HI from loud"
    assert again.answer == first.answer
    assert gone
    assert not host.modules("one").exists()
    assert any("starting it again" in line for line in said)


# Hooks: what a module does at lup's moments.


class Noted(ModuleHooks):
    """Notes each moment in its module's data directory, and fails when the launch stops."""

    module: Listening

    @lup_hook(on=["launched", "call_started", "stopped"])
    async def note(self, moment: Moment) -> None:
        """Note the moment, and the tool where there's one."""
        with (self.data / "moments").open("a", encoding="utf-8") as notes:
            notes.write(f"{moment.name} {moment.tool}\n")

    @lup_hook
    async def stopped(self, moment: Moment) -> None:
        """Fail when the launch stops."""
        message = f"it broke at {moment.name}"
        raise RuntimeError(message)


class Listening(Module):
    """Listening to lup's moments."""

    name = "listening"

    hooks: Hooks = Hooks.of(Noted)
    data: Mounted = Mounted()


def listening(tmp_path: Path) -> Serving:
    resolved = resolve(Project(modules=Modules.only(Core(), Listening())))
    return Serving(
        launch=launch(tmp_path),
        resolved=resolved,
        records=Nothing(),
        layout=Layout(state=tmp_path, data=tmp_path / "data"),
    )


def test_a_hook_naming_no_moment_of_lups_is_refused() -> None:
    with pytest.raises(ProjectError, match=r"runs `landed` at `landed`"):
        # lup: ignore("reportUnusedClass", why="defining it is the test: its definition is refused")
        class Landing(ModuleHooks):
            """Runs at a moment lup doesn't have."""

            module: Listening

            @lup_hook
            async def landed(self, moment: Moment) -> None:
                """Never runs."""


def test_a_module_s_hooks_offer_the_occasions_they_run_at(tmp_path: Path) -> None:
    assert listening(tmp_path).offered().occasions == [
        "launched",
        "stopped",
        "call-started",
    ]


def test_a_moment_runs_each_hook_with_its_module_s_data_and_tells_what_failed(
    tmp_path: Path,
) -> None:
    serving = listening(tmp_path)
    started = Happening(occasion="call-started", conversation=CALLER, tool="Bash")
    assert asyncio.run(serving.happen(started)).failures == []
    stopped = asyncio.run(serving.happen(Happening(occasion="stopped")))
    [failure] = stopped.failures
    assert failure.startswith("`Noted.stopped` failed at stopped:")
    assert "it broke at stopped" in failure
    data = tmp_path / "data" / "modules" / "listening"
    [notes] = list(data.rglob("moments"))
    assert notes.read_text() == "call_started Bash\nstopped None\n"


def test_a_module_s_data_each_room_mounts_resolves_by_its_name() -> None:
    resolved = resolve(Project(modules=Modules.only(Core(), Listening())))
    assert [(each.module, each.read_only) for each in resolved.shared] == [
        ("listening", True)
    ]


def test_a_hook_or_a_tool_named_like_a_field_is_refused() -> None:
    with pytest.raises(ToolError, match=r"`Shadowing`'s hook `launch` takes the name"):
        # lup: ignore("reportUnusedClass", why="defining it is the test: its definition is refused")
        class Shadowing(ModuleHooks):
            """Names a hook after the launch it's made with."""

            module: Listening

            @lup_hook(on="launched")
            # lup: ignore("reportIncompatibleVariableOverride", why="the clash is the test: the class is refused for it")
            async def launch(self, moment: Moment) -> None:
                """Would vanish under the field."""

    with pytest.raises(ToolError, match=r"`Hiding`'s tool `caller` takes the name"):
        # lup: ignore("reportUnusedClass", why="defining it is the test: its definition is refused")
        class Hiding(ModuleTools):
            """Names a tool after the conversation calling."""

            module: Echo

            @lup_tool
            # lup: ignore("reportIncompatibleVariableOverride", why="the clash is the test: the class is refused for it")
            async def caller(self, said: Said) -> str:
                """Would vanish under the field."""
                return said.text
