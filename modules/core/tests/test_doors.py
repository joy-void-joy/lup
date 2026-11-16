"""The doors' promises, checked through the doors and the environment's call.

Until #14 gives modules `@lup.promise`, each test is one promise, said in its
docstring. A module's methods are reached as the harness and the services reach
them: by resolving a declaration and calling through `Doors`. A door wrong in a
way pyright would refuse is written in a declaration file, as a project's code
reaches lup where pyright doesn't hold it.
"""

import asyncio
from typing import TYPE_CHECKING, Literal

import pytest

import lup
from lup import (
    Agent,
    JsonObject,
    Model,
    Module,
    Modules,
    ModuleServing,
    Operator,
    Project,
    ProjectError,
    Request,
    Serving,
)
from lup.doors.door import Accepted, Refused
from lup.environment.declaration import load, resolve

if TYPE_CHECKING:
    from pathlib import Path

    from lup.environment.doors import Doors


class Said(Model):
    """What to shout."""

    text: str


class Shouted(Model):
    """What was shouted, and for whom."""

    text: str
    caller: str


class Ping(Request):
    """Whether a module is there."""

    kind: Literal["ping"] = "ping"
    text: str


class Pong(Model):
    """A module's answer to a ping."""

    text: str


class Merging(Model):
    """A branch to merge."""

    branch: str


class Greeting(Model):
    """Someone to greet."""

    name: str


class EchoServing(ModuleServing):
    """Echo's methods, one behind each door."""

    module: Echo

    @lup.tool(reads=True)
    async def shout(self, said: Said, by: Agent) -> Shouted:
        """Shout what you're told.

        As many times as the module's volume says.
        """
        return Shouted(text=said.text.upper() * self.module.volume, caller=by.id)

    @lup.request
    async def ping(self, asked: Ping, by: Agent) -> Pong:
        """Answer a ping from an agent's room, as many times as the volume says."""
        return Pong(text=asked.text * self.module.volume)

    @lup.action(verb="done", says="merge it")
    async def merge(self, merging: Merging) -> str:
        """Merge a branch, refusing `main`, which is merged into."""
        if merging.branch == "main":
            message = "`main` is merged into, never merged"
            raise lup.RefusedError(message)
        return merging.branch

    @lup.command
    async def greet(self, greeting: Greeting, by: Operator) -> str:
        """Greet someone, as the operator."""
        return greeting.name


class Echo(Module):
    """Shouting what it's told."""

    name = "echo"
    volume: int = 1
    serving: Serving = Serving.of(EchoServing)


class OtherServing(ModuleServing):
    """Another module's tool and request, named as echo's."""

    module: Other

    @lup.tool
    async def shout(self, said: Said) -> str:
        """Shout too."""
        return said.text

    @lup.request
    async def answer(self, asked: Ping, by: Agent) -> Pong:
        """Answer a ping too."""
        return Pong(text=asked.text)


class Other(Module):
    """Shouting too."""

    name = "other"
    serving: Serving = Serving.of(OtherServing)


class Borrowing(Module):
    """Listing another module's methods as its own."""

    name = "borrowing"
    serving: Serving = Serving.of(EchoServing)


def doors(*modules: Module) -> Doors:
    return resolve(Project(modules=Modules.default().add(*modules))).doors


