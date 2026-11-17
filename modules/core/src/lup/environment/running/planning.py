"""Planning a declaration: loading it where its code may run, and saying what the program on the operator's machine reads of it.

The plan is each module with its one sentence, each part of each module with
what it holds and the doors it serves, each with what it takes, the tools a
session is told of, and the files loading the declaration imported, relative
to the project's root (`lup/running/README.md`, *The plan*).
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lup.doors.command import CommandDoor
from lup.doors.door import is_model
from lup.doors.service import ServiceDoor
from lup.doors.tool import ToolDoor
from lup.environment.declaration import Resolved, load, resolve
from lup.running.plan import Doorway, ModulePlan, PartPlan, Plan
from lup.shell.view import ViewDoor

if TYPE_CHECKING:
    from lup.environment.doors import Entry, Serves


def planned(root: Path, declaration: Path) -> Plan:
    """Load the declaration at `declaration`, relative to `root`, resolve it, and return its plan.

    Raise `ProjectError` where it doesn't load or resolve.
    """
    resolved = resolve(load(root / declaration))
    loaded = dict.fromkeys([str(declaration), *files(root)])
    return plan_of(resolved, sorted(loaded))


def plan_of(resolved: Resolved, loaded: list[str]) -> Plan:
    """Return the plan of a declaration resolved, which loading imported `loaded`."""
    entries = resolved.doors.entries()
    return Plan(
        modules=[
            ModulePlan(name=each.name, description=each.sentence())
            for each in resolved.modules
        ],
        parts=[part_plan(each, entries) for each in resolved.doors.served],
        tools=resolved.doors.tools(),
        files=loaded,
    )


def part_plan(serves: Serves, entries: list[Entry]) -> PartPlan:
    """Return one part's plan: what it holds, and each method it serves behind a door a party calls."""
    return PartPlan(
        module=serves.module.name,
        part=serves.part.__name__,
        holds=serves.part.holds(),
        doorways=[
            way
            for entry in entries
            if entry.serves == serves and (way := doorway(entry)) is not None
        ],
    )


def doorway(entry: Entry) -> Doorway | None:
    """Return how calls to the method behind `entry` are routed; none behind a door no party calls, a hook's or a promise's."""
    match entry.method.door:
        case ToolDoor():
            door = "tool"
        case ServiceDoor():
            door = "service"
        case CommandDoor():
            door = "command"
        case ViewDoor():
            door = "view"
        case _:
            return None
    taken = entry.method.taken
    model = taken.one()
    return Doorway(
        door=door,
        name=entry.name,
        parties=[each.__name__ for each in entry.method.parties()],
        description=taken.description,
        input_schema=model.model_json_schema() if is_model(model) else {},
    )


def files(root: Path) -> list[str]:
    """Return each file under `root` that's imported in this process, relative to it, in order."""
    base = root.resolve()
    imported = [
        Path(origin).resolve()
        for module in list(sys.modules.values())
        if (origin := getattr(module, "__file__", None)) is not None
    ]
    return sorted(
        dict.fromkeys(
            str(each.relative_to(base))
            for each in imported
            if each.is_relative_to(base)
        )
    )
