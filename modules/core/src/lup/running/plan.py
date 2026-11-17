"""A project's plan: what the program on the operator's machine reads of a declaration, never running it.

A declaration is code, so it's loaded in a container, where running a branch's
code is harmless, and what comes out is this: each part of each module, what it
holds, and the doors it serves, with the tools a session is told of and the
files the declaration loaded. The program starts containers from it and routes
calls by it; a part holding something runs apart, from a commit the operator
approved, and the files are what an approval shows (`README.md` here, *The
plan*).
"""

from collections import Counter
from typing import Annotated, Literal

from pydantic import AfterValidator

from lup.doors.parts import Holds
from lup.doors.tool import ToolSpec
from lup.types import Model


def checked(name: str) -> str:
    """Return `name` where it's safe as a directory's name and a container's, as the machine makes both from it: ASCII letters, digits, `-`, `_` and `.`, starting with a letter or a digit.

    Raise `ValueError` otherwise, so a name a project chose never reaches a
    path or podman's command line as anything but one name.

    >>> checked("harmon")
    'harmon'
    >>> checked("../operator")
    Traceback (most recent call last):
    ...
    ValueError: `../operator` isn't a name lup runs: ASCII letters, digits, `-`, `_` and `.`, starting with a letter or a digit
    """
    allowed = name.isascii() and all(each.isalnum() or each in "-_." for each in name)
    if not allowed or not name or name.startswith(("-", "_", ".")):
        message = (
            f"`{name}` isn't a name lup runs: ASCII letters, digits, `-`, `_` "
            "and `.`, starting with a letter or a digit"
        )
        raise ValueError(message)
    return name


type Name = Annotated[str, AfterValidator(checked)]
"""A name the machine makes a directory's or a container's name from: a
repository's, a module's, a part's."""


class Doorway(Model):
    """One method a part serves behind a door, as calls to it are routed: its door, its name, and who may call it."""

    door: Literal["tool", "service", "action", "command"]
    name: str
    parties: list[str]
    """Who may call it, by each party's class name: `Agent`, `Codebase`."""

    def said(self, module: str) -> str:
        """Name it as a refusal does, with its module where its name is the module's alone: a tool's or a service's name is the project's, a command's or an action's its module's.

        >>> Doorway(door="command", name="keep", parties=[]).said("hosting")
        'the command `keep` of `hosting`'
        """
        match self.door:
            case "tool" | "service":
                return f"the {self.door} `{self.name}`"
            case "command" | "action":
                return f"the {self.door} `{self.name}` of `{module}`"


class PartPlan(Model):
    """One part of a module, as the program runs it: where it runs follows from what it holds."""

    module: Name
    """Its module's name."""
    part: Name
    """Its class's name, which names it among its module's parts."""
    holds: Holds
    doorways: list[Doorway] = []

    def apart(self) -> bool:
        """Say whether it runs apart: in a container of its own, from approved code, or on the operator's machine."""
        return self.holds.anything()

    def named(self) -> str:
        """Name it as a refusal or an approval does: `harmon.Bot`."""
        return f"{self.module}.{self.part}"


class Plan(Model):
    """A project's declaration, as the program on the operator's machine reads it: its parts, what each holds and serves, and the files it loaded."""

    format: int = 1
    """The version of the plan's shape, which a program reading another
    refuses in words, saying how to update (`Versioned`)."""
    parts: list[PartPlan] = []
    tools: list[ToolSpec] = []
    """What a session is told of each tool the project's modules serve."""
    files: list[str] = []
    """The files of the project loading the declaration imported, relative to
    its root: what a part's container runs, and what an approval shows the
    diff of."""

    def together(self) -> list[PartPlan]:
        """Return the parts holding nothing, which run in the project's own container."""
        return [each for each in self.parts if not each.apart()]

    def apart(self) -> list[PartPlan]:
        """Return the parts holding something, each run apart from approved code."""
        return [each for each in self.parts if each.apart()]

    def ties(self) -> list[str]:
        """Name each method two parts serve under the same name: a tool's or a service's across the project, a command's or an action's within its module.

        The machine refuses a plan with one, rather than routing a call to
        whichever part comes first, since the plan comes from the code it
        plans.
        """
        served = Counter(
            way.said(each.module) for each in self.parts for way in each.doorways
        )
        return [said for said, count in served.items() if count > 1]

    def serving(
        self, door: str, name: str, module: str | None = None
    ) -> PartPlan | None:
        """Return the part serving the method named `name` behind `door`, of the module named `module` where its name is the module's alone; none where no part does."""
        return next(
            (
                each
                for each in self.parts
                if (module is None or each.module == module)
                and any(way.door == door and way.name == name for way in each.doorways)
            ),
            None,
        )
