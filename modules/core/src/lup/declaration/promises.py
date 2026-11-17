"""The declaration's promises: what a project can count on of loading and resolving its declaration.

Each is checked through the harness, as lup's start loads and resolves a
declaration, over example modules defined here and declarations the harness
generates (`README.md` here, *Promises*).
"""

from functools import reduce
from pathlib import Path
from typing import Literal

import lup
from lup import (
    Lend,
    Lending,
    Model,
    Module,
    Modules,
    Named,
    Part,
    Profile,
    Profiles,
    Project,
    ProjectError,
    chosen,
)
from lup.testing import Repository, Testing, raises


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


class DeclarationPromises(lup.Part):
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
        started = await by.started(Repository(declaration=EPISODES))
        [episodes] = [each for each in started.modules if each.name == "episodes"]
        assert Episodic.model_validate(episodes.model_dump()).length == 30

    @lup.promise
    async def a_declaration_that_doesnt_load_says_so(self, by: Testing) -> None:
        """A declaration that binds no project, binds something else, or fails as it runs raises `ProjectError`, never standing in the defaults."""
        unloadable = by.any(Unloadable)
        with raises(ProjectError):
            await by.started(Repository(declaration=unloadable.body))

    @lup.promise
    async def a_repository_declaring_nothing_runs_on_lups_defaults(
        self, by: Testing
    ) -> None:
        """A repository with no declaration runs on lup's default modules, its layers still over them."""
        started = await by.started(Repository())
        assert [each.name for each in started.modules] == [
            each.name for each in (await by.started(Project())).modules
        ]

    @lup.promise
    async def the_most_specific_layer_wins(self, by: Testing) -> None:
        """The repository's own local layer wins over the machine's, which wins over its declaration, each changing only what it sets."""
        layered = by.any(Layered)
        started = await by.started(layered.repository())
        [held] = [each for each in started.modules if isinstance(each, lup.Core)]
        assert held.profile == layered.expected()

    @lup.promise
    async def a_broken_layer_is_never_left_out(self, by: Testing) -> None:
        """A layer that's there and doesn't load fails the read, rather than lup running as if it weren't there."""
        unloadable = by.any(Unloadable)
        broken = by.any(Broken)
        declared = PROFILED.format(profile="default")
        files = (
            Repository(declaration=declared, local=unloadable.body)
            if broken.layer == "local"
            else Repository(declaration=declared, machine=unloadable.body)
        )
        with raises(ProjectError):
            await by.started(files)


PROFILED = """
from lup import Core, Modules, Profile, Profiles, Project

project = Project(
    modules=Modules().edit(
        Core(profiles=Profiles().add(Profile(name="{profile}")), profile="{profile}")
    )
)
"""
"""A layer choosing the profile it names, as a declaration or a layer writes one."""


class Broken(Model):
    """Which layer of a repository's is the one that's broken."""

    layer: Literal["local", "machine"]


class Layered(Model):
    """Which of a repository's files choose a profile, each naming its own."""

    declaration: bool
    machine: bool
    local: bool

    def repository(self) -> Repository:
        """Return the repository's files: each that chooses one, choosing the profile named after it."""
        return Repository(
            declaration=PROFILED.format(profile="declared")
            if self.declaration
            else None,
            machine=PROFILED.format(profile="machine") if self.machine else None,
            local=PROFILED.format(profile="local") if self.local else None,
        )

    def expected(self) -> str:
        """Return the profile the most specific file choosing one names, `default` where none does."""
        chosen = [
            name
            for name, chooses in [
                ("local", self.local),
                ("machine", self.machine),
                ("declared", self.declaration),
            ]
            if chooses
        ]
        return next(iter(chosen), lup.Core().profile)


class Accounted(Model):
    """A profile's accounts as a layer might give them: one for every runtime, and one in its place for a runtime it names."""

    account: Literal["work", "home", "team"]
    runtime: Literal["claude", "codex"]
    instead: Literal["work", "home", "team"] | None = None


class ProfilesPromises(Part):
    """What a repository can count on of the profiles its sessions run on, as its layers declare them."""

    @lup.promise
    async def a_profile_layer_changes_only_what_it_sets(self, by: Testing) -> None:
        """A layer on a profile changes the fields it sets, and every other field stays as the profile below has it."""
        accounted = by.any(Accounted)
        lent = Lending.of(Lend(path=Path("/notes")))
        default = lup.Core().profile
        below = Profile(name=default, lent=lent)
        layer = Profile(name=default, account=accounted.account)
        core = lup.Core(profiles=Profiles.of(below).edit(layer))
        started = await by.started(Project(modules=Modules.default().edit(core)))
        [held] = [each for each in started.modules if isinstance(each, lup.Core)]
        picked = chosen(held.profiles, accounted.runtime, profile=held.profile)
        assert picked.account == accounted.account
        assert picked.profile.lent == lent

    @lup.promise
    async def a_session_logs_in_with_the_account_its_runtime_is_given(
        self, by: Testing
    ) -> None:
        """A session's account is the one it's started with where it's given one, else the one its profile names for its runtime, else the profile's own."""
        accounted = by.any(Accounted)
        accounts = (
            {} if accounted.instead is None else {accounted.runtime: accounted.instead}
        )
        profile = Profile(name="work", account=accounted.account, accounts=accounts)
        core = lup.Core(profiles=Profiles().add(profile), profile="work")
        started = await by.started(Project(modules=Modules.default().edit(core)))
        [held] = [each for each in started.modules if isinstance(each, lup.Core)]
        on_it = chosen(held.profiles, accounted.runtime, profile=held.profile)
        assert on_it.account == (accounted.instead or accounted.account)
        given = chosen(held.profiles, accounted.runtime, profile="work", account="x")
        assert given.account == "x"

    @lup.promise
    async def every_repository_has_the_default_profile(self, by: Testing) -> None:
        """Profiles that leave out `default`, which sessions run on where nothing chooses another, are refused, as is a profile no one declared."""
        core = lup.Core(profiles=Profiles.of(Profile(name="work")))
        started = await by.started(Project(modules=Modules.default().edit(core)))
        [held] = [each for each in started.modules if isinstance(each, lup.Core)]
        with raises(ProjectError):
            chosen(held.profiles, "claude", profile="work")
        default = Profiles.of(Profile(name=lup.Core().profile))
        with raises(ProjectError):
            chosen(default, "claude", profile="gone")

    @lup.promise
    async def a_name_places_nothing_outside_its_own_directory(
        self, by: Testing
    ) -> None:
        """A profile's or an account's name that would name a directory elsewhere (a `/`, `..`, a leading `.`) is refused as it's written."""
        for name in ["../work", "a/b", ".hidden", ""]:
            with raises(ValueError):
                Profile(name=name)
            with raises(ValueError):
                Profile(name="fine", account=name)
