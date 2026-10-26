"""The environment for developing a project with agents.

`lup_dev` is what a project uses only while it's being developed, as opposed to
the library `lup`, which the project's production code imports. Everything it
raises descends from `lup_dev.errors.LupDevError`.

It's also the front door for a project's declaration: every name `lup_project.py`
imports is bound here, lup's modules among them (`docs/declaration.md`):

    from lup_dev import CodeRules, Modules, Project, Rules

    project = Project(
        modules=Modules.default().edit(CodeRules(rules=Rules().drop("tuple-shape"))),
    )

It imports the declaration's models and what they name (the catalog, the host
service's client, and `lup`'s sessions, adapters, rooms and tools), never the
judge's, the gate's or the code scanner's code, nor a runtime's SDK.
"""

from lup_dev.catalog.gate import Step
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Named
from lup_dev.declaration.kinds import (
    Actions,
    Credentials,
    Exemption,
    Exemptions,
    Gate,
    Guidance,
    Mounted,
    Package,
    Packages,
    Paths,
    Patterns,
    PyrightSource,
    Pytest,
    Refs,
    RemovedTools,
    Repositories,
    Repository,
    Rules,
    Section,
    Serving,
    Session,
    TestRoots,
)
from lup_dev.declaration.module import Module, Modules
from lup_dev.declaration.modules.code_rules import CodeRules
from lup_dev.declaration.modules.core import Core
from lup_dev.declaration.modules.python import Python
from lup_dev.declaration.package_managers.uv import Uv
from lup_dev.declaration.project import Project
from lup_dev.declaration.requirements import Requirement, Tools
from lup_dev.declaration.runner import (
    Interpreter,
    Plain,
    RoomEnvironment,
    RoomNeeds,
    RoomPlaces,
    Runner,
)
from lup_dev.declaration.serving import Agent, Asker, Lup, ModuleServing, Room
from lup_dev.private.module import Details, Private, Values

__all__ = [
    "Actions",
    "Agent",
    "Asker",
    "CodeRules",
    "Core",
    "Credentials",
    "Details",
    "Exemption",
    "Exemptions",
    "Gate",
    "Guidance",
    "Interpreter",
    "Lup",
    "Module",
    "ModuleServing",
    "Modules",
    "Mounted",
    "Named",
    "Package",
    "Packages",
    "Paths",
    "Patterns",
    "Plain",
    "Private",
    "Project",
    "ProjectError",
    "PyrightSource",
    "Pytest",
    "Python",
    "Refs",
    "RemovedTools",
    "Repositories",
    "Repository",
    "Requirement",
    "Room",
    "RoomEnvironment",
    "RoomNeeds",
    "RoomPlaces",
    "Rules",
    "Runner",
    "Section",
    "Serving",
    "Session",
    "Step",
    "TestRoots",
    "Tools",
    "Uv",
    "Values",
]
