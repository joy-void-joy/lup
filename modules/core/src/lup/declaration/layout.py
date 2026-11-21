"""Where lup finds what it reads outside a module's own code: a repository's declaration and its own local layer, and the machine's layer.

A repository's declaration sits at a worktree's root. Its local layer, which git
ignores, sits in its main worktree (a clone's root, or a bare repository's own
directory), so every worktree of the repository shares it. The machine's layer
sits in lup's directory of the operator's configuration, and applies to every
repository on this machine (`README.md` here, *Layers*).

Git says where a worktree's root and its main worktree are, asked through git's
companion (`found`, `lup.programs.git`): by lup's own code, through
`lup.programs`, or by a part, through the program it declares, which a promise
stands in for.
"""

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model
lazy from lup.programs.git import Git

if TYPE_CHECKING:
    from lup.doors.parts import Program
    from lup.programs.git import Worktree

TOP_LEVEL = ["rev-parse", "--show-toplevel"]
"""What git is asked for a worktree's root."""
COMMON = ["rev-parse", "--path-format=absolute", "--git-common-dir"]
"""What git is asked for the directory every worktree of a repository shares."""
BARE = ["config", "--bool", "core.bare"]
"""What git is asked, in that directory, of whether the repository is bare."""


class LupTable(Model):
    """`[tool.lup]` in a repository's `pyproject.toml`: what lup reads of the repository before loading its declaration."""

    declaration: str = "lup_project.py"
    """The declaration's file, from the worktree's root."""


class ToolTable(Model):
    """`[tool]` in a `pyproject.toml`, of which lup reads its own table alone."""

    lup: LupTable = LupTable()


class Pyproject(Model):
    """A repository's `pyproject.toml`, of which lup reads `[tool.lup]` alone."""

    tool: ToolTable = ToolTable()

    @classmethod
    def read(cls, path: Path) -> Pyproject:
        """Read the `pyproject.toml` at `path`, an empty one where there's none."""
        if not path.is_file():
            return cls()
        return cls.model_validate(tomllib.loads(path.read_text()))


class RepositoryLayout(Model):
    """Where a repository keeps what lup reads of it: at a worktree's root, and in its main worktree."""

    root: Path
    """The worktree's root."""
    main: Path
    """The repository's main worktree: a clone's root, or a bare repository's own
    directory, which every worktree shares."""

    @classmethod
    def of(cls, worktree: Worktree) -> RepositoryLayout:
        """Return the layout of `worktree`, as git's companion found it: its root, and its repository's main worktree."""
        return cls(root=worktree.root, main=worktree.main)

    @classmethod
    async def found(
        cls, within: Path, through: Program | None = None
    ) -> RepositoryLayout | None:
        """Return the layout of the repository holding `within`, as git finds it from there, through a part's own git program where `through` names one: the root of the worktree `within` is in, and the repository's main worktree; none where `within` is in no worktree.

        Raise `lup.programs.git.GitError` where git can't be run, or
        `lup.UnrunError` where the part's program can't.
        """
        worktree = await Git.located(within, through)
        return None if worktree is None else cls.of(worktree)

    # lup: defer(issue=25, why="the gate and code rules ask git for a worktree's layout themselves, by these arguments, which their promises' stand-ins answer, until they ask git's companion (`found`)")
    @classmethod
    async def located(cls, git: Program, within: Path) -> RepositoryLayout | None:
        """Return the layout of the repository holding `within`, as `git`, a part's program, finds it; none where `within` is in no worktree.

        Raise `lup.UnrunError` where git can't be run.
        """
        root = await git.ran("-C", str(within), *TOP_LEVEL)
        if root.status != 0:
            return None
        common = await git.ran("-C", str(within), *COMMON)
        if common.status != 0:
            return None
        bare = await git.ran("-C", common.text().strip(), *BARE)
        shared = Path(common.text().strip())
        return cls(
            root=Path(root.text().strip()),
            main=shared if bare.text().strip() == "true" else shared.parent,
        )

    @property
    def pyproject(self) -> Path:
        """The worktree's `pyproject.toml`, whose `[tool.lup]` names the declaration's file."""
        return self.root / "pyproject.toml"

    @property
    def declaration(self) -> Path:
        """The declaration's file: `lup_project.py` at the root, unless `[tool.lup]` names another."""
        return self.root / Pyproject.read(self.pyproject).tool.lup.declaration

    @property
    def local(self) -> Path:
        """The repository's own local layer, named after its declaration (`lup_project.local.py`), in its main worktree."""
        return local_layer(self.main, self.declaration)


def local_layer(main: Path, declaration: Path) -> Path:
    """Return a repository's own local layer, named after its declaration, in its main worktree `main`, which every worktree shares.

    >>> local_layer(Path("/src/app.git"), Path("lup_project.py"))
    PosixPath('/src/app.git/lup_project.local.py')
    """
    return main / declaration.with_suffix(f".local{declaration.suffix}").name


class MachineLayout(Model):
    """Where this machine keeps the layer that applies to every repository on it."""

    configuration: Path
    """The operator's configuration directory, `$XDG_CONFIG_HOME`."""

    @property
    def layer(self) -> Path:
        """The machine's layer, written as a repository's local layer is."""
        return self.configuration / "lup" / "lup_project.local.py"