def written(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "declaration.py"
    path.write_text(body)
    return path


AGENT = Agent(id="agent-1")


def test_a_session_is_told_each_tool_its_modules_serve() -> None:
    """A session is told each tool its project's modules serve, by its name, its summary and its marks, with nothing called."""
    [spec] = doors(Echo()).tools()
    assert spec.name == "shout"
    assert spec.summary == "Shout what you're told."
    assert spec.reads


def test_a_call_runs_its_method_with_its_module_and_its_caller() -> None:
    """A tool call runs its method with the module's settings, every layer applied, and hands it the agent calling."""
    result = asyncio.run(doors(Echo(volume=2)).call("shout", {"text": "hi"}, AGENT))
    assert isinstance(result, Accepted)
    assert result.output == Shouted(text="HIHI", caller=AGENT.id)


def test_arguments_a_tool_doesnt_take_are_refused() -> None:
    """A call whose arguments aren't what its tool takes is refused, with what was sent, rather than run."""
    sent: JsonObject = {"words": "hi"}
    result = asyncio.run(doors(Echo()).call("shout", sent, AGENT))
    assert isinstance(result, Refused)
    assert result.rejection.submitted == sent


def test_a_tool_no_module_serves_is_refused() -> None:
    """A call to a tool no module serves is refused, not raised."""
    assert isinstance(asyncio.run(doors(Echo()).call("whisper", {}, AGENT)), Refused)


def test_a_method_answers_only_who_its_for() -> None:
    """A method runs only for the parties its `by` names, checked before each call: the operator's command refuses an agent."""
    served = doors(Echo())
    greeting: JsonObject = {"name": "kai"}
    refused = asyncio.run(served.run("echo", "greet", greeting, AGENT))
    assert isinstance(refused, Refused)
    accepted = asyncio.run(served.run("echo", "greet", greeting, Operator()))
    assert isinstance(accepted, Accepted)


def test_a_command_takes_everything_as_arguments() -> None:
    """A command run without an argument it needs is refused at once, never asking for it."""
    result = asyncio.run(doors(Echo()).run("echo", "greet", {}, Operator()))
    assert isinstance(result, Refused)


def test_a_request_is_answered_by_the_method_for_its_kind() -> None:
    """A request is routed by its kind to the one method answering it, run with its module; a kind no module answers is refused."""
    served = doors(Echo(volume=3))
    result = asyncio.run(served.ask({"kind": "ping", "text": "a"}, AGENT))
    assert isinstance(result, Accepted)
    assert result.output == Pong(text="aaa")
    assert "ping" in served.kinds()
    unknown = asyncio.run(served.ask({"kind": "pong"}, AGENT))
    assert isinstance(unknown, Refused)


def test_a_method_refusing_is_answered_as_a_refusal() -> None:
    """A method refusing what it's asked, by raising `RefusedError`, answers a refusal; asked otherwise, it runs."""
    served = doors(Echo())
    refused = asyncio.run(served.act("echo", "merge", {"branch": "main"}, Operator()))
    assert isinstance(refused, Refused)
    merged = asyncio.run(served.act("echo", "merge", {"branch": "dev"}, Operator()))
    assert isinstance(merged, Accepted)


def test_a_method_read_through_an_instance_is_called_as_any() -> None:
    """A module's method, read through an instance of its class, is called as any method, typed as written."""
    serving = EchoServing(module=Echo(volume=2))
    shouted = asyncio.run(serving.shout(Said(text="a"), by=AGENT))
    assert shouted.text == "AA"


def test_a_class_of_methods_is_dropped_by_its_name() -> None:
    """A project drops a class of a module's methods by its class's name, and nothing of it is served."""
    quiet = Echo(serving=Serving().drop("EchoServing"))
    assert doors(quiet).tools() == []


def test_a_tool_or_a_kind_two_modules_share_fails_the_load_naming_both() -> None:
    """A tool's name and a request's kind are one method's across modules, so two modules sharing one fail to resolve, naming both."""
    with pytest.raises(ProjectError) as shared:
        doors(Echo(), Other())
    assert all(name in str(shared.value) for name in ["echo", "other"])
    quiet = Other(serving=Serving.of(EchoServing).drop("EchoServing"))
    assert [spec.name for spec in doors(Echo(), quiet).tools()] == ["shout"]


def test_a_class_of_methods_is_made_with_the_module_listing_it() -> None:
    """A module listing a class narrowed to another module's class fails to resolve, rather than serving it with the wrong settings."""
    with pytest.raises(ProjectError):
        doors(Borrowing())


DECLARATION = '''
from typing import TYPE_CHECKING, Literal

import lup

if TYPE_CHECKING:
    from lup import Operator


class Said(lup.Model):
    """What's said."""

    text: str


class Ping(lup.Request):
    """A ping."""

    kind: Literal["ping"] = "ping"


class LoudServing(lup.ModuleServing):
    """Loud's methods."""

    module: Loud

{methods}


class Loud(lup.Module):
    """Shouting."""

    name = "loud"
    serving: lup.Serving = lup.Serving.of(LoudServing)


project = lup.Project(modules=lup.Modules.default().add(Loud()))
'''


def declared(tmp_path: Path, methods: str) -> Doors:
    body = DECLARATION.replace("{methods}", methods)
    return resolve(load(written(tmp_path, body))).doors


@pytest.mark.parametrize(
    "methods",
    [
        pytest.param(
            '''
    @lup.tool
    def wrong(self, said: Said) -> str:
        """Not async."""
        return said.text
''',
            id="not async",
        ),
        pytest.param(
            '''
    @lup.tool
    async def wrong(self, said: Said, more: Said) -> str:
        """Two models."""
        return said.text
''',
            id="two models",
        ),
        pytest.param(
            '''
    @lup.tool
    async def wrong(self, said: Said) -> int:
        """A number."""
        return 1
''',
            id="a tool answering a number",
        ),
        pytest.param(
            '''
    @lup.tool
    async def wrong(self, said: Said) -> str:
        """A summary line far longer than the fifty characters a summary may take."""
        return said.text
''',
            id="a tool's summary too long",
        ),
        pytest.param(
            """
    @lup.tool
    async def wrong(self, said: Said) -> str:
        return said.text
""",
            id="no docstring",
        ),
        pytest.param(
            '''
    @lup.request
    async def wrong(self, asked: Ping) -> Said:
        """A request not saying who may send it."""
        return Said(text="")
''',
            id="a request without by",
        ),
        pytest.param(
            '''
    @lup.request
    async def wrong(self, asked: Said, by: lup.Agent) -> Said:
        """A request taking what isn't a request."""
        return asked
''',
            id="a request taking a plain model",
        ),
        pytest.param(
            '''
    @lup.command
    async def wrong(self, said: Said, by: str) -> str:
        """A command whose caller isn't a party."""
        return said.text
''',
            id="by naming no party",
        ),
        pytest.param(
            '''
    @lup.command
    async def wrong(self, said: Said, by: Operator) -> str:
        """A command whose caller's class is imported for type checking alone."""
        return said.text
''',
            id="a name defined for type checking alone",
        ),
        pytest.param(
            '''
    @lup.tool
    @lup.command
    async def wrong(self, said: Said, by: lup.Operator) -> str:
        """Two doors."""
        return said.text
''',
            id="two doors",
        ),
    ],
)
def test_a_method_that_cant_be_behind_its_door_fails_the_load_naming_it(
    tmp_path: Path, methods: str
) -> None:
    """A method that isn't what its door takes and returns, or doesn't say who may call it where its door has no default, fails the declaration's load, naming it, before anything calls it."""
    with pytest.raises(ProjectError) as failed:
        declared(tmp_path, methods)
    assert "wrong" in str(failed.value)


def test_a_door_reads_a_class_defined_further_down_its_file(tmp_path: Path) -> None:
    """A method may name a class its file defines further down, as Python allows: its door reads it once the declaration resolves."""
    methods = '''
    @lup.tool
    async def shout(self, heard: Heard) -> str:
        """Shout what's heard."""
        return heard.text


class Heard(lup.Model):
    """What's heard."""

    text: str
'''
    assert [spec.name for spec in declared(tmp_path, methods).tools()] == ["shout"]


@pytest.mark.parametrize(
    "methods",
    [
        pytest.param(
            '''
    @lup.tool
    async def module(self, said: Said) -> str:
        """Hide the class's module."""
        return said.text
''',
            id="a method named as a field",
        ),
        pytest.param(
            """
    count: int = 0
""",
            id="a field of its own",
        ),
    ],
)
def test_a_class_of_methods_holds_its_module_alone(
    tmp_path: Path, methods: str
) -> None:
    """A class of a module's methods holds its module alone, made afresh for each call: a field of its own, or a method hiding its module, fails the load."""
    with pytest.raises(ProjectError):
        declared(tmp_path, methods)
