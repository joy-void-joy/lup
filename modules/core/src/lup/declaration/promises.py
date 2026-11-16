"""The declaration's promises: what a project can count on of loading and resolving its declaration.

Each is checked through the harness, as lup's start loads and resolves a
declaration, over example modules defined here and declarations the harness
generates (`README.md` here, *Promises*).
"""

from functools import reduce
from typing import Literal

import lup
from lup import Model, Module, Modules, Named, Project, ProjectError
from lup.testing import Testing, raises


class Voices(Named[str]):
    """The voices a story is read in."""


class Narration(Module):
    """Reading a story aloud."""

    name = "narration"
    pace: int = 1
    voices: Voices = Voices.of("narrator")


class Captions(Module):
    """Captions under what's read aloud, which need the reading."""

    name = "captions"
    requires = [Narration]


type Called = Literal["core", "narration", "captions"]
"""A module the generated declarations name: lup's core, or one of the examples."""


def made(name: Called) -> Module:
    """Return the module named `name`, from its own defaults."""
    match name:
        case "core":
            return lup.Core()
        case "narration":
            return Narration()
        case "captions":
            return Captions()


class Verb(Model):
    """One verb a declaration writes on its modules, naming one of three."""

    verb: Literal["add", "drop", "edit", "replace"]
    module: Called
    put: Called
    """What `.replace` puts in the place of `module`."""

    def on(self, modules: Modules) -> Modules:
        """Return `modules` with this verb written after the others."""
        match self.verb:
            case "add":
                return modules.add(made(self.module))
            case "drop":
                return modules.drop(self.module)
            case "edit":
                return modules.edit(made(self.module))
            case "replace":
                return modules.replace(self.module, made(self.put))


class Declared(Model):
    """A declaration, as the verbs it writes on lup's default modules."""

    verbs: list[Verb]

    def project(self) -> Project:
        """Return the project these verbs declare."""
        modules = reduce(
            lambda written, verb: verb.on(written), self.verbs, Modules.default()
        )
        return Project(modules=modules)

    def named(self) -> list[str]:
        """Return the name of every module it names, lup's core among them."""
        return [
            "core",
            *(name for verb in self.verbs for name in (verb.module, verb.put)),
        ]


class Setting(Model):
    """What one layer sets on narration: its pace, a voice it adds, both, or neither."""

    pace: int | None = None
    voice: Literal["narrator", "villain", "hero"] | None = None

    def layer(self) -> Narration:
        """Return narration as a layer setting what this sets: its voices from below, with this one added."""
        voices = Voices() if self.voice is None else Voices().add(self.voice)
        if self.pace is None:
            return Narration(voices=voices)
        return Narration(pace=self.pace, voices=voices)


class Unloadable(Model):
    """A declaration's file that can't be loaded: it binds no project, binds something else, or fails as it runs."""

    body: Literal[
        "x = 1\n",
        "project = 'not a project'\n",
        "raise RuntimeError('broken')\n",
    ]


class Episodic(Model):
    """What the promise reads of a module a declaration's file declares, whose class it can't import."""

    length: int


EPISODES = '''
from lup import Module, Modules, Project


class Episodes(Module):
    """Turning a chapter into an episode."""

    name = "episodes"
    length: int = 20


project = Project(modules=Modules.default().add(Episodes(length=30)))
'''
"""A project's declaration, declaring a module of its own."""


class DeclarationPromises(lup.ModuleServing):
    """What a project can count on of loading and resolving its declaration."""

    @lup.promise
    async def resolving_gives_what_the_declaration_says(self, by: Testing) -> None:
        """Resolving a declaration gives its modules, each once, the core among them, with every module one of them requires and none it doesn't name; or it raises `ProjectError`, never anything else."""
        declared = by.any(Declared)
        try:
            started = await by.started(declared.project())
        except ProjectError:
            return
        names = [module.name for module in started.modules]
        assert all(names.count(name) == 1 for name in names)
        assert "core" in names
        assert all(
            required.name in names
            for module in started.modules
            for required in module.requires
        )
        assert all(name in declared.named() for name in names)

    @lup.promise
    async def a_layer_changes_only_what_it_sets(self, by: Testing) -> None:
        """A layer on a module changes the fields it sets, and every other field stays as below has it."""
        added, edited = by.any(Setting), by.any(Setting)
        modules = Modules.default().add(added.layer()).edit(edited.layer(), why="later")
        started = await by.started(Project(modules=modules))
        [narration] = [each for each in started.modules if isinstance(each, Narration)]
        paces = [each.pace for each in (edited, added) if each.pace is not None]
        assert narration.pace == next(iter(paces), Narration().pace)
        voices = ["narrator", *(each.voice for each in (added, edited) if each.voice)]
        held = narration.held(Voices)
        assert all(voice in held for voice in voices)
        assert all(voice in voices for voice in held)

    @lup.promise
    async def another_core_may_take_its_place(self, by: Testing) -> None:
        """A project may put another module in the core's place, which then counts as the core."""

        class Mine(lup.Core):
            """lup's core, with this project's changes."""

        modules = Modules.default().replace("core", Mine())
        started = await by.started(Project(modules=modules))
        assert any(isinstance(each, Mine) for each in started.modules)

    @lup.promise
    async def a_projects_own_module_loads_as_lups_do(self, by: Testing) -> None:
        """A module a project declares in its own declaration file loads and resolves the way lup's own do."""
        started = await by.started(EPISODES)
        [episodes] = [each for each in started.modules if each.name == "episodes"]
        assert Episodic.model_validate(episodes.model_dump()).length == 30

    @lup.promise
    async def a_declaration_that_doesnt_load_says_so(self, by: Testing) -> None:
        """A declaration that binds no project, binds something else, or fails as it runs raises `ProjectError`, never standing in the defaults."""
        unloadable = by.any(Unloadable)
        with raises(ProjectError):
            await by.started(unloadable.body)
