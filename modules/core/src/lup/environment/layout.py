"""Where lup finds what it reads outside a module's own code: a repository's declaration and its own local layer, and the machine's layer.

A repository's declaration sits at a worktree's root. Its local layer, which git
ignores, sits in its main worktree (a clone's root, or a bare repository's own
directory), so every worktree of the repository shares it. The machine's layer
sits in lup's directory of the operator's configuration, and applies to every
repository on this machine (`README.md` of `lup/declaration/`, *Layers*).
"""

import tomllib
from pathlib import Path

from lup.types import Model


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
