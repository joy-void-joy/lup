"""A module, one part of lup or of a project, and `Modules`, the selection of them.

A module is a `Module` subclass: its name, the modules it requires and what it
needs from outside the project as class attributes, its docstring as its one
sentence, and its parts and settings as fields whose defaults are the module's own
(`docs/declaration.md`, *What a module is*).

A module is a layer. Wherever it's written, in `.add` or `.edit` or bound to a
name, it means the module below with the fields it set (pydantic's
`model_fields_set`) changed: a selection it set composes over below's, any other
field it set replaces below's, and every field it didn't set stays as below has it.
Where nothing is below, below is the module's own defaults. Each field a layer set
is credited to that layer, by its place in the chain of `Modules`' verbs and its
reason, so the overview can show where every value came from.
"""

from collections.abc import Collection
from inspect import cleandoc
from itertools import takewhile
from types import UnionType
from typing import ClassVar, Self, TypeAliasType, get_args, get_origin, override

from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Edit, Of, Placed, Selection
from lup_dev.declaration.kinds import Paths
from lup_dev.declaration.requirements import Requirement


class Origin(Model):
    """Which layer last set one of a module's fields, and why."""

    field: str
    position: int | None = None
    """The layer's place in the chain of `Modules`' verbs: 0 for its start, then
    one for each verb; none while the module isn't placed in one."""
    why: str | None = None
    """The reason given with that layer, or with the `.edit` that set the field."""


class Origins(Model):
    """Which layer last set each field of a module that a layer set."""

    each: list[Origin] = []

    def of(self, field: str) -> Origin:
        """Return the origin of `field`, a blank one where no layer is credited."""
        return next(
            (origin for origin in self.each if origin.field == field),
            Origin(field=field),
        )

    def updated(self, origins: list[Origin]) -> Origins:
        """Return these origins with `origins` in place of the same fields'."""
        fields = [origin.field for origin in origins]
        kept = [origin for origin in self.each if origin.field not in fields]
        return Origins(each=[*kept, *origins])


def plain(annotation: type | UnionType | TypeAliasType | None) -> bool:
    """Say whether a field's type is a plain collection, optional or not.

    A `str` or `bytes` is a value, not a collection of its characters.

    >>> [plain(list[str]), plain(dict[str, int] | None), plain(str), plain(int)]
    [True, True, False, False]
    """
    match annotation:
        case TypeAliasType():
            return plain(annotation.__value__)
        case UnionType():
            return any(plain(each) for each in get_args(annotation))
        case _:
            kind = get_origin(annotation) or annotation
            if not isinstance(kind, type) or issubclass(kind, str | bytes):
                return False
            return issubclass(kind, Collection)


