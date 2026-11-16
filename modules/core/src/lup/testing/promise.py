"""`@lup.promise`: what someone can count on, its docstring saying it, and its body checking it.

A promise is a method behind a door, in a class a module lists in its
`serving`, of one of two shapes, told apart by what it takes:
- **a law**, `def name(self, step: Step[State]) -> bool`: a statement about
  every moment, a predicate over one step, which the harness checks after every
  step of every run (`README.md` here, *Laws*);
- **a scenario**, `async def name(self, by: Testing) -> None`: a story through
  the harness, asserting where it ends, with what it explores drawn from the
  harness (`by.any(Kind)`).
"""

import inspect
from typing import TYPE_CHECKING, ClassVar, Concatenate, overload, override

from pydantic import BaseModel

from lup.doors.door import (
    Door,
    DoorError,
    Function,
    Served,
    Taken,
    shaped,
    spelled,
    taking,
)
from lup.doors.parties import Party
from lup.testing.harness import Step, Testing

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from lup.doors.door import Annotation


def state_of(annotation: Annotation) -> type[BaseModel] | None:
    """Return the state a law's step reads, `State` in `Step[State]`; none where the annotation is no step naming a model.

    >>> from lup.types import Model
    >>> class Count(Model):
    ...     count: int
    >>> state_of(Step[Count]) is Count, state_of(Step), state_of(Count)
    (True, None, None)
    """
    if not (isinstance(annotation, type) and issubclass(annotation, Step)):
        return None
    # lup: ignore("dict-literal-key", why="pydantic lists a model's fields in a dict by name, and `before` is one `Step` itself declares")
    state = annotation.model_fields["before"].annotation
    return state if isinstance(state, type) and issubclass(state, BaseModel) else None


class PromiseDoor(Door):
    """A promise's door: the harness checks the method, a law over every step or a scenario through the harness.

    `@lup.promise` is this door, put on the method it decorates. A law is
    called by the harness as a predicate, a scenario is handed the harness as
    `by`; no other party calls either.
    """

    called: ClassVar[str] = "a promise"
    default: ClassVar[list[type[Party]]] = [Testing]

    @override
    def shaped(self, function: Function) -> None:
        """Raise `DoorError` where `function` can't be a promise: a law takes a step and isn't async, a scenario takes the harness alone and is.

        Each is typed and has a docstring, which is the promise.
        """
        name = function.__qualname__
        taken = list(inspect.signature(function).parameters)[1:]
        if inspect.iscoroutinefunction(function):
            shaped(function, by_alone=True)
            if taken != ["by"]:
                message = (
                    f"the scenario `{name}` takes {', '.join(taken)}: a scenario "
                    "takes the harness, `by: Testing`, alone, and draws what it "
                    "explores from it; a law takes a step, and isn't async"
                )
                raise DoorError(message)
            return
        taking(function)
        if len(taken) != 1:
            message = (
                f"the law `{name}` takes {', '.join(taken)}: a law takes one step, "
                "`step: Step[State]`, alone, so it can't drive lup"
            )
            raise DoorError(message)

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a law's or a scenario's: a step naming a model in, a verdict out; or the harness in, nothing out."""
        if taken.model is None:
            self.scenario(taken)
            return
        if state_of(taken.model.annotation) is None:
            message = (
                f"the law `{taken.qualified}` takes {taken.spelled_model()}: a law "
                "takes a step naming the state it reads, `Step[State]`, a model a "
                "door of the module that only reads answers"
            )
            raise DoorError(message)
        if taken.returned is not bool:
            message = (
                f"the law `{taken.qualified}` returns {spelled(taken.returned)}: a "
                "law returns whether it holds, `bool`"
            )
            raise DoorError(message)

    def scenario(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a scenario's: the harness in, as `by`, nothing out."""
        annotation = None if taken.by is None else taken.by.annotation
        if annotation is not Testing:
            message = (
                f"the scenario `{taken.qualified}` takes `by` typed "
                f"{spelled(annotation)}: a promise is checked by the harness, "
                "`by: Testing`"
            )
            raise DoorError(message)
        if taken.returned is not None:
            message = (
                f"the scenario `{taken.qualified}` returns "
                f"{spelled(taken.returned)}: a scenario asserts what it promises, "
                "and returns nothing"
            )
            raise DoorError(message)

    def law(self, taken: Taken) -> type[BaseModel] | None:
        """Return the state a law taking what `taken` says reads; none where it's a scenario."""
        return None if taken.model is None else state_of(taken.model.annotation)

    @overload
    def __call__[S, V: BaseModel, **P](
        self, method: Callable[Concatenate[S, Step[V], P], bool], /
    ) -> Served[S, Concatenate[Step[V], P], bool]: ...
    @overload
    def __call__[S, **P](
        self, method: Callable[Concatenate[S, Testing, P], Awaitable[None]], /
    ) -> Served[S, Concatenate[Testing, P], Awaitable[None]]: ...
    def __call__[S, R: Awaitable[None] | bool, **P](
        self, method: Callable[Concatenate[S, P], R], /
    ) -> Served[S, P, R]:
        """Return `method` behind this door."""
        return Served(method, self)


@overload
def promise[S, V: BaseModel, **P](
    method: Callable[Concatenate[S, Step[V], P], bool], /
) -> Served[S, Concatenate[Step[V], P], bool]: ...
@overload
def promise[S, **P](
    method: Callable[Concatenate[S, Testing, P], Awaitable[None]], /
) -> Served[S, Concatenate[Testing, P], Awaitable[None]]: ...
def promise[S, R: Awaitable[None] | bool, **P](
    method: Callable[Concatenate[S, P], R], /
) -> Served[S, P, R]:
    """Make a method a promise: its docstring says what someone can count on, and its body checks it.

    A law, `def name(self, step: Step[State]) -> bool`, says whether it holds
    over one step, and the harness checks it after every step of every run; a
    scenario, `async def name(self, by: Testing) -> None`, tells a story
    through the harness, asserting, and draws what it explores from it
    (`by.any(Kind)`). A run that breaks either is shrunk to the smallest that
    does.
    """
    return Served(method, PromiseDoor())
