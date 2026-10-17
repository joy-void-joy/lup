"""A method run at a moment: `@lup_hook`, as `@lup_tool` makes a method a tool.

`@lup_hook` marks an async method taking one pydantic model, what's known of the
moment, as run at one or several moments, named by `on`, or by the method's name
where `on` is left out. What the moments are, and which model describes one, is
the class's whose methods they are: the library only marks them, and a class of
hooks checks the names against its own moments (`lup_dev`'s `ModuleHooks`).

A `Hook` is a read-only property of its class, as a tool written as a method is
(`Method`): read through an instance, it's that instance's function of the
moment; read through the class, it says which moments it runs at.
"""

import inspect
from functools import partial
from typing import TYPE_CHECKING, Self, overload

from pydantic import BaseModel

from lup.tools.tool import ToolError, is_model, refuse_taken

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class Hook[S, M: BaseModel](property):
    """A method run at its moments: bound to an instance when read through it, itself when read through the class."""

    def __init__(
        self, function: Callable[[S, M], Awaitable[None]], moments: list[str]
    ) -> None:
        """Hold the function, which takes the instance and the moment, and the moments it runs at."""
        self.function = function
        self.moments = moments
        super().__init__(self.bound)

    def __set_name__(self, owner: type, name: str) -> None:
        """Refuse a name its class gives a field: the field would hide the hook."""
        refuse_taken(owner, name, "hook")

    def bound(self, instance: S) -> Callable[[M], Awaitable[None]]:
        """Return the function of the moment, called with `instance` first."""
        return partial(self.function, instance)

    @overload
    def __get__(self, instance: None, owner: type[S] | None = None) -> Self: ...
    @overload
    def __get__(
        self, instance: S, owner: type[S] | None = None
    ) -> Callable[[M], Awaitable[None]]: ...
    def __get__(
        self, instance: S | None, owner: type[S] | None = None
    ) -> Self | Callable[[M], Awaitable[None]]:
        """Return the function bound to `instance`, or this hook where read through its class."""
        if instance is None:
            return self
        return self.bound(instance)


def hooks(owner: type[BaseModel]) -> dict[str, list[str]]:
    """Return each hook of `owner`, or of a class it derives from, by its attribute's name, with the moments it runs at.

    A hook a subclass declares again stands in its base's place.
    """
    return {
        name: value.moments
        for klass in reversed(owner.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, Hook)
    }


def marked[S, M: BaseModel](
    function: Callable[[S, M], Awaitable[None]], on: str | list[str] | None
) -> Hook[S, M]:
    """Return `function` as a hook run at `on`, or at the moment its name names.

    Raise `ToolError` where it isn't a method taking one pydantic model besides
    `self`, or where `on` names no moment.
    """
    name = function.__name__
    parameters = list(inspect.signature(function).parameters.values())
    match parameters:
        case [inspect.Parameter(name="self"), parameter] if is_model(
            parameter.annotation
        ):
            pass
        case _:
            message = (
                f"the hook `{name}` must be a method taking one pydantic model, "
                "what's known of the moment, besides `self`"
            )
            raise ToolError(message)
    moments = [name] if on is None else [on] if isinstance(on, str) else on
    if not moments:
        message = f"the hook `{name}` runs at no moment: `on` names none"
        raise ToolError(message)
    return Hook[S, M](function, moments)


@overload
def lup_hook[S, M: BaseModel](
    function: Callable[[S, M], Awaitable[None]],
) -> Hook[S, M]: ...
@overload
def lup_hook[S, M: BaseModel](
    *, on: str | list[str]
) -> Callable[[Callable[[S, M], Awaitable[None]]], Hook[S, M]]: ...
def lup_hook[S, M: BaseModel](
    function: Callable[[S, M], Awaitable[None]] | None = None,
    *,
    on: str | list[str] | None = None,
) -> Hook[S, M] | Callable[[Callable[[S, M], Awaitable[None]]], Hook[S, M]]:
    """Mark a method as run at a moment: the one its name names, or those `on` names.

    `@lup_hook` on `async def stopped(self, moment: Moment)` runs it when the
    launch stops; `@lup_hook(on=["launched", "stopped"])` runs a method of any
    name at both.
    """
    if function is not None:
        return marked(function, on)

    def marking(method: Callable[[S, M], Awaitable[None]]) -> Hook[S, M]:
        return marked(method, on)

    return marking
