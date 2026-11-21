"""`Worktree`: a worktree as git finds it from a directory in it, the way a session's own git would, and what lup asks of its files.

For code acting on the worktree it's typed in, the gate's files, the code rules'
or a command's own: git finds the repository through the worktree's `.git`, as
the agent's own git does, reading the operator's configuration, so what it says
of the files is what their `git add` or `git commit` would. The machine reading
a repository a room writes pins git to it instead (`Store`).
"""

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from lup.programs.git.answers import line, nul_separated
from lup.programs.git.running import Git, GitError
from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta

    from lup.doors.parts import Finished


def nested(name: str) -> bool:
    """Say whether `name`, as `git ls-files --others` lists it, is a repository nested in the worktree that git doesn't track: git lists one as a directory, its name ending in `/`, never descending into it.

    >>> nested("tmp/clone/"), nested("tmp/clone/a.py")
    (True, False)
    """
    return name.endswith("/")


class Worktree(Model):
    """A worktree, as git finds it from a directory in it: its root, the repository's common git directory, and whether that repository is bare."""

    git: Git
    root: Path
    common: Path
    """The repository's common git directory: a clone's `.git`, or a bare
    repository's own directory, which every worktree of it shares."""
    bare: bool
    """Whether the repository is bare, its worktrees all linked ones."""

    @property
    def main(self) -> Path:
        """The repository's main worktree: a bare repository's own directory, which every worktree shares, or a clone's root."""
        return self.common if self.bare else self.common.parent

    @classmethod
    async def located(cls, git: Git, within: Path) -> Worktree | None:
        """Return the worktree `within` is in, as `git` finds it from there; none where it's in none, a bare repository's own directory among them.

        Raise `GitError` where git can't be run.
        """
        top = await git.ran("rev-parse", "--show-toplevel", cwd=within)
        if top.status != 0:
            return None
        common = await git.done(
            "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=within
        )
        shared = Path(line(common))
        bare = await git.ran("config", "--bool", "core.bare", cwd=shared)
        return cls(
            git=git,
            root=Path(line(top)),
            common=shared,
            bare=bare.status == 0 and line(bare) == "true",
        )

    async def ran(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        env: dict[str, str] | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git from the worktree's root, as `Git.ran` does, and say how it ended, whatever its status."""
        return await self.git.ran(
            *arguments, given=given, env=env, cwd=self.root, within=within
        )

    async def done(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git from the worktree's root, as `Git.done` does: raise `GitError` where it fails."""
        return await self.git.done(*arguments, env=env, cwd=self.root, within=within)

    async def files(self, paths: list[Path] | None = None) -> list[PurePosixPath]:
        """List each file of the worktree git would commit, of those `paths` name or hold, or every one where none are given, from its root, in order: tracked or not, but not ignored, and on disk.

        A repository nested in the worktree that git doesn't track is none of
        its files. Raise `GitError` where git fails, as where a path is
        outside the worktree.
        """
        within = [
            each.resolve().relative_to(self.root).as_posix() for each in paths or []
        ]
        listed = await self.done(
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--deduplicate",
            "--",
            *within,
        )

        def there(name: str) -> bool:
            found = self.root / name
            return found.is_symlink() or found.exists()

        return sorted(
            PurePosixPath(name)
            for name in nul_separated(listed.output)
            if not nested(name) and there(name)
        )

    async def tracks(self, path: Path) -> bool:
        """Say whether git tracks the file at `path` in the worktree: whether its index holds it.

        Raise `GitError` where git fails otherwise than by not tracking it.
        """
        ran = await self.ran("ls-files", "--error-unmatch", "--", str(path))
        match ran.status:
            case 0 | 1:
                return ran.status == 0
            case _:
                message = f"git can't say whether it tracks {path}: {ran.said()}"
                raise GitError(message)

    async def head(self) -> str | None:
        """Return the commit the worktree's `HEAD` names, by its whole id; none before the repository's first commit.

        Raise `GitError` where git fails otherwise.
        """
        ran = await self.ran("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        match ran.status:
            case 0:
                return line(ran)
            case 1:
                return None
            case _:
                message = f"git can't read {self.root}'s HEAD: {ran.said()}"
                raise GitError(message)

    async def staged(self) -> str:
        """Return the tree git would commit the worktree's files as, every change and every file it doesn't ignore added, read through an index of its own, the worktree's own left as it is.

        It starts from a copy of the worktree's index, so git hashes again only
        what changed. A repository nested in the worktree that git doesn't
        track is left out: one with no commit yet would fail `git add`, and its
        files are its own repository's. Raise `GitError` where git fails.
        """
        own = await self.done(
            "rev-parse", "--path-format=absolute", "--git-path", "index"
        )
        others = await self.done("ls-files", "-z", "--others", "--exclude-standard")
        left = [
            f":(exclude,literal){name}"
            for name in nul_separated(others.output)
            if nested(name)
        ]

        def copied(to: Path) -> None:
            if Path(line(own)).is_file():
                shutil.copyfile(line(own), to)

        with tempfile.TemporaryDirectory(prefix="lup-staged-") as scratch:
            index = Path(scratch) / "index"
            copied(index)
            apart = {"GIT_INDEX_FILE": str(index)}
            await self.done(
                "add", "--all", "--", ".", *left, env=apart, within=self.git.whole
            )
            return line(await self.done("write-tree", env=apart))
