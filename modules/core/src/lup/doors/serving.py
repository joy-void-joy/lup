"""What a module serves: its methods, grouped in `ModuleServing` classes it lists in its `serving` field.

A class only groups methods, each behind one of lup's doors: it narrows `module`
to its own module's class, so its methods read that module's settings with
their types, and it's made afresh, with its module, for each call. What a method
reaches outside its module, it reaches through another door, so a module's code
imports `lup` alone (`README.md` here, *What a module serves*).
"""

from typing import override

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Named
from lup.declaration.module import Module
from lup.types import Model


class ModuleServing(Model):
    """A class of a module's methods, each behind one of lup's doors.

    A subclass narrows `module` to its own module's class, so its methods read
    that module's settings with their types. It holds no state of its own: it's
    made afresh, with its module, for each call, so what it's set with goes in its
    module's fields.
    """

    module: Module
    """The module serving it, every layer applied."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a field of the class's own: it's made afresh for each call, with its module alone."""
        super().__pydantic_init_subclass__(**kwargs)
        own = [f"`{field}`" for field in cls.model_fields if field != "module"]
        if own:
            message = (
                f"`{cls.__name__}` holds {', '.join(own)}: a class of a module's "
                "methods is made afresh for each call, with its module alone, so "
                "what it's set with goes in its module's fields"
            )
            raise ProjectError(message)


class Serving(Named[type[ModuleServing]]):
    """The classes of a module's methods, each named by its class's name.

    `Serving.of(EchoServing)`; a module may hold several, and a project drops
    one by its class's name, `Serving().drop("EchoServing")`. Each is made with
    the module holding it, so its class narrows `module` to that module's class.
    """

    @override
    def named(self, entry: type[ModuleServing]) -> str:
        return entry.__name__
