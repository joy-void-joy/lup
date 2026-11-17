"""A project's plan: what the program on the operator's machine reads of a declaration, never running it.

A declaration is code, so it's loaded in a container, where running a branch's
code is harmless, and what comes out is this: each part of each module, what it
holds, and the doors it serves, with the tools a session is told of and the
files the declaration loaded. The program starts containers from it and routes
calls by it; a part holding something runs apart, from a commit the operator
approved, and the files are what an approval shows (`README.md` here, *The
plan*).
"""

from typing import Literal

from lup.doors.parts import Holds
from lup.doors.tool import ToolSpec
from lup.types import Model


class Doorway(Model):
    """One method a part serves behind a door, as calls to it are routed: its door, its name, and who may call it."""

    door: Literal["tool", "service", "action", "command"]
    name: str
    parties: list[str]
    """Who may call it, by each party's class name: `Agent`, `Code`."""


class PartPlan(Model):
    """One part of a module, as the program runs it: where it runs follows from what it holds."""

    module: str
    """Its module's name."""
    part: str
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
