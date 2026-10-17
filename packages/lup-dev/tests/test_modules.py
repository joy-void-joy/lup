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

from lup.tools.tool import lup_tool
from lup.types import Model
from lup_dev import (
    Core,
    Handlers,
    Module,
    ModuleHandler,
    Modules,
    ModuleTools,
    Project,
    ProjectError,
    Toolsets,
)
from lup_dev.declaration.resolve import resolve
from lup_dev.errors import LupDevError
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Limits, Register, Reply, Request
from lup_dev.host.workers import Called, Calling, Sent, Workers
from lup_dev.layout import HostLayout
from lup_dev.worker import Serving

CALLER = Conversation(id="c1", session="s1")


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
    return Serving(launch=launch(tmp_path), resolved=resolved)


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
