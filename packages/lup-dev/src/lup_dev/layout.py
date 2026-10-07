"""Where `lup_dev` keeps what it stores, as models whose fields are the places.

Two homes (`docs/judging-writes.md`, *Where things live*):
- lup's own state, under `$XDG_STATE_HOME/lup/`: each worktree's store, outside the
  worktree so the restore source is out of the agent's reach, and each
  repository's verdict log;
- inside a worktree, `.lup/saved/`, where a refused version waits for the agent.
"""

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model

if TYPE_CHECKING:
    from lup_dev.settings import LupDevSettings


def digest(path: Path) -> str:
    """Name a directory by its absolute path, as a stable file name.

    >>> len(digest(Path("/work/lup")))
    64
    """
    return hashlib.sha256(str(path).encode()).hexdigest()


class StoreLayout(Model):
    """Where one worktree's store keeps its parts, under its own directory."""

    home: Path

    @property
    def snapshots(self) -> Path:
        """The bare repository holding the snapshots and the trees lup keeps."""
        return self.home / "snapshots.git"

    @property
    def lock(self) -> Path:
        """The lock a checkpoint holds while it judges and moves the accepted tree."""
        return self.home / "store.lock"

    @property
    def state(self) -> Path:
        """The worktree's state between checkpoints: commits seen, saved versions."""
        return self.home / "state.json"

    @property
    def calls(self) -> Path:
        """The calls running now, read and written under `calls_lock`."""
        return self.home / "calls.json"

    @property
    def calls_lock(self) -> Path:
        """The lock guarding `calls`, since hooks for parallel calls run at once."""
        return self.home / "calls.lock"

    @property
    def sessions(self) -> Path:
        """One file per session that ran in this worktree."""
        return self.home / "sessions"

    @property
    def holds(self) -> Path:
        """One file per hold: a change waiting for the operator's answer."""
        return self.home / "holds"

    @property
    def importers(self) -> Path:
        """The importers pass: whether one runs, what's left, what it found."""
        return self.home / "importers.json"

    @property
    def importers_lock(self) -> Path:
        """The lock guarding `importers`."""
        return self.home / "importers.lock"

    @property
    def importers_run(self) -> Path:
        """The lock the running pass holds for its whole life, which the OS frees."""
        return self.home / "importers.run.lock"

    @property
    def importers_log(self) -> Path:
        """What the background pass prints, kept for when it fails."""
        return self.home / "importers.log"

    def session(self, session: str) -> Path:
        """Say where one session's state is kept."""
        return self.sessions / f"{session}.json"

    def hold(self, hold: str) -> Path:
        """Say where one hold is kept."""
        return self.holds / f"{hold}.json"


class CheckoutLayout(Model):
    """The places inside a worktree that lup reads or writes."""

    root: Path

    @property
    def pyproject(self) -> Path:
        """The worktree's own project file, where `[tool.lup]` names the declaration."""
        return self.root / "pyproject.toml"

    @property
    def package(self) -> Path:
        """The file that makes `root` a Python package."""
        return self.root / "__init__.py"

    @property
    def home(self) -> Path:
        """Lup's own directory in the worktree, which git ignores."""
        return self.root / ".lup"

    @property
    def saved(self) -> Path:
        """Where refused versions are saved, one numbered directory per refusal."""
        return self.home / "saved"

    @property
    def ruff(self) -> Path:
        """The project's own ruff, so findings match what its gate runs."""
        return self.root / ".venv" / "bin" / "ruff"

    def saved_copy(self, number: int, path: Path) -> Path:
        """Say where the version refused in refusal `number` is saved, by its path."""
        return self.saved / str(number) / path


class Layout(Model):
    """Where lup's state lives for one user: `$XDG_STATE_HOME/lup`."""

    state: Path

    @classmethod
    def of(cls, settings: LupDevSettings) -> Layout:
        """Place lup's state where the settings say, or XDG's default."""
        home = settings.xdg_state_home or Path.home() / ".local" / "state"
        return cls(state=home / "lup")

    @property
    def worktrees(self) -> Path:
        """Every worktree's store, one directory each."""
        return self.state / "worktrees"

    @property
    def session_index(self) -> Path:
        """Which worktree each session runs in, by session id."""
        return self.state / "sessions"

    def store(self, worktree: Path) -> StoreLayout:
        """Say where the store of the worktree at `worktree` lives."""
        return StoreLayout(home=self.worktrees / digest(worktree))

    def verdicts(self, repository: Path) -> Path:
        """Say where the verdict log of a repository lives, by its git directory."""
        return self.state / "repositories" / digest(repository) / "verdicts.jsonl"

    def session_worktree(self, session: str) -> Path:
        """Say where the worktree a session started in is recorded."""
        return self.session_index / f"{session}.json"
