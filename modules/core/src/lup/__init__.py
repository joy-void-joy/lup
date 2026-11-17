"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
the declaration's grammar (`Module`, `Modules`, `Project`, and the selections and
layers a module's parts are written in), and the doors a module's methods are
reached through (`lup.tool`, `lup.service`, `lup.action`, `lup.command`,
`lup.on`, `lup.promise`), with the parties a method's `by` names, lup's events,
and the parts a module is made of (`Part`, listed in its `Parts`, holding its
`Secret`s and its `Data`); and the shell's view door (`lup.view`), the blocks a
view answers, and the kinds a module declares for them (`Tones`, `Folds`,
`Marks`). The core's environment side
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
from lup.doors.parties import Agent, Codebase, Machine, Operator, Party
from lup.doors.parts import (
    Data,
    Finished,
    Part,
    Parts,
    Program,
    ProgramError,
    Secret,
)
from lup.doors.service import UncarriedError, service
from lup.doors.tool import tool
from lup.errors import LupError
from lup.shell.blocks import (
    BlockError,
    Blocks,
    Code,
    Diff,
    FileBytes,
    FileText,
    Fold,
    Gauge,
    Line,
    Mark,
    Markdown,
    Offer,
    Span,
    Ticking,
    Viewing,
)
from lup.shell.draft import Commented, Commenting
from lup.shell.kinds import FoldKind, Folds, MarkKind, Marks, Tone, Tones
from lup.shell.view import view
from lup.testing.promise import promise
from lup.types import JsonObject, Model, MutableModel, Settings
lazy from lup.core import Core

__all__ = [
    "Agent",
    "BlockError",
    "Blocks",
    "Code",
    "Codebase",
    "Commented",
    "Commenting",
    "Core",
    "Data",
    "Diff",
    "DoorError",
    "Event",
    "FileBytes",
    "FileText",
    "Finished",
    "Fold",
    "FoldKind",
    "Folds",
    "Gauge",
    "JsonObject",
    "Layer",
    "Line",
    "LupError",
    "Machine",
    "Mark",
    "MarkKind",
    "Markdown",
    "Marks",
    "Model",
    "Module",
    "Modules",
    "MutableModel",
    "Named",
    "Offer",
    "Operator",
    "Part",
    "Parts",
    "Party",
    "Program",
    "ProgramError",
    "Project",
    "ProjectError",
    "RefusedError",
    "Secret",
    "Selection",
    "Settings",
    "Span",
    "Starting",
    "Stopping",
    "Ticking",
    "Tone",
    "Tones",
    "UncarriedError",
    "Viewing",
    "action",
    "command",
    "on",
    "promise",
    "service",
    "tool",
    "view",
]
