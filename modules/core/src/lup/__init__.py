"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
and the declaration's grammar: `Module`, `Modules`, `Project`, and the selections
and layers a module's parts are written in. The core's environment side
(`lup.environment`) isn't among it, and nothing here imports it.
"""

from lup.declaration.core import Core
from lup.declaration.errors import ProjectError
from lup.declaration.grammar import Layer, Named, Selection
from lup.declaration.module import Module, Modules
from lup.declaration.project import Project
from lup.errors import LupError
from lup.types import JsonObject, Model, MutableModel, Settings

__all__ = [
    "Core",
    "JsonObject",
    "Layer",
    "LupError",
    "Model",
    "Module",
    "Modules",
    "MutableModel",
    "Named",
    "Project",
    "ProjectError",
    "Selection",
    "Settings",
]
