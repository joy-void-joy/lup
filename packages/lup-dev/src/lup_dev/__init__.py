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

It imports only the declaration's models, so loading a declaration costs little
more than pydantic.
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
    Package,
    Packages,
    Paths,
    Patterns,
    Pytest,
    Refs,
    RemovedTools,
    Repositories,
    Repository,
    Rules,
    Section,
    Session,
    TestRoots,
)
from lup_dev.declaration.module import Module, Modules
from lup_dev.declaration.modules.code_rules import CodeRules
from lup_dev.declaration.modules.core import Core
from lup_dev.declaration.modules.python import Python
from lup_dev.declaration.project import Project
from lup_dev.declaration.requirements import Requirement, Tools
from lup_dev.declaration.runner import Interpreter, Plain, RoomNeeds, Runner, Uv

__all__ = [
    "Actions",
    "CodeRules",
    "Core",
    "Credentials",
    "Exemption",
    "Exemptions",
    "Gate",
    "Guidance",
    "Interpreter",
    "Module",
    "Modules",
    "Named",
    "Package",
    "Packages",
    "Paths",
    "Patterns",
    "Plain",
    "Project",
    "ProjectError",
    "Pytest",
    "Python",
    "Refs",
    "RemovedTools",
    "Repositories",
    "Repository",
    "Requirement",
    "RoomNeeds",
    "Rules",
    "Runner",
    "Section",
    "Session",
    "Step",
    "TestRoots",
    "Tools",
    "Uv",
]
