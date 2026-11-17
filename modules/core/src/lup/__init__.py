"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
the declaration's grammar (`Module`, `Modules`, `Project`, and the selections and
layers a module's parts are written in), and the doors a module's methods are
reached through (`lup.tool`, `lup.service`, `lup.action`, `lup.command`,
`lup.on`, `lup.promise`), with the parties a method's `by` names, lup's events,
and the classes a module groups them in (`Part`, listed in its
`Parts`, holding its `Secret`s), and the records a module keeps in the store
(`Node`, `Edge`, listed in its `Recorded`). The core's environment side
(`lup.environment`) isn't among it, and nothing here imports it.

`Core` is imported when first used: it lists its submodules' promises, which
import `lup` itself.
"""

from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Layer, Named, Selection
from lup.declaration.module import Module, Modules
from lup.declaration.project import Project
from lup.doors.action import action
from lup.doors.command import command
from lup.doors.door import DoorError, RefusedError
from lup.doors.events import Event, Starting, Stopping
from lup.doors.on import on
from lup.doors.parties import Agent, Code, Operator, Party
from lup.doors.parts import Data, Part, Parts, Secret
from lup.doors.service import UncarriedError, service
from lup.doors.tool import tool
from lup.errors import LupError
from lup.store.records import Edge, Node, Recorded
from lup.testing.promise import promise
from lup.types import JsonObject, Model, MutableModel, Settings
lazy from lup.core import Core

__all__ = [
    "Agent",
    "Code",
    "Core",
    "Data",
    "DoorError",
    "Edge",
    "Event",
    "JsonObject",
    "Layer",
    "LupError",
    "Model",
    "Module",
    "Modules",
    "MutableModel",
    "Named",
    "Node",
    "Operator",
    "Part",
    "Parts",
    "Party",
    "Project",
    "ProjectError",
    "Recorded",
    "RefusedError",
    "Secret",
    "Selection",
    "Settings",
    "Starting",
    "Stopping",
    "UncarriedError",
    "action",
    "command",
    "on",
    "promise",
    "service",
    "tool",
]