class Module(Model, extra="forbid"):
    """A part of lup or of a project: what it brings, taken away when it's dropped.

    Subclass it to declare one, as lup's own are declared:

    >>> class Narration(Module):
    ...     '''Turning a page into an episode.'''
    ...
    ...     name = "narration"
    >>> Narration.sentence()
    'Turning a page into an episode.'
    """

    name: ClassVar[str]
    """How the module is named in `Modules`' verbs: `.drop("python")`."""
    requires: ClassVar[list[type[Module]]] = []
    """The modules it can't work without, which a selection holding it must hold."""
    requirements: ClassVar[list[Requirement]] = []
    """What it needs from outside the project's Python environment."""

    conditions: str | None = None
    """The Python module declaring the conditions a `defer` waits on, by its dotted
    name (`audiobook.conditions`); a part any module may fill."""
    origins: Origins = Origins()
    """Which layer last set each field a layer set: lup's record, kept by `.edit`
    and by `Modules` as it places the module, never written in a declaration."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a module without a name or a sentence, or with a plain collection.

        Every collection in a module is a selection: a layer would replace a
        plain list whole, so a base couldn't be extended without restating it.
        """
        super().__pydantic_init_subclass__(**kwargs)
        declared = cls.__name__
        if not isinstance(getattr(cls, "name", None), str):
            message = f"`{declared}` has no `name`, which `Modules`' verbs know it by"
            raise ProjectError(message)
        if not cls.__doc__:
            message = f"`{declared}` has no docstring, which is its one sentence"
            raise ProjectError(message)
        required = [field for field, info in cls.model_fields.items() if info.is_required()]
        if required:
            message = (
                f"`{declared}` gives {', '.join(f'`{field}`' for field in required)} "
                "no default: a module added with nothing set stands on its own defaults"
            )
            raise ProjectError(message)
        collections = [
            field for field, info in cls.model_fields.items() if plain(info.annotation)
        ]
        if collections:
            message = (
                f"`{declared}` holds {', '.join(f'`{field}`' for field in collections)} "
                "as a plain collection: a layer would replace it whole, so a base "
                "couldn't be extended without restating it. Make each a selection: a "
                "kind of `lup_dev.declaration.kinds`, or a `Named` selection of "
                "its own entries"
            )
            raise ProjectError(message)

    @classmethod
    def sentence(cls) -> str:
        """Return the module's one sentence: its docstring's first paragraph."""
        lines = (line.strip() for line in cleandoc(cls.__doc__ or "").splitlines())
        return " ".join(takewhile(bool, lines))

    def changed(self) -> list[str]:
        """List the fields this module's layers set, in the order they're declared."""
        return [
            field
            for field in type(self).model_fields
            if field in self.model_fields_set and field != "origins"
        ]

    def over(self, below: Self) -> Self:
        """Return this module as a layer over `below`: the fields it set, on below's.

        A selection it set composes over below's; any other field it set replaces
        below's. Every field it didn't set stays as below has it, credited to the
        layer that set it there.
        """
        changed = self.changed()
        update = {
            field: value.over(getattr(below, field))
            if issubclass(type(value := getattr(self, field)), Selection | Paths)
            else value
            for field in changed
        }
        origins = below.origins.updated([self.origins.of(field) for field in changed])
        return below.model_copy(update={**update, "origins": origins})

    def stamped(self, position: int | None, why: str | None) -> Self:
        """Credit each field this module set to the layer at `position`, for `why`.

        A field an `.edit` on the module already credits keeps its reason, and
        its place once it has one.
        """

        def credited(field: str) -> Origin:
            origin = self.origins.of(field)
            return Origin(
                field=field,
                position=position if origin.position is None else origin.position,
                why=why if origin.why is None else origin.why,
            )

        origins = self.origins.updated([credited(field) for field in self.changed()])
        return self.model_copy(update={"origins": origins})

    def edited(self, module: Self, position: int | None, why: str | None) -> Self:
        """Return this module with `module` on it, as the layer at `position`.

        `module` must be of this module's class: one of another class goes in its
        place with `.replace`, which says so in the declaration.
        """
        if type(module) is not type(self):
            mine = type(self).__name__
            message = (
                f"`.edit` puts a `{type(module).__name__}` on `{mine}` "
                f"`{self.name}`; a module of another class goes in its place with "
                f'`.replace("{self.name}", …)`'
            )
            raise ProjectError(message)
        return module.stamped(position, why).over(self)

    def edit(self, module: Self, why: str | None = None) -> Self:
        """Return this module with `module` as a layer on it.

        The fields `module` set change, as a layer over this one, and the rest
        stay as they are here.
        """
        return self.edited(module, None, why)


class Modules(Selection[Module]):
    """The modules a project is made of, each named by its `name`.

    `Modules.default()` is lup's default modules, `Modules.all()` every one lup
    ships, and `Modules.only(…)` an exact list of modules, each with its settings.
    """

    @override
    def named(self, entry: Module) -> str:
        return entry.name

    @classmethod
    def only(cls, *modules: Module) -> Self:
        """Start from these modules and no other: a later release's don't come in."""
        return cls.starting(Of(entries=list(modules)))

    def edit(self, module: Module, why: str | None = None) -> Self:
        """Put `module` as a layer on the module of its name, which must be there."""
        return self.then(Edit(entry=module, why=why))

    @override
    def placed(self, placed: Placed[Module]) -> Placed[Module]:
        """Return a module placed in the chain, over its own defaults."""
        module = placed.entry.stamped(placed.position, placed.why)
        return placed.model_copy(update={"entry": module.over(type(module)())})

    @override
    def edited(self, below: Placed[Module], layer: Placed[Module]) -> Placed[Module]:
        """Return the module `below` with `layer`'s module on it, where it was."""
        module = below.entry.edited(layer.entry, layer.position, layer.why)
        return below.model_copy(update={"entry": module})
