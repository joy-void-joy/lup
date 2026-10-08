"""A project's declaration, as far as judging writes reads it.

A project names its declaration in `pyproject.toml` (`[tool.lup] project =
"audiobook.lup_project:project"`); without one, the defaults apply. This minimal
`Project` holds only what the judge reads: the test roots, the protected paths,
and the module declaring the project's conditions. The declaration piece grows it
(`DESIGN.md`, *How lup reaches a project*).
"""

import importlib
import sys
import tomllib
from contextlib import contextmanager
from importlib.metadata import EntryPoint
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from pydantic import Field

from lup.types import Model
from lup_dev.catalog.paths import Paths
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout

if TYPE_CHECKING:
    from collections.abc import Generator


class ProjectError(LupDevError):
    """The project's declaration can't be found or isn't a `Project`."""


class Protected(Model):
    """The paths every write to asks the operator about, as patterns from the root.

    Patterns are matched whole, `**` spanning any number of directories
    (`PurePath.full_match`).
    """

    patterns: list[str]

    @classmethod
    def default(cls) -> Protected:
        """Return lup's own protected paths, which every project starts from.

        They're data, in `lup_dev.catalog.paths`, with the reason for each.

        >>> Protected.default().matching(PurePath("packages/lup/pyproject.toml"))
        '**/pyproject.toml'
        """
        return cls(patterns=Paths().protected)

    def add(self, *patterns: str) -> Protected:
        """Return these protected paths with `patterns` added.

        >>> Protected(patterns=["a"]).add("tests/spec/**").patterns
        ['a', 'tests/spec/**']
        """
        return Protected(patterns=[*self.patterns, *patterns])

    def matching(self, path: PurePath) -> str | None:
        """Return the first pattern `path` matches, or none where it's not protected."""
        return next(
            (pattern for pattern in self.patterns if path.full_match(pattern)), None
        )


class Pytest(Model):
    """A root pytest collects tests from, and the file names it collects there."""

    root: Path
    """The directory, relative to the worktree's root."""
    files: list[str] = ["test_*.py", "*_test.py"]
    """pytest's `python_files` patterns, its defaults unless the project says."""


class Project(Model):
    """What a project declares about itself that judging writes reads."""

    tests: list[Pytest] | None = None
    """The test roots; none leaves it to pytest's configuration in `pyproject.toml`."""
    protected: Protected = Field(default_factory=Protected.default)
    """The paths every write to asks about: lup's defaults and the project's own."""
    excluded: list[str] = []
    """Paths held to nothing, as patterns from the root, matched as `protected` is.

    No lup rules, no ruff or pyright findings reported, and writes allowed. A
    path both protected and excluded still asks: exclusion takes the checks
    away, never the operator's review.
    """
    conditions: str | None = None
    """The module declaring the project's conditions, by its dotted name.

    A `# lup: defer(when=…)` names one of the `Condition` instances it binds.
    """


class Declared(Model):
    """A project's declaration, with the file it was read from."""

    project: Project
    source: Path | None = None
    """The declaration's file, relative to the worktree; none for the defaults."""


class Pyproject(Model):
    """The parts of a `pyproject.toml` the declaration's loader reads."""

    class Tool(Model):
        """`[tool]`, for the tables lup reads."""

        class Lup(Model):
            """`[tool.lup]`."""

            project: str | None = None
            """Where the declaration is, as `package.module:name`."""

        class Uv(Model):
            """`[tool.uv]`, for its workspace."""

            class Workspace(Model):
                """`[tool.uv.workspace]`: the projects a uv workspace holds."""

                members: list[str] = []

            workspace: Workspace = Workspace()

        lup: Lup = Lup()
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
def importable(roots: list[Path]) -> Generator[None]:
    """Put `roots` first on the import path for the duration, then restore it."""
    before = list(sys.path)
    sys.path[:0] = [str(root) for root in roots]
    try:
        yield
    finally:
        sys.path[:] = before


def load(root: Path) -> Declared:
    """Load the declaration the worktree at `root` names, or the defaults.

    Raise `ProjectError` where `[tool.lup] project` names something that can't be
    imported or isn't a `Project`: a declaration that silently fell back to the
    defaults would judge with the wrong roles.
    """
    pyproject = Pyproject.read(CheckoutLayout(root=root).pyproject)
    reference = pyproject.tool.lup.project
    if reference is None:
        return Declared(project=Project())
    entry = EntryPoint(name="project", value=reference, group="lup")
    with importable(import_roots(root, pyproject)):
        try:
            declared = entry.load()
        except (ImportError, AttributeError) as missing:
            message = f"`[tool.lup] project = {reference!r}` can't be loaded: {missing}"
            raise ProjectError(message) from missing
    if not isinstance(declared, Project):
        message = f"`{reference}` is a {type(declared).__name__}, not a `Project`"
        raise ProjectError(message)
    module = importlib.import_module(entry.module)
    source = Path(module.__file__) if module.__file__ else None
    if source is None or not source.is_relative_to(root):
        return Declared(project=declared)
    return Declared(project=declared, source=source.relative_to(root))
