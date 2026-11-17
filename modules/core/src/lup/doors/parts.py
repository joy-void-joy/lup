"""A module's parts: the classes it lists in its `parts` field, each grouping methods behind lup's doors.

A part is made once where it runs, as its container starts, so it may keep what
it holds between calls: a connection, a cache, a count (`README.md` here,
*Parts*). What must outlast it, or be read by others, it keeps in the core's
store.

Where it runs follows from what it holds. A part holding nothing runs in its
project's container. One holding a secret (a field typed `Secret`), the
operator's machine (`machine=True`) or anything else only approved code may
hold (`approved=True`) runs in a container of its own, from a commit the
operator approved, with what it holds alone, or on the machine.
"""

from typing import ClassVar, Unpack, override

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Named
from lup.doors.door import DoorError, Method
from lup.types import Model, MutableModel
lazy from lup.declaration.module import Module


class Secret(Model):
    """A secret a class holds: a field typed `Secret`, filled where the class runs with the value the operator stored under the field's name.

    Its value is never shown or written out with the class: it's left out of
    how the class prints and of its JSON.

    >>> token = Secret(value="hunter2")
    >>> token, token.model_dump()
    (Secret(), {})
    """

    value: str = Field(repr=False, exclude=True)
    """The secret itself."""


class Holds(Model):
    """What a part holds, which only code the operator approved may: where it runs follows from it."""

    secrets: list[str] = []
    """The secrets it holds, by their names: its fields typed `Secret`."""
    machine: bool = False
    """Whether it runs on the operator's machine itself, outside any container."""
    approved: bool = False
    """Whether it holds something else only approved code may, as the store
    holds the operator's acts."""

    def anything(self) -> bool:
        """Say whether it holds anything, and so runs apart, from approved code."""
        return bool(self.secrets) or self.machine or self.approved


class Part(MutableModel, arbitrary_types_allowed=True):
    """A part of a module: its methods, each behind one of lup's doors, made once where it runs.

    A subclass that reads its module's settings declares `module`, typed as its
    module's class (`module: Echo`), and lup hands it the module, every layer
    applied. Its other fields are what it keeps while it runs, each with a
    default, but a `Secret`, which lup fills; what it holds says where it runs
    (`holds`).

    It says in its header what it holds beyond its secrets:
    `class Notices(Part, machine=True)` runs on the operator's machine,
    `class Store(Part, approved=True)` holds what only approved code may.
    """

    machine: ClassVar[bool] = False
    """Whether it runs on the operator's machine itself: its header's word."""
    approved: ClassVar[bool] = False
    """Whether it holds what only approved code may: its header's word."""

    def __init_subclass__(
        cls,
        *,
        machine: bool | None = None,
        approved: bool | None = None,
        **kwargs: Unpack[ConfigDict],
    ) -> None:
        """Keep what the class's header says it holds, a subclass keeping its base's where it says nothing."""
        super().__init_subclass__(**kwargs)
        if machine is not None:
            cls.machine = machine
        if approved is not None:
            cls.approved = approved

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a field of the class's own with no default, but a `Secret`, which lup fills, and a method named as a field, which the field would hide: lup makes the class with its module and its secrets alone."""
        super().__pydantic_init_subclass__(**kwargs)
        hidden = [
            f"`{field}`"
            for field, info in cls.model_fields.items()
            if isinstance(info.default, Method)
        ]
        if hidden:
            message = (
                f"`{cls.__name__}`'s method {', '.join(hidden)} takes the name of a "
                "field of its model, which hides it: name it otherwise"
            )
            raise DoorError(message, about=[cls.__name__])
        bare = [
            f"`{field}`"
            for field, info in cls.model_fields.items()
            if field != "module"
            and info.is_required()
            and info.annotation is not Secret
        ]
        if bare:
            message = (
                f"`{cls.__name__}` holds {', '.join(bare)} with no default: lup "
                "makes a part with its module and its "
                "secrets alone, so what it keeps starts from a default"
            )
            raise ProjectError(message, about=[cls.__name__])

    @classmethod
    def holds(cls) -> Holds:
        """Return what the class holds: its secrets, and what its header says."""
        return Holds(
            secrets=[
                field
                for field, info in cls.model_fields.items()
                if info.annotation is Secret
            ],
            machine=cls.machine,
            approved=cls.approved,
        )

    @classmethod
    def made(cls, module: Module, secrets: dict[str, str]) -> Part:
        """Make the class where it runs, with its module and the value of each secret it holds.

        Raise `ProjectError` where a secret it holds isn't given.
        """
        missing = [name for name in cls.holds().secrets if name not in secrets]
        if missing:
            message = (
                f"`{cls.__name__}` holds {', '.join(f'`{name}`' for name in missing)}, "
                "which nothing stored: the operator stores each under its name"
            )
            raise ProjectError(message, about=[cls.__name__])
        given: dict[str, Module | Secret] = {
            name: Secret(value=secrets[name]) for name in cls.holds().secrets
        }
        if "module" in cls.model_fields:
            given["module"] = module
        return cls.model_validate(given)

    @classmethod
    def admits(cls, module: Module) -> bool:
        """Say whether the class can be made with `module`: whether the `module` it declares, where it does, is typed as that module's class."""
        # lup: ignore("dict-literal-key", why="pydantic lists a model's fields in a dict by name, and `module` is the one lup hands a class")
        declared = cls.model_fields.get("module")
        if declared is None or declared.annotation is None:
            return True
        try:
            TypeAdapter[object](declared.annotation).validate_python(module)
        except ValidationError:
            return False
        return True


class Parts(Named[type[Part]]):
    """A module's parts, each named by its class's name.

    `Parts.of(EchoPart)`; a module may hold several, and a project drops one by
    its class's name, `Parts().drop("EchoPart")`. Each is made with the module
    holding it, so a part reading its module types `module` as that module's
    class.
    """

    @override
    def named(self, entry: type[Part]) -> str:
        return entry.__name__
