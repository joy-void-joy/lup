"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
the declaration's grammar (`Module`, `Modules`, `Project`, and the selections and
layers a module's parts are written in, and the profiles a repository's sessions
run on), and the doors a module's methods are
reached through (`lup.tool`, `lup.service`, `lup.action`, `lup.command`,
`lup.on`, `lup.promise`), with the parties a method's `by` names, lup's events,
and the classes a module groups them in (`Part`, listed in its
`Parts`, holding its `Secret`s). The core's environment side
(`lup.environment`) isn't among it, and nothing here imports it.

Running a program is `lup.programs` (`lup.programs.run`), kept under its own
name: alone, its names would read as lup's own (`lup.run`).

`Core` and `lup.programs` are imported when first used: `Core` lists its
submodules' promises, which import `lup` itself.
"""

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Layer, Named, Selection
from lup.declaration.module import Module, Modules
from lup.declaration.profiles import (
    Chosen,
    Lend,
    Lending,
    Profile,
    Profiles,
    RuntimeDefaults,
    chosen,
)
from lup.declaration.project import Project
from lup.doors.action import action
from lup.doors.command import command
from lup.doors.door import DoorError, RefusedError
from lup.doors.events import Event, Starting, Stopping
from lup.doors.on import on
from lup.doors.parties import Agent, Code, Operator, Party
from lup.doors.parts import Part, Parts, Secret
from lup.doors.service import UncarriedError, service
from lup.doors.tool import tool
from lup.errors import LupError
from lup.testing.promise import promise
from lup.types import JsonObject, Model, MutableModel, Settings
lazy from lup import programs
lazy from lup.core import Core

__all__ = [
    "Agent",
    "Chosen",
    "Code",
    "Core",
    "DoorError",
    "Event",
    "JsonObject",
    "Layer",
    "Lend",
    "Lending",
    "LupError",
    "Model",
    "Module",
    "Modules",
    "MutableModel",
    "Named",
    "Operator",
    "Part",
    "Parts",
    "Party",
    "Profile",
    "Profiles",
    "Project",
    "ProjectError",
    "RefusedError",
    "RuntimeDefaults",
    "Secret",
    "Selection",
    "Settings",
    "Starting",
    "Stopping",
    "UncarriedError",
    "action",
    "chosen",
    "command",
    "on",
    "programs",
    "promise",
    "service",
    "tool",
]
