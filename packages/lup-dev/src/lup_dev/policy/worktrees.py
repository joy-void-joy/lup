"""Which worktrees of its repository a session's writes are judged in.

A session starts in one worktree and often works in others
(`docs/judging-writes.md`, *Every worktree of the repository*). Its repository is
read from where it starts, as git's common directory, so a session started in a
bare repository's own directory is judged too, holding no worktree until it
reaches one. A write is judged in the worktree its path is in, which git names
from the file's nearest existing directory; a repository nested in a worktree is
another repository, as git says.

The session index keeps each session's repository and the worktrees it holds:
where it started, where its file tools wrote, and where its hooks reported its
working directory. It keeps, too, the worktrees each of its conversations works
in (`Holding.works`), which a call of that conversation holds checkpoints back
in while it runs (`docs/judging-writes.md`, *Which calls hold a checkpoint
back*).
"""

from pathlib import Path

from filelock import FileLock

from lup.types import Model, MutableModel
from lup_dev.git import Git
from lup_dev.layout import Layout
from lup_dev.stored import read_model, write_model


class Place(Model):
    """Where a path is, as git names it."""

    repository: Path
    """Its repository's shared git directory (`git rev-parse --git-common-dir`)."""
    worktree: Path | None
    """The root of the worktree holding it; none in the repository's git directory."""
    path: Path
    """The path, relative to its worktree, or to the repository's git directory."""


def place(path: Path) -> Place | None:
    """Say where the absolute `path` is, asking git from its nearest existing directory.

    None outside every repository. Inside a repository's own git directory (a
    bare repository's, or `.git/`), there's no worktree.
    """
    directory = next(each for each in [path, *path.parents] if each.is_dir())
    resolved = directory.resolve() / path.relative_to(directory)
    git = Git(cwd=directory)
    top = git.run(
        "rev-parse",
        "--path-format=absolute",
        "--show-toplevel",
        "--git-common-dir",
        ok=[0, 128],
    )
    if top.status == 0:
        worktree, common = top.output.decode().splitlines()
        root = Path(worktree)
        return Place(
            repository=Path(common), worktree=root, path=resolved.relative_to(root)
        )
    common = git.run(
        "rev-parse", "--path-format=absolute", "--git-common-dir", ok=[0, 128]
    )
    if common.status != 0:
        return None
    repository = Path(common.output.decode().strip())
    return Place(
        repository=repository, worktree=None, path=resolved.relative_to(repository)
    )


class Holding(MutableModel):
    """A session's repository, the worktrees of it the session holds, and those each of its conversations works in."""

    repository: Path
    worktrees: list[Path] = []
    """Their roots, in the order the session reached them."""
    started: dict[str, list[Path]] = {}
    """By conversation, `""` for the session's own and a subagent's id else: the
    worktrees its hooks reported its working directory in."""
    wrote: dict[str, list[Path]] = {}
    """By conversation: the worktrees its file tools wrote in."""

    def reach(self, root: Path) -> bool:
        """Hold the worktree at `root`; say whether the session hadn't reached it."""
        if root in self.worktrees:
            return False
        self.worktrees = [*self.worktrees, root]
        return True

    def note(self, agent: str, *, started: Path | None, wrote: Path | None) -> bool:
        """Note that conversation `agent` worked where its hook's working directory is (`started`) and where its file tool writes (`wrote`); say whether that's new."""

        def added(
            kept: dict[str, list[Path]], root: Path | None
        ) -> dict[str, list[Path]]:
            had = kept.get(agent, [])
            return (
                kept if root is None or root in had else {**kept, agent: [*had, root]}
            )

        now_started = added(self.started, started)
        now_wrote = added(self.wrote, wrote)
        new = now_started != self.started or now_wrote != self.wrote
        self.started = now_started
        self.wrote = now_wrote
        return new

    def works(self, agent: str) -> list[Path]:
        """Return the worktrees conversation `agent` works in, of those the session holds.

        The session's own conversation works where its hooks report its working
        directory, which follows it, and where its file tools write. A
        subagent's hooks report where its session works rather than where it
        does (each adapter says so of its runtime), so a subagent works where
        its file tools write, and only until they have, where its hooks report.

        >>> held = Holding(repository=Path("/r/.git"), worktrees=[Path("/a"), Path("/b")])
        >>> held.note("w", started=Path("/a"), wrote=None)
        True
        >>> held.works("w")
        [PosixPath('/a')]
        >>> held.note("w", started=Path("/a"), wrote=Path("/b"))
        True
        >>> held.works("w")
        [PosixPath('/b')]
        """
        started = self.started.get(agent, [])
        wrote = self.wrote.get(agent, [])
        roots = [*started, *wrote] if not agent or not wrote else wrote
        return [root for root in dict.fromkeys(roots) if root in self.worktrees]

    def release_removed(self) -> bool:
        """Stop holding each worktree whose root is gone; say whether one was.

        `git worktree remove`, as landing a branch does, deletes the root, and a
        worktree that's gone has nothing left to judge.
        """
        present = [root for root in self.worktrees if root.is_dir()]
        released = present != self.worktrees
        self.worktrees = present
        return released


class SessionIndex(Model):
    """Where each session's repository and the worktrees it holds are kept."""

    layout: Layout

    def lock(self, session: str) -> FileLock:
        """Return the lock over one session's entry, which parallel hooks share."""
        self.layout.session_index.mkdir(parents=True, exist_ok=True)
        entry = self.layout.session(session)
        return FileLock(entry.with_name(f"{entry.name}.lock"))

    def read(self, session: str) -> Holding | None:
        """Return what the session holds, or none where it was never seen."""
        return read_model(self.layout.session(session), Holding)

    def write(self, session: str, holding: Holding) -> None:
        """Keep what the session holds."""
        write_model(self.layout.session(session), holding)
