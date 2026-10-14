"""Finding a project's declaration at a root, and importing it.

The declaration is `lup_project.py` at the root, or the package `lup_project/`
once the project's own modules outgrow one file, binding `project`, a `Project`.
Nothing points at it: the loader looks there (`docs/declaration.md`, *Where it
lives*). Without either, the defaults apply; with both, or with one that can't be
imported or binds no `Project`, the load fails, never falling back to the defaults,
which would judge with the wrong roles. The same function reads a worktree's root
and a directory a commit was exported to.

Beside it, the person's own layer, `lup_project.local.py`, which git ignores, is
loaded after it and layered on top, in the same grammar
(`docs/related-repositories.md`, decision 7). The judge and a launch read the
copy trust on launch approved, put beside the commit's export.
"""

import importlib
import importlib.util
import sys
import tomllib
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import applied, set_fields
from lup_dev.declaration.project import Project
from lup_dev.layout import CheckoutLayout

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import ModuleType


class Declared(Model):
    """A project's declaration, with the file it was read from."""

    project: Project
    """The project's declaration, with the person's own layer on top where
    there's one."""
    source: Path | None = None
    """The declaration's file, relative to the root: `lup_project.py`, or the
    package's `__init__.py`; none for the defaults."""
    local: Path | None = None
    """The person's own layer, relative to the root, `lup_project.local.py`,
    where one was read and layered on top; none otherwise."""


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


def read_by_import(path: PurePath) -> bool:
    """Say whether importing a declaration from a directory may read the file at `path`.

    Its Python modules, and each project file, which says where a workspace's
    packages are (`import_roots`): what a commit's export holds so its declaration
    can be imported. Never the person's own layer, which git ignores: one a
    commit holds anyway would run unapproved, so only the copy trust on launch
    approved is put beside an export.

    >>> [read_by_import(PurePath(each)) for each in ["a/b.py", "pyproject.toml", "c.md"]]
    [True, True, False]
    >>> read_by_import(PurePath("lup_project.local.py"))
    False
    """
    layout = CheckoutLayout(root=Path())
    if path == layout.local_declaration:
        return False
    return path.suffix in [".py", ".pyi"] or path.name == layout.pyproject.name


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


def bound(module: ModuleType, shown: Path) -> Project:
    """Return the `Project` the module read from `shown` binds as `project`.

    Raise `ProjectError` where it binds none, or something else.
    """
    declared = getattr(module, "project", None)
    if declared is None:
        message = f"`{shown}` binds no `project`"
        raise ProjectError(message)
    if not isinstance(declared, Project):
        # Each class by its module and qualified name, so a `Project` of the
        # declaration's own, or from another copy of `lup_dev`, is told apart.
        message = (
            f"`project` in `{shown}` is a "
            f"`{type(declared).__module__}.{type(declared).__qualname__}`, "
            f"not a `{Project.__module__}.{Project.__qualname__}`"
        )
        raise ProjectError(message)
    return declared


def executed(path: Path, name: str) -> ModuleType:
    """Run the Python file at `path` as the module `name`, which no import names.

    The person's own layer is `lup_project.local.py`, whose name holds a dot, so
    it's run from its path. It's kept in `sys.modules` while it runs, as an
    import would be, so the models it defines resolve their annotations there.
    Raise `ProjectError` where it can't be run.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        message = f"`{path.name}` isn't a Python file lup can run"
        raise ProjectError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as failure:
        message = f"`{path.name}` can't be imported: {failure}"
        raise ProjectError(message) from failure
    return module


def load(root: Path) -> Declared:
    """Load the declaration at `root`, the person's own layer on top where there's one, or the defaults where there's neither.

    The person's own layer, `lup_project.local.py` beside the declaration,
    binds `project` too, a `Project` written as a layer on the project's: what
    it sets changes the project's, as a module layers (`applied`), so
    `Modules().add(…)` adds to the project's modules. It runs in the same import
    as the declaration, so it can import the project's own modules and edit
    them. Raise `ProjectError` where both forms of the declaration are there, or
    where the declaration or the person's layer can't be imported or binds no
    `Project`. Whatever importing one raises (a name the installed `lup_dev`
    lacks, conflict markers, a module edited with another's class) is that.
    """
    layout = CheckoutLayout(root=root)
    package = layout.declaration_package
    local = layout.local_declaration
    match [layout.declaration.is_file(), package.is_dir()]:
        case [False, False]:
            source = None
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
    if source is not None and not source.is_file():
        message = f"`{package.name}/` holds no `{source.name}` binding `project`"
        raise ProjectError(message)
    if source is None and not local.is_file():
        return Declared(project=Project())
    shown = None if source is None else source.relative_to(root)
    roots = import_roots(root, Pyproject.read(layout.pyproject))
    with importable(roots, root, layout.declaration.stem):
        if shown is None:
            project = Project()
        else:
            try:
                module = importlib.import_module(layout.declaration.stem)
            except Exception as failure:
                message = f"`{shown}` can't be imported: {failure}"
                raise ProjectError(message) from failure
            project = bound(module, shown)
        if not local.is_file():
            return Declared(project=project, source=shown)
        mine = bound(
            executed(local, f"{layout.declaration.stem}_local"),
            local.relative_to(root),
        )
    return Declared(
        project=applied(mine, project, set_fields(mine)),
        source=shown,
        local=local.relative_to(root),
    )
