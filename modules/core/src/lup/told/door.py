"""`@lup.guidance`: what the method answers is its module's section of what a session is told at its start.

A section is Markdown, written in Python: a template string (`t"…"`) whose
values are its module's typed settings (`self.module.…`), so pyright checks
each name it reads, a rename follows it, and a section that can't render fails
at the gate rather than at a session's start; or plain `str`. Its values stay
apart from its text until it's rendered, so what each runtime spells its own
way is a typed value the runtimes' adapter spells, and no section names a
runtime. It takes nothing, or `by` alone, the session it's told to, where a
section differs by session, and answers nothing where it has nothing to say to
that session.
"""

import inspect
from string.templatelib import Template
from types import UnionType
from typing import TYPE_CHECKING, ClassVar, Concatenate, get_args, override

from lup.doors.door import Door, DoorError, Served, Taken, shaped, spelled
from lup.doors.parties import Agent, Party, said

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from lup.doors.door import Function


class GuidanceDoor(Door):
    """A section's door: lup renders the method as a session starts, its module's section of what the session is told.

    `@lup.guidance` is this door, put on the method it decorates.
    """

    called: ClassVar[str] = "a section of guidance"
    default: ClassVar[list[type[Party]]] = [Agent]

    @override
    def shaped(self, function: Function) -> None:
        """Raise `DoorError` where `function` can't be a section: async, taking nothing, or `by`, the session it's told to, alone, typed, with a docstring."""
        taken = list(inspect.signature(function).parameters)[1:]
        if taken not in ([], ["by"]):
            named = ", ".join(f"`{each}`" for each in taken)
            message = (
                f"the section `{function.__qualname__}` takes {named}: a section of "
                "guidance takes nothing, or `by`, the session it's told to, alone, "
                "and reads what it says from its module's settings"
            )
            raise DoorError(message)
        shaped(function, by_alone=True, nothing=True)

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a section's: Markdown out, a template (`t"…"`) or `str`."""
        returned = taken.returned
        answers = get_args(returned) if isinstance(returned, UnionType) else [returned]
        if not all(each in (str, Template) for each in answers):
            message = (
                f"the section `{taken.qualified}` returns {spelled(returned)}: a "
                'section of guidance returns its Markdown, a template (`t"…"`), '
                "or `str`"
            )
            raise DoorError(message)

    @override
    def parties(self, taken: Taken) -> list[type[Party]]:
        """Return who a section is told to: the parties its `by` names, or any agent.

        Raise `DoorError` where `by` names a party that isn't a session, an
        `Agent` or a party deriving from it.
        """
        parties = super().parties(taken)
        others = [each for each in parties if not issubclass(each, Agent)]
        if others:
            message = (
                f"the section `{taken.qualified}` is told to {said(others)}: a "
                "section of guidance is told to a session, `by: Agent`, or a party "
                "deriving from it"
            )
            raise DoorError(message)
        return parties

    def __call__[S, T: str | Template, **P](
        self, method: Callable[Concatenate[S, P], Awaitable[T]], /
    ) -> Served[S, P, Awaitable[T]]:
        """Return `method` behind this door."""
        return Served(method, self)


def guidance[S, T: str | Template, **P](
    method: Callable[Concatenate[S, P], Awaitable[T]], /
) -> Served[S, P, Awaitable[T]]:
    """Make a method its module's section of guidance: what a session is told at its start, in Markdown.

    It's async, takes nothing, or `by: Agent` alone where what it says differs
    by session, and answers a template (`t"…"`) of its module's settings, or
    `str`; nothing where it has nothing to say to that session. A module's
    sections come in its parts' order, after the modules before it in the
    declaration.
    """
    return GuidanceDoor()(method)
