"""Path roles: which role a path in a worktree has, the first that matches.

1. **protected:** the project's declaration, and the paths its modules protect;
2. **operator:** the operator's documents, `DESIGN.md` and `AGENTS.md`;
3. **excluded:** what its modules hold to nothing;
4. **test:** a module under a test root and matching its file patterns, or a
   `conftest.py` under one: the roots the declaration names, or where it keeps
   lup's default, the ones pytest's configuration gives;
5. **scratch:** `tmp/` at any depth, and the saved versions under `.lup/`;
6. **docs:** Markdown files and `docs/`;
7. **data:** data formats outside a source tree;
8. **production:** everything else, so a file nobody classified is gated.

Each role's patterns come from the declaration resolved (`Declaration`), every
selected module's own, starting from lup's (`lup_dev.catalog.paths`). A protected
Python module gets lup's rules as production code does: protection adds the
operator's review, it doesn't take the rules away. A protected path the
declaration also excludes still asks, but gets no rules and no findings. A rule the
declaration exempts a path from is lifted there alone. The table of what each role
gets is in `docs/judging-writes.md`, *What each change gets*.
"""

import tomllib
from pathlib import Path, PurePath
from typing import Literal

from lup.types import Model
from lup_dev.declaration.kinds import Pytest
from lup_dev.declaration.resolve import Declaration
from lup_dev.layout import CheckoutLayout

type Role = Literal[
    "protected", "operator", "excluded", "test", "scratch", "docs", "data", "production"
]
"""A path's role, which decides what a change to it gets."""


def matches(path: PurePath, patterns: list[str]) -> bool:
    """Say whether `path` matches any of `patterns`, each matched whole."""
    return any(path.full_match(pattern) for pattern in patterns)


class Roles(Model):
    """The role of every path in one worktree, from its project's declaration."""

    root: Path
    declaration: Declaration
    """The declaration the worktree is judged by."""

    def role(self, path: Path) -> Role:
        """Return the role of `path`, relative to the root.

        >>> from lup_dev import Project
        >>> roles = Roles(root=Path("/nowhere"), declaration=Declaration.of(Project()))
        >>> [roles.role(Path(p)) for p in ["uv.lock", "AGENTS.md", "tmp/a.py", "x.py"]]
        ['protected', 'operator', 'scratch', 'production']
        """
        paths = self.declaration.paths
        if self.protecting(path) is not None or path == self.declaration.source:
            return "protected"
        if matches(path, paths.operator_documents):
            return "operator"
        if self.is_excluded(path):
            return "excluded"
        if self.is_test(path):
            return "test"
        if matches(path, paths.scratch):
            return "scratch"
        if matches(path, paths.docs):
            return "docs"
        data = matches(PurePath(path.name), paths.data)
        if data and not self.in_source_tree(path):
            return "data"
        return "production"

    def protecting(self, path: Path) -> str | None:
        """Return the first protected pattern `path` matches, or none.

        >>> from lup_dev import Project
        >>> roles = Roles(root=Path("/nowhere"), declaration=Declaration.of(Project()))
        >>> roles.protecting(Path("packages/lup/pyproject.toml"))
        '**/pyproject.toml'
        """
        protected = self.declaration.paths.protected
        return next(
            (pattern for pattern in protected if path.full_match(pattern)), None
        )

    def is_python(self, path: Path) -> bool:
        """Say whether `path` is a Python module, which the rules read."""
        return matches(PurePath(path.name), self.declaration.paths.python)

    def is_excluded(self, path: Path) -> bool:
        """Say whether the project's declaration holds `path` to nothing."""
        return matches(path, self.declaration.paths.excluded)

    def exempt(self, path: Path, rule: str) -> bool:
        """Say whether the project's declaration lifts `rule` from `path`.

        >>> from lup_dev import CodeRules, Exemption, Exemptions, Modules, Project
        >>> lifted = Exemption(rule="regex", paths=["parsers/**"], why="a grammar")
        >>> lifting = CodeRules(exempt=Exemptions().add(lifted))
        >>> project = Project(modules=Modules.default().edit(lifting))
        >>> roles = Roles(root=Path("/nowhere"), declaration=Declaration.of(project))
        >>> [roles.exempt(Path("parsers/a.py"), r) for r in ["regex", "elif"]]
        [True, False]
        """
        return any(
            lifted.rule == rule and matches(path, lifted.paths)
            for lifted in self.declaration.exempt
        )

    def ruled(self, path: Path) -> bool:
        """Say whether lup's rules read `path`: a production or protected module.

        Never one the declaration excludes, even where it's protected.

        >>> from lup_dev import Core, Modules, Paths, Project
        >>> excluding = Core(paths=Paths().add(excluded=[".github/x/**"]))
        >>> project = Project(modules=Modules.default().edit(excluding))
        >>> roles = Roles(root=Path("/nowhere"), declaration=Declaration.of(project))
        >>> [roles.ruled(Path(p)) for p in ["a.py", ".github/h.py", ".github/x/h.py"]]
        [True, True, False]
        """
        ruled = self.role(path) in ["production", "protected"]
        return self.is_python(path) and ruled and not self.is_excluded(path)

    def checked(self, path: Path) -> bool:
        """Say whether pyright's and ruff's findings in `path` are reported.

        A module lup's rules read, or a test: tests are exempt from lup's rules,
        not from pyright and ruff.
        """
        return self.ruled(path) or (self.is_python(path) and self.role(path) == "test")

    def is_test(self, path: Path) -> bool:
        """Say whether pytest collects `path` as a test, or reads it as a conftest.

        The test roots are the ones the declaration names; where it keeps lup's
        default, pytest's configuration says where tests are, as it did before a
        project could name its own, until the gate checks `testpaths` against the
        declared roots (#176).
        """
        if not self.is_python(path):
            return False
        named = PurePath(path.name)
        declared = self.declaration.tests
        roots = declared if declared is not None else self.configured(path)
        for pytest in roots:
            if not path.full_match(str(pytest.root / "**")):
                continue
            if matches(named, self.declaration.paths.conftest):
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
        if matches(path, self.declaration.paths.source_trees):
            return True
        return any(
            CheckoutLayout(root=self.root / directory).package.is_file()
            for directory in path.parents
            if directory != Path()
        )
