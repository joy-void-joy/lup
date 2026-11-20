"""A project's plan: what the program on the operator's machine reads of a declaration, never running it.

A declaration is code, so it's loaded in a container, where running a branch's
code is harmless, and what comes out is this: each part of each module, what it
holds, the file it's defined in, and the doors it serves, with the tools a
session is told of and the files the declaration loaded. The program starts
containers from it and routes calls by it; a part holding something runs apart,
in a container of its own (`README.md` here, *The plan*).
"""

from collections import Counter
from typing import Annotated, Literal, get_args

from pydantic import StringConstraints

from lup.doors.parts import Holds
from lup.doors.tool import ToolSpec
from lup.rooms.packages import Package
from lup.types import JsonObject, Model

CORE = "core"
"""The core's name: the module every project holds, whose tools, commands and
views `lup` types at its top level (`lup init`), since the core is lup itself,
where every other module's go under its name (`lup hosting open`)."""

type Offerable = Literal["tool", "command", "view"]
"""The doors the command line offers a method behind: a service is code's."""


def typed(name: str) -> str:
    """Return a method's or a module's name as the command line types it: each `_` a `-`, lowered, typer's way.

    >>> typed("concern_view"), typed("hosting")
    ('concern-view', 'hosting')
    """
    # lup: ignore("string-replace", why="typer's own rule for a command's name (`typer.main.get_command_name`), said once here for the plan, the declaration's check and the command line, so a name the core takes and a module's are compared as both are typed")
    return name.lower().replace("_", "-")


type Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
"""A name the machine makes a directory's or a container's name from: a
repository's, a module's, a part's. ASCII letters, digits, `-`, `_` and `.`,
starting with a letter or a digit, so a name a project chose never reaches a
path or podman's command line as anything but one name: never `../operator`,
`.hidden` or `-rm`."""


class Doorway(Model):
    """One method a part serves behind a door, as calls to it are routed and the command line offers it: its door, its name, who may call it, and what it takes."""

    door: Literal["tool", "service", "command", "view"]
    name: str
    parties: list[str]
    """Who may call it, by each party's class name: `Agent`, `Codebase`."""
    description: str = ""
    """Its docstring, which describes it: a command's help."""
    input_schema: JsonObject = {}
    """The JSON Schema of the model it takes, or of each where it takes a list
    of it: what the command line reads its arguments and options from."""
    here: bool = False
    """Whether it's a command `lup` answers where it's typed, over the
    declaration of the worktree it's typed in, never carried to where the
    project runs (`@lup.command(here=True)`)."""

    def typed(self) -> str:
        """Name it as the command line types it (`typed`)."""
        return typed(self.name)

    def said(self, module: str) -> str:
        """Name it as a refusal does, with its module where its name is the module's alone: a tool's or a service's name is the project's, a command's or a view's its module's.

        >>> Doorway(door="command", name="keep", parties=[]).said("hosting")
        'the command `keep` of `hosting`'
        """
        match self.door:
            case "tool" | "service":
                return f"the {self.door} `{self.name}`"
            case "command" | "view":
                return f"the {self.door} `{self.name}` of `{module}`"


class ModulePlan(Model):
    """One of the project's modules, as the command line names it: its name, and its one sentence."""

    name: str
    description: str = ""


class PartPlan(Model):
    """One part of a module, as the program runs it: where it runs follows from what it holds."""

    module: Name
    """Its module's name."""
    part: Name
    """Its class's name, which names it among its module's parts."""
    holds: Holds
    source: str | None = None
    """The file its class is defined in, relative to the project's root: what
    an approval calls out where it changes; none where it's outside the root,
    as a part lup ships is."""
    doorways: list[Doorway] = []
    hears: list[str] = []
    """The events its methods run at, each by its class's name, which the
    machine carries a session's to it."""

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
    modules: list[ModulePlan] = []
    """The project's modules, in order."""
    parts: list[PartPlan] = []
    tools: list[ToolSpec] = []
    """What a session is told of each tool the project's modules serve."""
    packages: list[Package] = []
    """What its modules add to the standard machine in its sessions' rooms
    (`lup.rooms`)."""
    files: list[str] = []
    """The files of the project loading the declaration imported, relative to
    its root: what an approval may point at, never what it approves, which is
    the commit whole."""

    def together(self) -> list[PartPlan]:
        """Return the parts holding nothing, which run in the project's own container, but those run in each session's own room."""
        return [each for each in self.parts if not each.apart() and not each.holds.room]

    def rooms(self) -> list[PartPlan]:
        """Return the parts run in each session's own room."""
        return [each for each in self.parts if each.holds.room]

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

    def shadowed(self) -> list[str]:
        """Name each module whose name, as it's typed, one of the core's tools, commands or views takes: `lup` types those at its top level and every other module's under its name, so both would be typed alike.

        The machine refuses a plan with one, as one with a tie; resolving the
        declaration refuses it first.

        >>> core = PartPlan(
        ...     module=CORE,
        ...     part="Inboxes",
        ...     holds=Holds(),
        ...     doorways=[Doorway(door="command", name="clear", parties=["Operator"])],
        ... )
        >>> Plan(modules=[ModulePlan(name="clear")], parts=[core]).shadowed()
        ['clear']
        """
        top = {
            way.typed(): way
            for each in self.parts
            if each.module == CORE
            for way in each.doorways
            if way.door in get_args(Offerable.__value__)
        }
        return [
            each.name
            for each in self.modules
            if each.name != CORE and typed(each.name) in top
        ]

    def only(self, modules: list[str]) -> Plan:
        """Return the plan of the modules named in `modules` alone: what a project's own command offers, of the modules it's given.

        >>> Plan(modules=[ModulePlan(name="core"), ModulePlan(name="harmon")]).only(
        ...     ["harmon"]
        ... ).modules
        [ModulePlan(name='harmon', description='')]
        """
        return self.model_copy(
            update={
                "modules": [each for each in self.modules if each.name in modules],
                "parts": [each for each in self.parts if each.module in modules],
            }
        )

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
