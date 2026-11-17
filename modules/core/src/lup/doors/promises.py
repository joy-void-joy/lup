"""The doors' promises: what a module's code and its callers can count on of the doors its methods are reached through.

Each is checked through the harness over example modules defined here: started
as a project's declaration starts them, and called as a party calls them. A door
wrong in a way pyright would refuse is written in a declaration's file, as a
project's code reaches lup where pyright doesn't hold it (`README.md` here,
*Promises*).
"""

import asyncio
from typing import Literal

from pydantic import Field

import lup
from lup import (
    Agent,
    Code,
    Model,
    Module,
    Modules,
    MutableModel,
    Operator,
    Part,
    Parts,
    Project,
    ProjectError,
    Secret,
    Starting,
    Stopping,
    UncarriedError,
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


class EchoPart(Part):
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
    parts: Parts = Parts.of(EchoPart)


class OtherPart(Part):
    """Another module's tool, named as echo's."""

    module: Other

    @lup.tool
    async def shout(self, said: Said) -> str:
        """Shout too."""
        return said.text


class Other(Module):
    """Shouting too."""

    name = "other"
    parts: Parts = Parts.of(OtherPart)


class Borrowing(Module):
    """Listing another module's methods as its own."""

    name = "borrowing"
    parts: Parts = Parts.of(EchoPart)


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
    """Return a project's declaration whose module's part holds `methods`."""
    return f'''
from typing import TYPE_CHECKING

import lup

if TYPE_CHECKING:
    from lup import Operator


class Said(lup.Model):
    """What's said."""

    text: str


class LoudPart(lup.Part):
    """Loud's methods."""

    module: Loud
{methods}

class Loud(lup.Module):
    """Shouting."""

    name = "loud"
    parts: lup.Parts = lup.Parts.of(LoudPart)


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
    """A part holding what lup can't make it with."""

    held: Literal["a method named as a field", "a field with no default"]

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
            case "a field with no default":
                return """
    count: int
"""


class DoorsPromises(Part):
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
        part = EchoPart(module=Echo(volume=2))
        shouted = await part.shout(Said(text="a"), by=by.any(Agent))
        assert shouted.text == "AA"

    @lup.promise
    async def a_class_of_methods_is_dropped_by_its_name(self, by: Testing) -> None:
        """A project drops a part by its class's name, and nothing of it is served."""
        quiet = Echo(parts=Parts().drop("EchoPart"))
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
        quiet = Other(parts=Parts().drop("OtherPart"))
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
        assert "LoudPart.wrong" in failed.raised().about

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
    async def a_class_of_methods_is_made_with_its_module_alone(
        self, by: Testing
    ) -> None:
        """lup makes a part with its module and its secrets alone: a field of its own with no default, or a method hiding its module, fails the load."""
        holding = by.any(Holding)
        with raises(ProjectError):
            await by.started(loud(holding.methods()))


class Adding(Model):
    """How much to add."""

    by: int = Field(ge=0, le=100)


class Tally(Model):
    """What's been added so far."""

    count: int


class Asking(Model):
    """Asking for something, giving nothing."""


class Tallied(Model):
    """What's been added so far, and whose code asked."""

    count: int
    repository: str


class Revealed(Model):
    """A secret's value, as a class holding it reads it."""

    value: str


class Events(MutableModel):
    """What a keeper's class saw of its own start and stop, in order: kept on its module, so a promise reads it once the class has stopped."""

    seen: list[str] = []


class KeeperPart(Part):
    """A keeper's class: it keeps a count while it runs, holds a token, serves code, and marks its own start and stop."""

    module: Keeper
    count: int = 0
    token: Secret

    @lup.on(Starting)
    async def kept_running(self, starting: Starting) -> None:
        """Run as long as the class runs, marking when it begins and when it's cancelled."""
        del starting
        self.module.events.seen.append("starting")
        try:
            await asyncio.Event().wait()
        finally:
            self.module.events.seen.append("cancelled")

    @lup.on(Stopping)
    async def stopping(self, stopping: Stopping) -> None:
        """Mark the class's stop, before what it started is cancelled."""
        del stopping
        self.module.events.seen.append("stopping")

    @lup.tool
    async def add(self, adding: Adding) -> Tally:
        """Add to the count.

        The class keeps the count while it runs.
        """
        self.count += adding.by
        return Tally(count=self.count)

    @lup.service
    async def tallied(self, asking: Asking, by: Code) -> Tallied:
        """Say the count, and whose code asked."""
        del asking
        return Tallied(count=self.count, repository=by.repository)

    @lup.service
    async def reveal(self, asking: Asking) -> Revealed:
        """Say the token's value, as the class holding it reads it."""
        del asking
        return Revealed(value=self.token.value)

    @lup.service
    async def refuse(self, asking: Asking) -> None:
        """Refuse whatever is asked."""
        del asking
        message = "asked of a keeper that keeps nothing for you"
        raise lup.RefusedError(message)


class AskingPart(Part):
    """Another class, whose tools call the keeper's services as plain calls."""

    @lup.tool
    async def ask(self, asking: Asking) -> Tallied:
        """Ask the keeper for its count, as code."""
        return await KeeperPart.tallied(asking)

    @lup.tool
    async def ask_refused(self, asking: Asking) -> str:
        """Ask the keeper for what it refuses."""
        await KeeperPart.refuse(asking)
        return "answered"


class Keeper(Module):
    """Keeping a count while it runs, behind a token."""

    name = "keeper"
    events: Events = Field(default_factory=Events)
    parts: Parts = Parts.of(KeeperPart, AskingPart)


class RunningPromises(Part):
    """What a module's code can count on of its classes made once where they run: what they keep, the services they serve, the secrets they hold, and their start and stop."""

    @lup.promise
    async def a_class_keeps_what_it_holds_between_calls(self, by: Testing) -> None:
        """A part is made once where it runs, so what it keeps in its fields is there at its next call."""
        first, second = by.any(Adding), by.any(Adding)
        started = await by.started(declared(Keeper()))
        agent = by.any(Agent)
        await started.call("add", first, agent)
        added = await started.call("add", second, agent)
        assert isinstance(added, Accepted)
        assert added.output == Tally(count=first.by + second.by)

    @lup.promise
    async def a_service_is_a_plain_call_by_the_projects_code(self, by: Testing) -> None:
        """A service read through its class is called as a plain call, carried to its class wherever it runs, and called by the project whose code made the call."""
        repository = by.any(str)
        started = await by.started(declared(Keeper()), repository=repository)
        asked = await started.call("ask", Asking(), by.any(Agent))
        assert isinstance(asked, Accepted)
        assert isinstance(asked.output, Tallied)
        assert asked.output.repository == repository

    @lup.promise
    async def a_refused_service_raises_at_its_caller(self, by: Testing) -> None:
        """A service refusing what it's asked raises `RefusedError` at the code that called it, as a plain call's failure would, so a tool calling it is refused in turn."""
        started = await by.started(declared(Keeper()))
        asked = await started.call("ask_refused", Asking(), by.any(Agent))
        assert isinstance(asked, Refused)

    @lup.promise
    async def a_service_runs_only_where_lup_carries_it(self, by: Testing) -> None:
        """A service called where lup runs no module's code, as from a promise's own body, raises `UncarriedError` rather than running somewhere it shouldn't."""
        with raises(UncarriedError):
            await KeeperPart.tallied(Asking())

    @lup.promise
    async def a_service_answers_only_who_its_for(self, by: Testing) -> None:
        """A service is the project's code's to call: an agent calling it by name is refused."""
        started = await by.started(declared(Keeper()))
        refused = await started.serve("tallied", Asking(), by.any(Agent))
        assert isinstance(refused, Refused)

    @lup.promise
    async def a_class_holds_the_secret_stored_under_its_fields_name(
        self, by: Testing
    ) -> None:
        """A class holding a field typed `Secret` is filled, where it runs, with the value stored under the field's name, and says it holds it; a class whose secret nothing stored fails to start."""
        value = by.any(str)
        started = await by.started(declared(Keeper()), secrets={"token": value})
        revealed = await started.serve("reveal", Asking(), Code(repository="harness"))
        assert isinstance(revealed, Accepted)
        assert revealed.output == Revealed(value=value)
        assert "token" in KeeperPart.holds().secrets
        assert KeeperPart.holds().anything()
        with raises(ProjectError):
            await by.started(declared(Keeper()), secrets={})

    @lup.promise
    async def a_class_stops_what_it_started_after_its_stop(self, by: Testing) -> None:
        """What a class runs at `Starting` goes on as long as the class runs; as it stops, its methods run at `Stopping` first, then what it started is cancelled, wherever it had got to."""
        started = await by.started(declared(Keeper()))
        [keeper] = [each for each in started.modules if isinstance(each, Keeper)]
        await asyncio.sleep(0)
        await started.stopped()
        seen = keeper.events.seen
        assert "stopping" in seen
        assert ("starting" in seen) == ("cancelled" in seen)
        if "starting" in seen:
            assert seen.index("starting") < seen.index("stopping")
            assert seen.index("stopping") < seen.index("cancelled")
