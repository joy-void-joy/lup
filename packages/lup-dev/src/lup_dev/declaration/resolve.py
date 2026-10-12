"""A declaration resolved: each kind's entries, from the modules it selects.

Resolving applies every layer in order, then reads each kind from the modules that
hold it, by the kind's type (`docs/declaration.md`, *What a module is*):
- `Core` is held, and every module a selected module requires is selected,
  without a cycle; lup never adds or drops a module behind the project's back;
- names are per kind and shared across modules, so one name from two modules
  fails, naming both, but for a path pattern, which from two modules is one
  pattern, a requirement, which is checked for each module needing it, and an
  exemption, which each module keeps for its own paths;
- entries placed `before=` or `after=` another go there, whichever module holds
  it, and the rest keep the order of their modules;
- the runner comes from the one module holding one, `Plain()` where none does.

Rule selections are kept as recorded, one per module, for the engine to resolve.
"""

from typing import TYPE_CHECKING, Literal

from lup.types import Model
from lup_dev.catalog.gate import Step
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Named, listed
from lup_dev.declaration.kinds import (
    Exemption,
    Exemptions,
    Gate,
    Paths,
    Pytest,
    Rules,
    TestRoots,
)
from lup_dev.declaration.module import Module
from lup_dev.declaration.modules.core import Core
from lup_dev.declaration.modules.shipped import default, shipped
from lup_dev.declaration.requirements import Needed
from lup_dev.declaration.runner import Plain, Runner

if TYPE_CHECKING:
    from lup_dev.declaration.project import Project


class PathRoles(Model, extra="forbid"):
    """Each role's patterns from every selected module, as the roles read them."""

    protected: list[str]
    operator_documents: list[str]
    excluded: list[str]
    scratch: list[str]
    docs: list[str]
    data: list[str]
    source_trees: list[str]
    python: list[str]
    conftest: list[str]


class Selected(Model):
    """One module's rule selection, as it's recorded, for the engine to resolve."""

    module: str
    """The module's name."""
    rules: Rules


class Part[K](Model):
    """One module's value of a kind, and the module's own default for it."""

    module: str
    """The module's name."""
    value: K
    default: K | None
    """The module's own default for the field holding it: what `Kind.default()`
    and `Kind()` start from there."""


class Owned(Model):
    """An entry's name, and the module holding it."""

    module: str
    name: str


class Resolved(Model):
    """A declaration resolved: what its readers need, each kind from every module."""

    modules: list[Module]
    """The selected modules in order, every layer applied, each field a layer set
    credited to that layer (`Module.origins`)."""
    paths: PathRoles
    gate: list[Step]
    """The gate's steps, in the order they run."""
    rules: list[Selected]
    """Each module's rule selection, as recorded."""
    exempt: list[Exemption]
    tests: list[Pytest]
    conditions: list[str]
    """The Python modules declaring the conditions a `defer` waits on, by name."""
    runner: Runner
    requirements: list[Needed]
    """Every selected module's requirements, its runner's among them."""
    asks: Literal["every", "protected"]


def parts[K](modules: list[Module], kind: type[K]) -> list[Part[K]]:
    """Return every module's values of `kind`, in the order of the modules."""
    return [
        Part(
            module=module.name,
            value=value,
            default=default if isinstance(default := info.default, kind) else None,
        )
        for module in modules
        for field, info in type(module).model_fields.items()
        if isinstance(value := getattr(module, field), kind)
    ]


def distinct(label: str, owned: list[Owned]) -> None:
    """Raise `ProjectError` where two modules give a kind's entry the same name."""
    clashes = [
        f"`{one.name}` from `{one.module}` and `{other.module}`"
        for at, one in enumerate(owned)
        for other in owned[at + 1 :]
        if one.name == other.name
    ]
    if clashes:
        message = (
            f"{label}: two modules name one entry alike, {'; '.join(clashes)}. "
            "Names are shared across modules: drop or rename one"
        )
        raise ProjectError(message)


def held[E](
    kind: Named[E], found: list[Part[Named[E]]], label: str, *, shared: bool = True
) -> list[E]:
    """Resolve each module's selection of a kind, check its names, and order it.

    With `shared`, a name is shared across modules, so one from two modules fails;
    without, each module's entries stand beside the others', as an exemption's do.
    """

    def own(part: Part[Named[E]]) -> list[E]:
        if part.default is None:
            return []
        return [each.entry for each in part.default.resolve([], [])]

    resolved = [part.value.resolve(own(part), own(part)) for part in found]
    if shared:
        distinct(
            label,
            [
                Owned(module=part.module, name=kind.named(each.entry))
                for part, placed in zip(found, resolved, strict=True)
                for each in placed
            ],
        )
    return kind.ordered([each for placed in resolved for each in placed])


def checked(modules: list[Module]) -> list[Module]:
    """Return `modules` once `Core` and every module required are among them."""
    if not any(type(module) is Core for module in modules):
        message = (
            "`Core` is required: every project holds lup's `Core`, and this "
            "declaration's modules leave it out"
        )
        raise ProjectError(message)

    none: list[str] = []

    def cycle(module: type[Module], trail: list[type[Module]]) -> list[str]:
        if module in trail:
            return [each.name for each in trail[trail.index(module) :]] + [module.name]
        return next(
            (
                found
                for required in module.requires
                if (found := cycle(required, [*trail, module]))
            ),
            none,
        )

    looped = next(
        (found for module in modules if (found := cycle(type(module), []))), none
    )
    if looped:
        around = " requires ".join(f"`{name}`" for name in looped)
        message = f"Modules can't require each other in a cycle: {around}"
        raise ProjectError(message)
    names = [module.name for module in modules]
    missing = [
        f"`{module.name}` requires `{required.name}`, which isn't selected"
        for module in modules
        for required in module.requires
        if required.name not in names
    ]
    if missing:
        message = (
            f"{'; '.join(missing)}. Add each, or drop what requires it too: lup "
            "never adds or drops a module behind the declaration's back"
        )
        raise ProjectError(message)
    return modules


def resolve(project: Project) -> Resolved:
    """Resolve `project`'s declaration, or raise `ProjectError` saying what's wrong."""
    selection = project.modules
    modules = checked(selection.ordered(selection.resolve(default(), shipped())))

    def role(name: str) -> list[str]:
        patterns = [
            pattern
            for part in parts(modules, Paths)
            for pattern in part.value.resolve(part.default or Paths())[name]
        ]
        return list(dict.fromkeys(patterns))

    runners = parts(modules, Runner)
    if len(runners) > 1:
        holding = listed([part.module for part in runners])
        message = f"{holding} each give a runner, and a project runs its tools one way"
        raise ProjectError(message)
    runner = runners[0].value if runners else Plain()
    needed = [
        Needed(module=module.name, requirement=requirement)
        for module in modules
        for requirement in module.requirements
    ]
    brought = [
        Needed(module=part.module, requirement=requirement)
        for part in runners
        for requirement in part.value.requirements
    ]
    return Resolved(
        modules=modules,
        paths=PathRoles.model_validate({name: role(name) for name in Paths.roles()}),
        gate=held(Gate(), parts(modules, Gate), "The gate's steps"),
        rules=[
            Selected(module=part.module, rules=part.value)
            for part in parts(modules, Rules)
        ],
        exempt=held(
            Exemptions(), parts(modules, Exemptions), "Exemptions", shared=False
        ),
        tests=held(TestRoots(), parts(modules, TestRoots), "Test roots"),
        conditions=[
            module.conditions for module in modules if module.conditions is not None
        ],
        runner=runner,
        requirements=[*needed, *brought],
        asks=project.asks,
    )
