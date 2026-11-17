"""lup's front door: what a project's declaration and a module's code import.

`import lup` gives the bases every model starts from, the root of lup's errors,
the declaration's grammar (`Module`, `Modules`, `Project`, and the selections and
layers a module's parts are written in, and the profiles a repository's sessions
run on), and the doors a module's methods are
reached through (`lup.tool`, `lup.service`, `lup.command`, `lup.on`,
`lup.promise`), with the parties a method's `by` names, lup's events,
and the parts a module is made of (`Part`, listed in its `Parts`, holding its
`Secret`s and its `Data`); and the shell's view door (`lup.view`), the blocks a
view answers, and the kinds a module declares for them (`Tones`, `Folds`,
`Marks`); and the guidance door (`lup.guidance`), a module's section of
what a session is told at its start. The core's environment side
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
from lup.doors.command import command
from lup.doors.door import DoorError, RefusedError
from lup.doors.events import Event, Starting, Stopping
from lup.doors.on import on
from lup.doors.parties import Agent, Codebase, Operator, Party
from lup.doors.parts import Data, Part, Parts, Secret
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
from lup.shell.kinds import FoldKind, Folds, MarkKind, Marks, Tone, Tones
from lup.shell.view import view
from lup.testing.promise import promise
from lup.told.door import guidance
from lup.told.guidance import GuidanceError
from lup.types import JsonObject, Model, MutableModel, Settings
lazy from lup import programs
lazy from lup.core import Core

__all__ = [
    "Agent",
    "BlockError",
    "Blocks",
    "Chosen",
    "Code",
    "Codebase",
    "Core",
    "Data",
    "Diff",
    "DoorError",
    "Event",
    "FileBytes",
    "FileText",
    "Fold",
    "FoldKind",
    "Folds",
    "Gauge",
    "GuidanceError",
    "JsonObject",
    "Layer",
    "Lend",
    "Lending",
    "Line",
    "LupError",
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
    "Profile",
    "Profiles",
    "Project",
    "ProjectError",
    "RefusedError",
    "RuntimeDefaults",
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
    "chosen",
    "command",
    "guidance",
    "on",
    "programs",
    "promise",
    "service",
    "tool",
    "view",
]
