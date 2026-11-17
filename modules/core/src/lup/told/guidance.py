"""A session's guidance as its project's modules render it: each section, in the declaration's order, and the room it may take.

The smallest ceiling among the runtimes lup starts sessions on is 40,000 bytes
of what a session is told at its start (`Room.ceiling`). A project's modules'
guidance may take 30,000 of it (`Guidance.project`), the rest left for what its
gate can't see: the operator's own section, which git ignores, and what a
session's start adds. lup's own modules at their defaults may take 20,000
(`Guidance.shipped`), leaving a project 10,000 for its own (`README.md` here,
*Room*).
"""

from typing import ClassVar

from lup.errors import LupError
from lup.types import Model


class GuidanceError(LupError):
    """A section of guidance doesn't render, or the guidance doesn't fit its room: `about` names its modules."""


class Section(Model):
    """One section of a session's guidance: what one method of a module said."""

    module: str
    """Its module, by its name."""
    method: str
    """The method that said it, by its name within its class:
    `RunnerGuide.running`."""
    text: str
    """What it said, in Markdown, with no blank lines around it."""

    def size(self) -> int:
        """Return its size in bytes, as a runtime counts it.

        >>> Section(module="m", method="P.s", text="Run `uv`.").size()
        9
        """
        return len(self.text.encode())


class Room(Model):
    """How much of the smallest runtime's ceiling a share of guidance may take, in bytes, and what the rest is left for."""

    # lup: defer(issue=5, why="the runtimes' adapter says each runtime's ceiling, and a session's start refuses guidance past the one it runs on, once sessions are started")
    ceiling: int = 40_000
    """The smallest ceiling among the runtimes lup starts sessions on, on what a
    session is told at its start: 10,000 estimated tokens at 4 bytes each
    (`docs/field-notes.md`)."""
    most: int
    """What the share may take."""
    left: str
    """What the rest of the ceiling is left for, as a refusal says it."""


class Guidance(Model):
    """What a session is told at its start of its project's modules: each section that said something, in the declaration's order.

    >>> told = Guidance(sections=[
    ...     Section(module="a", method="P.s", text="## A"),
    ...     Section(module="b", method="Q.s", text="## B"),
    ... ])
    >>> told.text().splitlines(), told.size()
    (['## A', '', '## B'], 10)
    """

    project: ClassVar[Room] = Room(
        most=30_000,
        left="the operator's own section, which git ignores, and what a session's "
        "start adds",
    )
    """What a project's modules, lup's and its own, may take: a quarter of the
    ceiling is left for what its gate can't see."""
    shipped: ClassVar[Room] = Room(
        most=20_000,
        left="a project's own sections, the operator's own, and what a session's "
        "start adds",
    )
    """What lup's own modules may take, at their defaults: as much again as a
    project's room leaves is left for a project's own sections."""

    sections: list[Section] = []

    def text(self) -> str:
        """Return the guidance as one Markdown document: its sections, a blank line between each."""
        return "\n\n".join(each.text for each in self.sections)

    def size(self) -> int:
        """Return its size in bytes as one document, as a runtime counts it."""
        return len(self.text().encode())

    def by_module(self) -> dict[str, int]:
        """Return the size of each module's sections, in bytes, by its name, the largest first.

        >>> Guidance(sections=[
        ...     Section(module="a", method="P.s", text="a"),
        ...     Section(module="b", method="Q.s", text="bbbb"),
        ...     Section(module="a", method="P.t", text="aa"),
        ... ]).by_module()
        {'b': 4, 'a': 3}
        """
        modules = dict.fromkeys(each.module for each in self.sections)
        sizes = {
            module: sum(each.size() for each in self.sections if each.module == module)
            for module in modules
        }
        return dict(sorted(sizes.items(), key=lambda each: each[1], reverse=True))

    def within(self, room: Room) -> None:
        """Raise `GuidanceError` where the guidance takes more than `room` leaves it, naming its modules, the largest first."""
        size = self.size()
        if size <= room.most:
            return
        sizes = self.by_module()
        largest = ", ".join(f"`{module}` {each:,}" for module, each in sizes.items())
        message = (
            f"the guidance is {size:,} bytes, past the {room.most:,} it may take of "
            f"the {room.ceiling:,} the smallest runtime takes, the rest left for "
            f"{room.left}. By module, the largest first: {largest}. Shorten a "
            "section: say what exists, and where the rest is looked up"
        )
        raise GuidanceError(message, about=list(sizes))
