"""The doors' promises: what a module's code and its callers can count on of the doors its methods are reached through.

Each is checked through the harness over example modules defined here: started
as a project's declaration starts them, and called as a party calls them. A door
wrong in a way pyright would refuse is written in a declaration's file, as a
project's code reaches lup where pyright doesn't hold it (`README.md` here,
*Promises*).
"""

from typing import Literal

from pydantic import Field

import lup
from lup import (
    Agent,
    Model,
    Module,
    Modules,
    ModuleServing,
    Operator,
    Project,
    ProjectError,
    Serving,
)
from lup.testing import Accepted, Refused, Testing, raises


class Said(Model):
    """What to shout."""

    text: str


class Shouted(Model):
    """What was shouted, and for whom."""

    text: str
    caller: str


class Merging(Model):
    """A branch to merge."""

    branch: str


class Greeting(Model):
    """Someone to greet."""

    name: str


class EchoServing(ModuleServing):
    """Echo's methods, one behind each door a party calls."""

    module: Echo

    @lup.tool(reads=True)
    async def shout(self, said: Said, by: Agent) -> Shouted:
        """Shout what you're told.

        As many times as the module's volume says.
        """
        return Shouted(text=said.text.upper() * self.module.volume, caller=by.id)

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
    """Another module's tool, named as echo's."""

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


def declared(*modules: Module) -> Project:
    """Return a project of lup's default modules and `modules`."""
    return Project(modules=Modules.default().add(*modules))


class Loudness(Model):
    """How loud echo shouts, within what a promise can run."""

    volume: int = Field(ge=1, le=5)


class Sending(Model):
    """Something a party sends through one of echo's doors, or one it doesn't have."""

    door: Literal["tool", "action", "command"]
    name: Literal["shout", "merge", "greet", "whisper"]
    given: dict[str, str | int | None]
    by: Agent | Operator


def loud(methods: str) -> str:
    """Return a project's declaration whose module's class of methods holds `methods`."""
    return f'''
from typing import TYPE_CHECKING

import lup

if TYPE_CHECKING:
    from lup import Operator


class Said(lup.Model):
    """What's said."""

    text: str


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


class Misshapen(Model):
    """A method that can't be behind its door, by what's wrong with it."""

    wrong: Literal[
        "not async",
        "two models",
        "by alone",
        "a tool answering a number",
        "a tool's summary too long",
        "no docstring",
        "by naming no party",
        "a command not saying who may run it",
        "a name defined for type checking alone",
        "two doors",
    ]

    def methods(self) -> str:
        """Return the method, named `wrong`, as its class's body."""
        match self.wrong:
            case "not async":
                return '''
    @lup.tool
    def wrong(self, said: Said) -> str:
        """Not async."""
        return said.text
'''
            case "two models":
                return '''
    @lup.tool
    async def wrong(self, said: Said, more: Said) -> str:
        """Two models."""
        return said.text
'''
            case "by alone":
                return '''
    @lup.tool
    async def wrong(self, by: lup.Agent) -> str:
        """Who calls, and nothing else."""
        return by.id
'''
            case "a tool answering a number":
                return '''
    @lup.tool
    async def wrong(self, said: Said) -> int:
        """A number."""
        return 1
'''
            case "a tool's summary too long":
                return '''
    @lup.tool
    async def wrong(self, said: Said) -> str:
        """A summary line far longer than the fifty characters a summary may take."""
        return said.text
'''
            case "no docstring":
                return """
    @lup.tool
    async def wrong(self, said: Said) -> str:
        return said.text
"""
            case "by naming no party":
                return '''
    @lup.command
    async def wrong(self, said: Said, by: str) -> str:
        """A command whose caller isn't a party."""
        return said.text
'''
            case "a command not saying who may run it":
                return '''
    @lup.command
    async def wrong(self, said: Said) -> str:
        """A command not saying who may run it."""
        return said.text
'''
            case "a name defined for type checking alone":
                return '''
    @lup.command
    async def wrong(self, said: Said, by: Operator) -> str:
        """A command whose caller's class is imported for type checking alone."""
        return said.text
'''
            case "two doors":
                return '''
    @lup.tool
    @lup.command
    async def wrong(self, said: Said, by: lup.Operator) -> str:
        """Two doors."""
        return said.text
'''


class Holding(Model):
    """A class of a module's methods holding more than its module."""

    held: Literal["a method named as a field", "a field of its own"]

    def methods(self) -> str:
        """Return the class's body, past its `module`."""
        match self.held:
            case "a method named as a field":
                return '''
    @lup.tool
    async def module(self, said: Said) -> str:
        """Hide the class's module."""
        return said.text
