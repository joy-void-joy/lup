"""Where `lup_dev` keeps what it stores, as models whose fields are the places.

The homes (`docs/judging-writes.md`, *Where things live*):
- lup's own state, under `$XDG_STATE_HOME/lup/`: each worktree's store, outside the
  worktree so the restore source is out of the agent's reach, and each
  repository's verdict log;
- each worktree engine's socket, under `$XDG_RUNTIME_DIR/lup/`, since a socket's
  path is limited in length;
- inside a worktree, `.lup/saved/`, where a refused version waits for the agent;
- inside `lup_dev`, the built engine (`Bundle`).
"""

import getpass
import hashlib
import tempfile
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


def short_digest(path: Path) -> str:
    """Name a directory by its absolute path, short enough for a socket's path.

    A Unix socket's path holds at most 107 bytes on Linux, 103 on macOS.

    >>> len(short_digest(Path("/work/lup")))
    32
    """
    return hashlib.blake2b(str(path).encode(), digest_size=16).hexdigest()


class Bundle(Model):
    """The built engine, shipped inside `lup_dev`: its script and the stubs beside it.

    The engine's build (`packages/lup-dev/checker/build.py`) writes it; git ignores
    it, and the package carries it when installed from a built checkout.
    """

    directory: Path = Path(__file__).parent / "codescan" / "bundle"

    @property
    def script(self) -> Path:
        """The engine itself, one JavaScript file run by Node."""
        return self.directory / "engine.js"

    @property
    def stubs(self) -> Path:
        """The standard library's stubs at pyright's pinned release, which it reads."""
        return self.directory / "typeshed-fallback"


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

    @property
    def engine_lock(self) -> Path:
        """The lock a client holds while it starts the worktree's engine."""
        return self.home / "engine.lock"

    @property
    def engine_log(self) -> Path:
        """What the worktree's engine prints, kept for when it fails."""
        return self.home / "engine.log"

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

    @property
    def rules_reference(self) -> Path:
        """The reference to lup's rules, compiled from the engine's table: lup's own."""
        return self.root / "docs" / "rules.md"

    def saved_copy(self, number: int, path: Path) -> Path:
        """Say where the version refused in refusal `number` is saved, by its path."""
        return self.saved / str(number) / path

    @property
    def tool(self) -> Path:
        """The package installed as the judge, `lup-dev`, in a checkout of lup."""
        return self.root / "packages" / "lup-dev"

    @property
    def judge_source(self) -> list[Path]:
        """Everything the installed judge carries, from a checkout of lup's root.

        Both packages' metadata and source (`lup` is a dependency of `lup-dev`),
        the engine's source the bundle is built from, and `uv.lock`, whose
        versions the installed copy's dependencies are held to.
        """
        library = Path("packages") / "lup"
        return [
            library / "pyproject.toml",
            library / "src",
            Path("packages") / "lup-dev" / "pyproject.toml",
            Path("packages") / "lup-dev" / "src",
            Path("packages") / "lup-dev" / "checker",
            Path("uv.lock"),
        ]


class Layout(Model):
    """Where lup's state lives for one user: `$XDG_STATE_HOME/lup`, and its sockets."""

    state: Path
    runtime: Path = Path(tempfile.gettempdir()) / f"lup-{getpass.getuser()}"
    """lup's sockets: `$XDG_RUNTIME_DIR/lup`, or the user's own temporary directory."""

    @classmethod
    def of(cls, settings: LupDevSettings) -> Layout:
        """Place lup's state and sockets where the settings say, or XDG's defaults."""
        home = settings.xdg_state_home or Path.home() / ".local" / "state"
        if settings.xdg_runtime_dir is None:
            return cls(state=home / "lup")
        return cls(state=home / "lup", runtime=settings.xdg_runtime_dir / "lup")

    def engine_socket(self, worktree: Path) -> Path:
        """Say where the engine of the worktree at `worktree` listens."""
        return self.runtime / f"{short_digest(worktree)}.sock"

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

    @property
    def approval(self) -> Path:
        """The commit of lup the operator last approved as the judge that runs."""
        return self.state / "judge" / "approved.json"
