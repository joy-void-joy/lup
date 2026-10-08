"""Path roles: which role a path in a worktree has, the first that matches.

1. **protected:** the project's declaration and the protected paths
   (`Protected.default()` and the project's additions);
2. **operator:** the operator's documents, `DESIGN.md` and `AGENTS.md`;
3. **test:** a module pytest collects as a test, under a root it reads and matching
   its `python_files` patterns, or a `conftest.py` under such a root;
4. **scratch:** `tmp/` at any depth, and the saved versions under `.lup/`;
5. **docs:** Markdown files and `docs/`;
6. **data:** data formats outside a source tree;
7. **production:** everything else, so a file nobody classified is gated.

A protected Python module gets lup's rules as production code does: protection
adds the operator's review, it doesn't take the rules away. The table of what each
role gets is in `docs/judging-writes.md`, *What each change gets*.
"""

import tomllib
from pathlib import Path, PurePath
from typing import Literal

from lup.types import Model
from lup_dev.catalog.paths import Paths
from lup_dev.layout import CheckoutLayout
from lup_dev.project import Declared, Project, Pytest

type Role = Literal[
    "protected", "operator", "test", "scratch", "docs", "data", "production"
]
"""A path's role, which decides what a change to it gets."""


def matches(path: PurePath, patterns: list[str]) -> bool:
    """Say whether `path` matches any of `patterns`, each matched whole."""
    return any(path.full_match(pattern) for pattern in patterns)


class Roles(Model):
    """The role of every path in one worktree, from its project's declaration."""

    root: Path
    project: Project
    declaration: Path | None = None
    """The declaration's file, relative to the root, which is always protected."""
    paths: Paths = Paths()
    """lup's default patterns (`lup_dev.catalog.paths`)."""

    @classmethod
    def of(cls, root: Path, declared: Declared) -> Roles:
        """Classify the paths of the worktree at `root` by its declaration."""
        return cls(root=root, project=declared.project, declaration=declared.source)

    def role(self, path: Path) -> Role:
        """Return the role of `path`, relative to the root.

        >>> roles = Roles(root=Path("/nowhere"), project=Project())
        >>> [roles.role(Path(p)) for p in ["uv.lock", "AGENTS.md", "tmp/a.py", "x.py"]]
        ['protected', 'operator', 'scratch', 'production']
        """
        if path == self.declaration or self.project.protected.matching(path):
            return "protected"
        if matches(path, self.paths.operator_documents):
            return "operator"
        if self.is_test(path):
            return "test"
        if matches(path, self.paths.scratch):
            return "scratch"
        if matches(path, self.paths.docs):
            return "docs"
        data = matches(PurePath(path.name), self.paths.data)
        if data and not self.in_source_tree(path):
            return "data"
        return "production"

    def is_python(self, path: Path) -> bool:
        """Say whether `path` is a Python module, which the rules read."""
        return matches(PurePath(path.name), self.paths.python)

    def ruled(self, path: Path) -> bool:
        """Say whether lup's rules read `path`: a production or protected module.

        >>> roles = Roles(root=Path("/nowhere"), project=Project())
        >>> [roles.ruled(Path(p)) for p in ["a.py", ".claude/h.py", "tests/test_a.py"]]
        [True, True, False]
        """
        return self.is_python(path) and self.role(path) in ["production", "protected"]

    def checked(self, path: Path) -> bool:
        """Say whether pyright's and ruff's findings in `path` are reported.

        A module lup's rules read, or a test: tests are exempt from lup's rules,
        not from pyright and ruff.
        """
        return self.ruled(path) or (self.is_python(path) and self.role(path) == "test")

    def is_test(self, path: Path) -> bool:
        """Say whether pytest collects `path` as a test, or reads it as a conftest."""
        if not self.is_python(path):
            return False
        named = PurePath(path.name)
        roots = self.project.tests if self.project.tests is not None else []
        for pytest in roots or self.configured(path):
            if not path.full_match(str(pytest.root / "**")):
                continue
            if named.name == self.paths.conftest:
                return True
            if matches(named, pytest.files):
                return True
        return False

    def configured(self, path: Path) -> list[Pytest]:
        """Return the test roots pytest's configuration gives `path`.

        They come from the nearest `pyproject.toml` above it holding pytest's
        options (`[tool.pytest]` or `[tool.pytest.ini_options]`), nested projects
        included; with none, pytest collects from the worktree's root.
        """

        class Options(Model):
            """The options pytest reads from a `pyproject.toml` to find tests."""

            testpaths: list[str] = []
            python_files: list[str] | str | None = None

            def roots(self, base: Path) -> list[Pytest]:
                """Return the test roots these options give, relative to the worktree.

                `base` is where the `pyproject.toml` holding them sits; without
                `testpaths`, pytest collects from there.
                """
                match self.python_files:
                    case None:
                        files = Pytest(root=base).files
                    case str() as spaced:
                        files = spaced.split()
                    case list() as listed:
                        files = listed
                return [
                    Pytest(root=base / pattern, files=files)
                    for pattern in self.testpaths or ["."]
                ]

        class Table(Options):
            """`[tool.pytest]`: pytest 9's own table, or the older `ini_options`."""

            ini_options: Options | None = None

        class Tool(Model):
            """`[tool]`, for pytest's table."""

            pytest: Table | None = None

        class Pyproject(Model):
            """A `pyproject.toml`, for its `[tool]` table."""

            tool: Tool = Tool()

        for directory in path.parents:
            pyproject = CheckoutLayout(root=self.root / directory).pyproject
            if not pyproject.is_file():
                continue
            table = Pyproject.model_validate(tomllib.loads(pyproject.read_text()))
            match table.tool.pytest:
                case None:
                    continue
                case Table(ini_options=Options() as options):
                    return options.roots(directory)
                case Table() as options:
                    return options.roots(directory)
        return [Pytest(root=Path())]

    def in_source_tree(self, path: Path) -> bool:
        """Say whether `path` sits in a source tree: under `src/`, or in a package."""
        if matches(path, self.paths.source_trees):
            return True
        return any(
            CheckoutLayout(root=self.root / directory).package.is_file()
            for directory in path.parents
            if directory != Path()
        )