'''
            case "a field of its own":
                return """
    count: int = 0
"""


class DoorsPromises(ModuleServing):
    """What a module's code and its callers can count on of the doors its methods are reached through."""

    @lup.promise
    async def a_session_is_told_each_tool_its_modules_serve(self, by: Testing) -> None:
        """A session is told each tool its project's modules serve, by its name, its summary and its marks, with nothing called."""
        started = await by.started(declared(Echo()))
        [spec] = [each for each in started.tools() if each.name == "shout"]
        assert spec.summary == "Shout what you're told."
        assert spec.reads

    @lup.promise
    async def a_call_runs_its_method_with_its_module_and_its_caller(
        self, by: Testing
    ) -> None:
        """A tool call runs its method with the module's settings, every layer applied, and hands it the agent calling."""
        volume = by.any(Loudness).volume
        agent = by.any(Agent)
        started = await by.started(declared(Echo(volume=volume)))
        answered = await started.call("shout", Said(text="hi"), agent)
        assert isinstance(answered, Accepted)
        assert answered.output == Shouted(text="HI" * volume, caller=agent.id)

    @lup.promise
    async def nothing_sent_makes_a_call_raise(self, by: Testing) -> None:
        """Whatever a party sends through a door, and to whichever name, the call answers: run, or refused with what was sent."""
        sending = by.any(Sending)
        started = await by.started(declared(Echo()))
        match sending.door:
            case "tool":
                answered = await started.call(sending.name, sending.given, sending.by)
            case "action":
                answered = await started.act(
                    "echo", sending.name, sending.given, sending.by
                )
            case "command":
                answered = await started.run(
                    "echo", sending.name, sending.given, sending.by
                )
        assert isinstance(answered, Accepted | Refused)
        if isinstance(answered, Refused):
            assert answered.rejection.submitted == sending.given

    @lup.promise
    async def what_a_tool_doesnt_take_is_refused(self, by: Testing) -> None:
        """A call whose arguments aren't what its tool takes, or to a tool no module serves, is refused with what was sent, rather than run."""
        agent = by.any(Agent)
        started = await by.started(declared(Echo()))
        sent = {"words": "hi"}
        wrong = await started.call("shout", sent, agent)
        assert isinstance(wrong, Refused)
        assert wrong.rejection.submitted == sent
        assert isinstance(await started.call("whisper", {}, agent), Refused)

    @lup.promise
    async def a_method_answers_only_who_its_for(self, by: Testing) -> None:
        """A method runs only for the parties its `by` names, checked before each call: the operator's command refuses an agent."""
        started = await by.started(declared(Echo()))
        greeting = Greeting(name="kai")
        refused = await started.run("echo", "greet", greeting, by.any(Agent))
        assert isinstance(refused, Refused)
        accepted = await started.run("echo", "greet", greeting, Operator())
        assert isinstance(accepted, Accepted)

    @lup.promise
    async def a_command_takes_everything_as_arguments(self, by: Testing) -> None:
        """A command run without an argument it needs is refused at once, never asking for it."""
        started = await by.started(declared(Echo()))
        assert isinstance(await started.run("echo", "greet", {}, Operator()), Refused)

    @lup.promise
    async def a_method_refusing_is_answered_as_a_refusal(self, by: Testing) -> None:
        """A method refusing what it's asked, by raising `RefusedError`, answers a refusal; asked otherwise, it runs."""
        started = await by.started(declared(Echo()))
        main = await started.act("echo", "merge", Merging(branch="main"), Operator())
        assert isinstance(main, Refused)
        dev = await started.act("echo", "merge", Merging(branch="dev"), Operator())
        assert isinstance(dev, Accepted)

    @lup.promise
    async def a_method_read_through_an_instance_is_called_as_any(
        self, by: Testing
    ) -> None:
        """A module's method, read through an instance of its class, is called as any method, typed as written."""
        serving = EchoServing(module=Echo(volume=2))
        shouted = await serving.shout(Said(text="a"), by=by.any(Agent))
        assert shouted.text == "AA"

    @lup.promise
    async def a_class_of_methods_is_dropped_by_its_name(self, by: Testing) -> None:
        """A project drops a class of a module's methods by its class's name, and nothing of it is served."""
        quiet = Echo(serving=Serving().drop("EchoServing"))
        started = await by.started(declared(quiet))
        assert all(each.name != "shout" for each in started.tools())

    @lup.promise
    async def a_tool_two_modules_share_fails_the_load_naming_both(
        self, by: Testing
    ) -> None:
        """A tool's name is one method's across modules, so two modules sharing one fail to resolve, naming both; dropping one's class resolves."""
        with raises(ProjectError) as shared:
            await by.started(declared(Echo(), Other()))
        assert all(name in shared.raised().about for name in ["echo", "other"])
        quiet = Other(serving=Serving().drop("OtherServing"))
        started = await by.started(declared(Echo(), quiet))
        assert [each.name for each in started.tools()].count("shout") == 1

    @lup.promise
    async def a_class_of_methods_is_made_with_the_module_listing_it(
        self, by: Testing
    ) -> None:
        """A module listing a class narrowed to another module's class fails to resolve, rather than serving it with the wrong settings."""
        with raises(ProjectError):
            await by.started(declared(Borrowing()))

    @lup.promise
    async def a_method_that_cant_be_behind_its_door_fails_the_load_naming_it(
        self, by: Testing
    ) -> None:
        """A method that isn't what its door takes and returns, or doesn't say who may call it where its door has no default, fails the declaration's load, naming it, before anything calls it."""
        misshapen = by.any(Misshapen)
        with raises(ProjectError) as failed:
            await by.started(loud(misshapen.methods()))
        assert "LoudServing.wrong" in failed.raised().about

    @lup.promise
    async def a_door_reads_a_class_defined_further_down_its_file(
        self, by: Testing
    ) -> None:
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
        started = await by.started(loud(methods))
        assert any(each.name == "shout" for each in started.tools())

    @lup.promise
    async def a_class_of_methods_holds_its_module_alone(self, by: Testing) -> None:
        """A class of a module's methods holds its module alone, made afresh for each call: a field of its own, or a method hiding its module, fails the load."""
        holding = by.any(Holding)
        with raises(ProjectError):
            await by.started(loud(holding.methods()))
