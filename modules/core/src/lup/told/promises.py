"""Guidance's promises: what a module's author, and a project selecting modules, can count on of the sections a session is told.

Each is checked through the harness over example modules defined here, started
as a project's declaration starts them and rendered as a session's start
renders them; and two over the modules a project selects: those lup ships, at
their defaults, and those of whichever project's gate checks it (`README.md`
here, *Promises*).
"""

from typing import Literal
lazy from string.templatelib import Template

from pydantic import Field

import lup
from lup import (
    Agent,
    GuidanceError,
    Model,
    Module,
    Modules,
    Part,
    Parts,
    Project,
    ProjectError,
    Secret,
)
from lup.testing import Guidance, Repository, Testing, raises


class GuidedPart(Part):
    """The example module's sections: one from its settings, one for the session told it."""

    module: Guided

    @lup.guidance
    async def running(self) -> Template:
        """Say how the project's commands run."""
        if self.module.broken:
            message = "this section can't render"
            raise ValueError(message)
        return (
            t"## Running\n\nRun the project's commands through `{self.module.runner}`."
        )

    @lup.guidance
    async def greeting(self, by: Agent) -> str:
        """Greet the session told it, where the module greets."""
        return f"You're `{by.id}`." if self.module.greets else ""


class Guided(Module):
    """A module with something to tell sessions: an example the guidance's promises render."""

    name = "guided"
    runner: str = "uv run"
    """What the project's commands run through, as its section says."""
    greets: bool = False
    """Whether it greets the session told it."""
    broken: bool = False
    """Whether its section fails as it renders."""
    parts: Parts = Parts.of(GuidedPart)


class LongPart(Part):
    """A section as long as its module says."""

    module: Long

    @lup.guidance
    async def filler(self) -> str:
        """Say as many bytes as the module says."""
        return "x" * self.module.size


class Long(Module):
    """A module whose section is as long as it says."""

    name = "long"
    size: int = 1
    parts: Parts = Parts.of(LongPart)


class Longer(Long):
    """Another module whose section is as long as it says."""

    name = "longer"


class HoldingPart(Part):
    """A section on a part holding a secret."""

    module: Holding
    token: Secret

    @lup.guidance
    async def holding(self) -> str:
        """Say what the part holds, which no section may."""
        return self.token.value


class Holding(Module):
    """A module whose section is on a part holding a secret."""

    name = "holding"
    parts: Parts = Parts.of(HoldingPart)


def declared(*modules: Module) -> Project:
    """Return a project of lup's default modules and `modules`."""
    return Project(modules=Modules.default().add(*modules))


class Runner(Model):
    """What a project's commands run through, as a promise draws it."""

    runner: str = Field(min_length=1, max_length=40)


class Sizes(Model):
    """Two sections' sizes, as a promise draws them: together, under or past a project's room."""

    long: int = Field(ge=0, le=20_000)
    longer: int = Field(ge=0, le=20_000)


class Unrendered(Model):
    """A section that can't render, by what's wrong with it."""

    wrong: Literal["it raises", "its part holds a secret"]


class Misshapen(Model):
    """A method that can't be a section, by what's wrong with it."""

    wrong: Literal[
        "not async",
        "a model taken",
        "a number answered",
        "told to the operator",
    ]

    def methods(self) -> str:
        """Return the method, named `wrong`, as its class's body."""
        match self.wrong:
            case "not async":
                return '''
    @lup.guidance
    def wrong(self) -> str:
        """Not async."""
        return ""
'''
            case "a model taken":
                return '''
    @lup.guidance
    async def wrong(self, said: lup.Model) -> str:
        """A model taken."""
        return ""
'''
            case "a number answered":
                return '''
    @lup.guidance
    async def wrong(self) -> int:
        """A number."""
        return 1
'''
            case "told to the operator":
                return '''
    @lup.guidance
    async def wrong(self, by: lup.Operator) -> str:
        """Told to the operator, who isn't a session."""
        return ""
'''


def misshapen(methods: str) -> str:
    """Return a project's declaration whose module's part holds `methods`."""
    return f'''
import lup


class TellingPart(lup.Part):
    """Telling's sections."""
{methods}

class Telling(lup.Module):
    """Telling sessions something."""

    name = "telling"
    parts: lup.Parts = lup.Parts.of(TellingPart)


project = lup.Project(modules=lup.Modules.default().add(Telling()))
'''


