"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
the declaration's grammar (`Module`, `Modules`, `Project`, and the selections and
layers a module's parts are written in), and the doors a module's methods are
reached through (`lup.tool`, `lup.action`, `lup.command`, `lup.promise`), with
the parties a method's `by` names and the classes a module groups them in
(`ModuleServing`, listed in its `Serving`). The core's environment side
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
from lup.doors.parties import Agent, Operator, Party
from lup.doors.serving import ModuleServing, Serving
from lup.doors.tool import tool
from lup.errors import LupError
from lup.testing.promise import promise
from lup.types import JsonObject, Model, MutableModel, Settings
lazy from lup.core import Core

__all__ = [
    "Agent",
    "Core",
    "DoorError",
    "JsonObject",
    "Layer",
    "LupError",
    "Model",
    "Module",
    "ModuleServing",
    "Modules",
    "MutableModel",
    "Named",
    "Operator",
    "Party",
    "Project",
    "ProjectError",
    "RefusedError",
    "Selection",
    "Serving",
    "Settings",
    "action",
    "command",
    "promise",
    "tool",
]
