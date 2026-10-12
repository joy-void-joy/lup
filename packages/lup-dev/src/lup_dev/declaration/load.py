"""Finding a project's declaration at a root, and importing it.

The declaration is `lup_project.py` at the root, or the package `lup_project/`
once the project's own modules outgrow one file, binding `project`, a `Project`.
Nothing points at it: the loader looks there (`docs/declaration.md`, *Where it
lives*). Without either, the defaults apply; with both, or with one that can't be
imported or binds no `Project`, the load fails, never falling back to the defaults,
which would judge with the wrong roles. The same function reads a worktree's root
and a directory a commit was exported to.
"""

import importlib
import sys
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.project import Project
from lup_dev.layout import CheckoutLayout

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import ModuleType


class Declared(Model):
    """A project's declaration, with the file it was read from."""

    project: Project
    source: Path | None = None
    """The declaration's file, relative to the root: `lup_project.py`, or the
    package's `__init__.py`; none for the defaults."""


class Pyproject(Model):
    """The parts of a `pyproject.toml` the declaration's loader reads."""

    class Tool(Model):
        """`[tool]`, for uv's table."""

        class Uv(Model):
            """`[tool.uv]`, for its workspace."""

            class Workspace(Model):
                """`[tool.uv.workspace]`: the projects a uv workspace holds."""

                members: list[str] = []

            workspace: Workspace = Workspace()

        uv: Uv = Uv()

    tool: Tool = Tool()

    @classmethod
    def read(cls, path: Path) -> Pyproject:
        """Read `path`, or return an empty project file where there's none."""
        if not path.is_file():
            return cls()
        return cls.model_validate(tomllib.loads(path.read_text()))


def import_roots(root: Path, pyproject: Pyproject) -> list[Path]:
    """List where a project's modules are imported from, without its environment.

    The judge runs from its own installed copy, so the project's packages aren't
    on its path: the worktree's root and `src/`, and each uv workspace member and
    its `src/`.
    """
    members = [
        member
        for pattern in pyproject.tool.uv.workspace.members
        for member in sorted(root.glob(pattern))
    ]
    candidates = [root, root / "src", *members, *(member / "src" for member in members)]
    return [candidate for candidate in candidates if candidate.is_dir()]


@contextmanager
def importable(roots: list[Path], root: Path, name: str) -> Generator[None]:
    """Put `roots` first on the import path for the duration, then restore it.

    The modules imported meanwhile from the worktree at `root` are dropped from
    `sys.modules` afterwards. Every worktree's declaration is the module `name`,
    `lup_project`, and Python keeps a module once it's imported, so a second
    worktree's load in the same process would otherwise get the first's; one
    imported before from elsewhere is set aside meanwhile and put back after. No
    bytecode is written meanwhile: a `__pycache__/` the judge left in a worktree
    that doesn't ignore it would be judged at the next checkpoint as a file the
    session wrote.
    """
    before = list(sys.path)
    known = dict(sys.modules)
    aside = {
        each: module
        for each, module in known.items()
        if each == name or each.startswith(f"{name}.")
    }
    writes = sys.dont_write_bytecode
    for each in aside:
        del sys.modules[each]
    sys.path[:0] = [str(each) for each in roots]
    sys.dont_write_bytecode = True
    importlib.invalidate_caches()

    def within(module: ModuleType) -> bool:
        spec = module.__spec__
        if spec is None:
            return False
        places = [spec.origin, *(spec.submodule_search_locations or [])]
        return any(Path(place).is_relative_to(root) for place in places if place)

    try:
        yield
    finally:
        sys.path[:] = before
        sys.dont_write_bytecode = writes
        imported = [
            each
            for each, module in sys.modules.items()
            if each not in known and within(module)
        ]
        for each in imported:
            del sys.modules[each]
        sys.modules.update(aside)


def load(root: Path) -> Declared:
    """Load the declaration at `root`, or the defaults where there's none.

    Raise `ProjectError` where both forms are there, or where the one there can't
    be imported or binds no `Project`. Whatever importing it raises (a name the
    installed `lup_dev` lacks, conflict markers, a module edited with another's
    class) is that.
    """
    layout = CheckoutLayout(root=root)
    package = layout.declaration_package
    match [layout.declaration.is_file(), package.is_dir()]:
        case [False, False]:
            return Declared(project=Project())
        case [True, True]:
            message = (
                f"`{layout.declaration.name}` and `{package.name}/` are both at "
                f"{root}: the declaration is one or the other"
            )
            raise ProjectError(message)
        case [True, False]:
            source = layout.declaration
        case _:
            source = CheckoutLayout(root=package).package
    shown = source.relative_to(root)
    if not source.is_file():
        message = f"`{package.name}/` holds no `{source.name}` binding `project`"
        raise ProjectError(message)
    roots = import_roots(root, Pyproject.read(layout.pyproject))
    with importable(roots, root, layout.declaration.stem):
        try:
            module = importlib.import_module(layout.declaration.stem)
        except Exception as failure:
            message = f"`{shown}` can't be imported: {failure}"
            raise ProjectError(message) from failure
    declared = getattr(module, "project", None)
    if declared is None:
        message = f"`{shown}` binds no `project`"
        raise ProjectError(message)
    if not isinstance(declared, Project):
        message = f"`project` in `{shown}` is a `{type(declared).__name__}`, not a `Project`"
        raise ProjectError(message)
    return Declared(project=declared, source=shown)
