"""Loading a project's declaration, and resolving which modules it's made of.

A declaration is a Python file binding `project`, a `Project`. Loading it runs it,
and every module it imports, so it's loaded where running a branch's code is
harmless, never by the program on the operator's machine (`DESIGN.md`, *Where
code runs*). What comes out of resolving it (`Resolved`) is the modules, each with
every layer applied, and what they serve behind their doors, which the rest of lup
reads.

Resolving applies every layer over lup's default modules, in order, then checks
what a selection must hold: a module named `core`, and every module a selected
one requires, with no cycle among them. lup never adds or drops a module behind
the declaration's back.
"""

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lup.command_line.names import typed_methods
from lup.core import Core
from lup.declaration.errors import ProjectError
from lup.declaration.grammar import applied, listed, set_fields
from lup.declaration.module import Module, Modules
from lup.declaration.project import Project
from lup.environment.doors import Doors
from lup.errors import LupError
from lup.gate.module import Gate
from lup.github.module import GitHub
from lup.landing.module import Landing
from lup.remote.module import Remote
from lup.running.plan import typed
from lup.shell.looks import Looks
from lup.store.records import Edge, Kinds, Node, Recorded
from lup.types import Model

if TYPE_CHECKING:
    from lup.declaration.layout import MachineLayout, RepositoryLayout


class Resolved(Model):
    """A declaration resolved: what the rest of lup reads of it."""

    modules: list[Module]
    """The modules it's made of, every layer applied, in order."""
    doors: Doors
    """What the modules serve, each method behind its door."""
    looks: Looks
    """The tones, fold kinds and mark kinds the modules declare, which their
    views may name."""
    kinds: Kinds
    """The kinds of record the modules keep in the store, which it reads its records as."""


def default() -> list[Module]:
    """List lup's default modules, in their order: what `Modules.default()` starts from."""
    return [Core(), Gate(), Landing(), Remote(), GitHub()]


def shipped() -> list[Module]:
    """List every module lup ships: what `Modules.all()` starts from and `Modules.only(…)` picks from."""
    return default()


def load(path: Path) -> Project:
    """Run the declaration at `path` and return the `Project` it binds as `project`.

    Raise `ProjectError` where the file can't be run, binds no `project`, or binds
    something else. The modules it defines are importable by the name it's run
    under while it's loaded, as pydantic needs to complete their fields.
    """
    name = f"lup_declared_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        message = f"{path} can't be read as Python: a declaration is a `.py` file"
        raise ProjectError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except ProjectError:
        raise
    except Exception as failed:
        message = f"{path} failed as it ran: {type(failed).__name__}: {failed}"
        about = failed.about if isinstance(failed, LupError) else []
        raise ProjectError(message, about=about) from failed
    finally:
        del sys.modules[name]
    project = getattr(module, "project", None)
    if project is None:
        message = (
            f"{path} binds no `project`: a declaration binds `project = Project(…)`"
        )
        raise ProjectError(message)
    if not isinstance(project, Project):
        message = (
            f"{path} binds `project` to a `{type(project).__name__}`, where it "
            "takes a `lup.Project`"
        )
        raise ProjectError(message)
    return project


class Declared(Model):
    """A repository's declaration as lup finds it: the project, every layer found applied, and the files it was read from."""

    project: Project
    """The project: lup's defaults where the repository declares none, then each
    layer found over it."""
    read: list[Path]
    """The files read, in the order they were applied: the declaration, the
    machine's layer, the repository's own local layer, each where it's there."""


def read(repository: RepositoryLayout, machine: MachineLayout) -> Declared:
    """Return the declaration of `repository`, with the machine's layer and then the repository's own local layer over it, each where it's there.

    A layer binds `project` too, a `Project` written as a layer on what's below
    it: what it sets changes what's below, as a module's layer does, so
    `Modules().edit(…)` changes a module of the project's. The most specific
    comes last: the repository's own layer wins over the machine's, which wins
    over the declaration. A repository with no declaration runs on lup's
    defaults, its layers still over them. Raise `ProjectError` where a file
    found doesn't load (`load`): a layer that's there and broken is never left
    out without a word.
    """
    found = [
        each
        for each in [repository.declaration, machine.layer, repository.local]
        if each.is_file()
    ]
    project = Project()
    for path in found:
        layer = load(path)
        project = (
            layer
            if path == repository.declaration
            else applied(layer, project, set_fields(layer))
        )
    return Declared(project=project, read=found)


