"""Where lup finds what it reads outside a module's own code: a repository's declaration and its own local layer, and the machine's layer.

A repository's declaration sits at a worktree's root. Its local layer, which git
ignores, sits in its main worktree (a clone's root, or a bare repository's own
directory), so every worktree of the repository shares it. The machine's layer
sits in lup's directory of the operator's configuration, and applies to every
repository on this machine (`README.md` here, *Layers*).

Git says where a worktree's root and its main worktree are, asked the same three
things whoever runs it: lup's own code, through `lup.programs` (`found`), or a
part, through the program it declares, which a promise stands in for
(`located`).
"""

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from lup.programs import run
from lup.types import Model

if TYPE_CHECKING:
    from lup.doors.parts import Program

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
    def of(cls, root: str, common: str, bare: str) -> RepositoryLayout:
        r"""Return the layout git's answers say: a worktree's root (`TOP_LEVEL`), the directory every worktree shares (`COMMON`), and whether the repository is bare (`BARE`).

        The main worktree is that shared directory where the repository is
        bare, else its parent, a clone's root.

        >>> RepositoryLayout.of("/src/app\n", "/src/app/.git\n", "false\n").main
        PosixPath('/src/app')
        """
        shared = Path(common.strip())
        return cls(
            root=Path(root.strip()),
            main=shared if bare.strip() == "true" else shared.parent,
        )

    @classmethod
    def found(cls, within: Path) -> RepositoryLayout:
        """Return the layout of the repository holding `within`, as git finds it: the root of the worktree `within` is in, and the repository's main worktree.

        Raise `lup.programs.ProgramFailedError` where `within` is in no
        worktree.
        """
        root = run("git", *TOP_LEVEL, cwd=within).text()
        common = run("git", *COMMON, cwd=within).text()
        bare = run("git", *BARE, cwd=Path(common), checked=False).text()
        return cls.of(root, common, bare)

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
        return cls.of(root.text(), common.text(), bare.text())

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
        declaration = self.declaration
        return self.main / declaration.with_suffix(f".local{declaration.suffix}").name


class MachineLayout(Model):
    """Where this machine keeps the layer that applies to every repository on it."""

    configuration: Path
    """The operator's configuration directory, `$XDG_CONFIG_HOME`."""

    @property
    def layer(self) -> Path:
        """The machine's layer, written as a repository's local layer is."""
        return self.configuration / "lup" / "lup_project.local.py"