class GuidancePromises(Part):
    """What a module's author, and a project selecting modules, can count on of the sections a session is told."""

    @lup.promise
    async def a_section_says_its_modules_settings(self, by: Testing) -> None:
        """A module's section is filled from its settings, every layer applied, for whichever session it's told to."""
        runner = by.any(Runner).runner
        project = Project(
            modules=Modules.default().add(Guided()).edit(Guided(runner=runner))
        )
        told = await (await by.started(project)).guidance(by.any(Agent))
        [running] = [each for each in told.sections if each.module == Guided.name]
        assert running.method == "GuidedPart.running"
        assert runner in running.text

    @lup.promise
    async def a_section_with_nothing_to_say_is_left_out(self, by: Testing) -> None:
        """A section may differ by the session it's told to, and one rendering to nothing for it is left out."""
        greets = by.any(bool)
        agent = by.any(Agent)
        started = await by.started(declared(Guided(greets=greets)))
        told = await started.guidance(agent)
        greeting = [
            each for each in told.sections if each.method == "GuidedPart.greeting"
        ]
        assert bool(greeting) == greets
        assert all(agent.id in each.text for each in greeting)

    @lup.promise
    async def sections_come_in_the_declarations_order(self, by: Testing) -> None:
        """Sections come in the order the declaration gives their modules, then their parts', then their own, and the guidance is each of them, in that order."""
        modules: list[Module] = [Guided(greets=True), Long()]
        ordered = modules if by.any(bool) else list(reversed(modules))
        started = await by.started(declared(*ordered))
        told = await started.guidance(by.any(Agent))
        names = [each.name for each in ordered]
        assert [each.module for each in told.sections if each.module in names] == [
            name for name in names for _ in range(2 if name == Guided.name else 1)
        ]
        guided = [each.method for each in told.sections if each.module == Guided.name]
        assert guided == ["GuidedPart.running", "GuidedPart.greeting"]
        text = told.text()
        start = 0
        for each in told.sections:
            found = text.find(each.text, start)
            assert found >= 0
            start = found + len(each.text)

    @lup.promise
    async def a_section_that_cant_render_fails_naming_its_module(
        self, by: Testing
    ) -> None:
        """A section that raises as it renders, or sits on a part holding a secret, fails the guidance, naming its module, rather than being told or dropped without a word."""
        match by.any(Unrendered).wrong:
            case "it raises":
                module: Module = Guided(broken=True)
            case "its part holds a secret":
                module = Holding()
        started = await by.started(declared(module))
        with raises(GuidanceError) as failed:
            await started.guidance(by.any(Agent))
        assert module.name in failed.raised().about

    @lup.promise
    async def a_method_that_cant_be_a_section_fails_the_load(self, by: Testing) -> None:
        """A section that isn't async, takes a model, answers other than words, or is told to a party that isn't a session fails the declaration's load, naming it, before any session starts."""
        wrong = by.any(Misshapen)
        with raises(ProjectError) as failed:
            await by.started(Repository(declaration=misshapen(wrong.methods())))
        assert "TellingPart.wrong" in failed.raised().about

    @lup.promise
    async def guidance_past_its_room_fails_naming_its_modules(
        self, by: Testing
    ) -> None:
        """Guidance past the room a project's modules may take fails, naming its modules, the largest first; guidance within it passes."""
        sizes = by.any(Sizes)
        project = declared(Long(size=sizes.long), Longer(size=sizes.longer))
        told = await (await by.started(project)).guidance(by.any(Agent))
        if told.size() <= Guidance.project.most:
            told.within(Guidance.project)
            return
        with raises(GuidanceError) as past:
            told.within(Guidance.project)
        largest = sorted(
            [(sizes.long, Long.name), (sizes.longer, Longer.name)], reverse=True
        )
        named = past.raised().about
        assert named[0] == largest[0][1] or largest[0][0] == largest[1][0]

    @lup.promise
    async def lups_own_modules_render_and_leave_a_project_room(
        self, by: Testing
    ) -> None:
        """Every module lup ships renders its sections at its defaults for any session, and together they take at most lup's share of the smallest runtime's ceiling, leaving room for a project's own sections, the operator's own, and what a session's start adds."""
        started = await by.started(Project(modules=Modules.all()))
        told = await started.guidance(by.any(Agent))
        told.within(Guidance.shipped)

    @lup.promise(every_project=True)
    async def a_projects_guidance_renders_and_leaves_the_operator_room(
        self, by: Testing
    ) -> None:
        """Every section the project's modules serve, lup's and its own, renders for any session, and together they leave room under the smallest runtime's ceiling for the operator's own section and what a session's start adds: checked at every project's gate, so a project adding a long section learns there."""
        started = await by.started(by.project())
        told = await started.guidance(by.any(Agent))
        told.within(Guidance.project)