def resolve(project: Project) -> Resolved:
    """Return the modules `project` is made of, every layer applied, in order, and what they serve.

    Raise `ProjectError` where a name its verbs give isn't there, where it holds
    no module named `core`, where a module it holds requires one it doesn't,
    where modules require each other in a cycle, where what they serve can't
    be served (`Doors.of`), where a module is named as the core's tools,
    commands and views are typed (`unshadowed`), or where what they declare for
    their views clashes (`Looks.of`).
    """
    selected = project.modules.over(Modules.default())
    placed = selected.resolve(default(), shipped())
    modules = selected.ordered(placed)
    names = [module.name for module in modules]
    if Core.name not in names:
        message = (
            f"every project holds a module named `{Core.name}`, which this "
            f"declaration's modules leave out; they're {listed(names)}"
        )
        raise ProjectError(message, about=[Core.name])
    looped = next(
        (found for module in modules if (found := cycle(type(module), []))), None
    )
    if looped is not None:
        around = " requires ".join(f"`{name}`" for name in looped)
        message = f"modules can't require each other in a cycle: {around}"
        raise ProjectError(message, about=list(dict.fromkeys(looped)))
    unmet = [
        (module.name, required.name)
        for module in modules
        for required in module.requires
        if required.name not in names
    ]
    if unmet:
        missing = [
            f"`{name}` requires `{required}`, which isn't selected"
            for name, required in unmet
        ]
        message = (
            f"{'; '.join(missing)}. Add each, or drop what requires it too: lup "
            "never adds or drops a module behind the declaration's back"
        )
        about = [name for pair in unmet for name in pair]
        raise ProjectError(message, about=list(dict.fromkeys(about)))
    doors = Doors.of(modules)
    unshadowed(modules)
    return Resolved(
        modules=modules,
        doors=doors,
        looks=Looks.of(modules),
        kinds=kept(modules),
    )


def unshadowed(modules: list[Module]) -> None:
    """Raise `ProjectError` where a module's name, as it's typed, is one a tool, command or view of the core takes, naming both: `lup` types the core's at its top level and every other module by its name, so both would be typed alike."""
    top = {
        name: method
        for module in modules
        if module.name == Core.name
        for name, method in typed_methods(module).items()
    }
    shadowed = [
        (module.name, top[typed(module.name)])
        for module in modules
        if module.name != Core.name and typed(module.name) in top
    ]
    if shadowed:
        clashes = [
            f"the module `{name}` and {method.door.called} of the core's typed so"
            for name, method in shadowed
        ]
        message = (
            "`lup` types the core's tools, commands and views at its top level, "
            f"and every other module by its name, so {'; '.join(clashes)} would "
            "be typed alike: rename the module"
        )
        raise ProjectError(message, about=[name for name, _ in shadowed])


def cycle(module: type[Module], trail: list[type[Module]]) -> list[str] | None:
    """Return the names around a cycle of requirements reached from `module`, after `trail`, or none where there's no cycle."""
    if module in trail:
        return [each.name for each in trail[trail.index(module) :]] + [module.name]
    return next(
        (
            found
            for required in module.requires
            if (found := cycle(required, [*trail, module])) is not None
        ),
        None,
    )


def kept(modules: list[Module]) -> Kinds:
    """Return the kinds of record `modules` keep in the store; raise `ProjectError` where two modules declare one kind, naming both."""
    held = {module.name: module.held(Recorded) for module in modules}
    owners = {
        kind: [name for name, kinds in held.items() if kind in kinds]
        for kinds in held.values()
        for kind in kinds
    }
    shared = {kind: names for kind, names in owners.items() if len(names) > 1}
    if shared:
        said = "; ".join(
            f"`{kind.declared()}` by {listed(names)}" for kind, names in shared.items()
        )
        message = f"a kind of record is one module's, and two declare {said}"
        raise ProjectError(
            message,
            about=list(
                dict.fromkeys(name for names in shared.values() for name in names)
            ),
        )
    return Kinds(
        nodes=[kind for kind in owners if issubclass(kind, Node)],
        edges=[kind for kind in owners if issubclass(kind, Edge)],
    )
