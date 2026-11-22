"""`Git`: how lup runs git, every time, whoever asks: hardened, held to a time, through a part's own program or `lup.programs`.

Each run is given options that turn off what a repository's files could make git
read or run in another's place (`Git.options`), and variables that keep it from
reading grafts or fetching what a partial clone left out (`Git.variables`), so
no caller can forget them. A run through a part's program (`through`) is one a
promise stands in; one without runs git through `lup.programs`, for lup's own
code outside any part (`README.md` here, *How git is run*).
"""

import os
import shutil
from datetime import timedelta
lazy from pathlib import Path

from lup.doors.door import RefusedError
from lup.doors.parts import Finished, Program
from lup.programs.ended import ProgramMissingError, ProgramOverdueError
from lup.programs.waited import awaited
from lup.types import Model
lazy from lup.programs.git.stores import Store
lazy from lup.programs.git.worktrees import Worktree


class GitError(RefusedError):
    """git couldn't answer what lup asked: it isn't there, ran past its time, failed, or answered what lup can't read; the call needing it is refused, saying which command and why."""


class Git(Model):
    """git as lup runs it: through a part's own program where one is given, else through `lup.programs`, each run hardened and held to a time.

    A question lup asks git is a method of what it's asked of: a worktree
    (`Git.located`), a repository's store, pinned (`Git.pinned`), or a
    directory outside any (`Git.initialised`, `Git.cloned`, `Git.diffed`).
    """

    through: Program | None = None
    """The part's own program git runs through, which a promise stands in;
    none for lup's own code outside any part, which runs it through
    `lup.programs`."""
    limit: timedelta = timedelta(seconds=30)
    """The longest a run reading or writing a few refs or objects may take,
    hundreds of times what one does: past it, git is killed, since git
    reading a ref a room made a FIFO waits for good."""
    whole: timedelta = timedelta(minutes=10)
    """The longest a run reading every file of a worktree may take, as `git
    add --all` hashing each it hasn't yet."""
    crossing: timedelta = timedelta(minutes=10)
    """The longest a run crossing the network may take: a fetch, a push, a
    listing of a remote's refs, a clone, where a whole history may move."""
    options: list[str] = [
        "--no-replace-objects",
        "-c",
        "core.commitGraph=false",
        "-c",
        "advice.graftFileDeprecated=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.quotePath=false",
    ]
    """The options every run is given before its command: replace refs and the
    commit-graph ignored, which a room writes and git reads a commit's parents
    and tree from before the commit's own bytes; the hint a graft file named
    gives left out; `core.fsmonitor` and hooks, which run a program a
    repository's files name, turned off; paths printed as they are."""
    variables: dict[str, str] = {
        "GIT_GRAFT_FILE": os.devnull,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    """The variables every run is given: grafts read from an empty file,
    rather than the `info/grafts` a room writes; nothing fetched for an object
    a partial clone left out, so a read never reaches the network; and no
    prompt on the terminal for a password, which would wait for good."""
    unfound: int = 127
    """The status `env` ends with where the program it's asked to run isn't
    there."""

    @classmethod
    async def located(
        cls, within: Path, through: Program | None = None
    ) -> Worktree | None:
        """Return the worktree `within` is in, as git finds it from there; none where it's in none.

        Raise `GitError` where git can't be run.
        """
        return await Worktree.located(cls(through=through), within)

    @classmethod
    def pinned(cls, common: Path, through: Program | None = None) -> Store:
        """Return the store of the repository whose common git directory is `common`, git pinned to it, reading nothing of anyone's but the repository's own `config`: for the machine, reading a repository a room writes."""
        return Store(git=cls(through=through), common=common)

    @classmethod
    async def initialised(cls, root: Path, through: Program | None = None) -> Worktree:
        """Make a repository at `root`, as `git init` does, and return its worktree.

        Raise `GitError` where git can't make it.
        """
        git = cls(through=through)
        await git.done("init", "--quiet", str(root))
        found = await Worktree.located(git, root)
        if found is None:
            message = f"git made a repository at {root}, then found none there"
            raise GitError(message)
        return found

    @classmethod
    async def apart(
        cls, root: Path, object_format: str, through: Program | None = None
    ) -> Store:
        """Make a bare repository of lup's own at `root`, its objects named by `object_format` (`sha1` or `sha256`), from no template and reading no configuration of anyone's, and return its store.

        Raise `GitError` where git can't make it.
        """
        git = cls(through=through)
        await git.done(
            "init",
            "--quiet",
            "--bare",
            "--template=",
            f"--object-format={object_format}",
            str(root),
            env=unconfigured(),
        )
        return Store(git=git, common=root)

    @classmethod
    async def cloned(
        cls,
        url: str,
        into: Path,
        branch: str,
        through: Program | None = None,
    ) -> Worktree:
        """Clone the branch or tag `branch` of the repository at `url` into `into`, its last commit alone, and return its worktree.

        Raise `GitError` where git can't clone it.
        """
        git = cls(through=through)
        await git.done(
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            branch,
            url,
            str(into),
            within=git.crossing,
        )
        found = await Worktree.located(git, into)
        if found is None:
            message = f"git cloned {url} into {into}, then found no worktree there"
            raise GitError(message)
        return found

    @classmethod
    async def diffed(
        cls, before: Path, after: Path, through: Program | None = None
    ) -> str:
        """Return the whole diff from the directory `before` to the directory `after`, as git shows one, comparing them alone: no repository, configuration or diff driver of anyone's has a say in it.

        Each is named from their common parent, so the diff's paths read
        from each directory's name. Raise `GitError` where git fails.
        """
        git = cls(through=through)
        ran = await git.ran(
            "diff",
            "--no-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            before.name,
            after.name,
            env=unconfigured(),
            cwd=before.parent,
            within=git.whole,
        )
        if ran.status not in [0, 1]:
            message = f"git couldn't compare {before} with {after}: {ran.said()}"
            raise GitError(message)
        return ran.text()

    async def ran(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git with `arguments`, after the options every run is given, `given` on its input, `env` set beside the variables every run is given, from `cwd`, killed past `within` or this git's `limit`, and say how it ended, whatever its status.

        What `Worktree` and `Store` run each question through: a question lup
        asks git is a method of theirs. Raise `GitError` where git isn't there
        or runs past its time, or `lup.UnrunError` where the part's program
        can't run it.
        """
        variables = {**self.variables, **(env or {})}
        words = [*self.options, *arguments]
        limit = within or self.limit
        if self.through is not None:
            return await self.through.ran(
                *words, given=given, env=variables, cwd=cwd, within=limit
            )
        pinned = [f"{name}={value}" for name, value in variables.items()]
        command = ["env", *pinned, "git", *words]
        try:
            ran = await awaited(
                *command, cwd=cwd, stdin=given, checked=False, within=limit
            )
        except ProgramMissingError as unfound:
            message = "git isn't there; install it from https://git-scm.com"
            raise GitError(message) from unfound
        except ProgramOverdueError as late:
            message = (
                f"git {command_of(list(arguments))} ran past {limit} and was stopped: something "
                "it reads may be a FIFO, or a file nothing finishes writing, as a "
                "room can make of a repository's refs"
            )
            raise GitError(message) from late
        if ran.status == self.unfound and shutil.which("git") is None:
            message = "git isn't there; install it from https://git-scm.com"
            raise GitError(message)
        return Finished(status=ran.status, output=ran.output, error=ran.error)

    async def done(
        self,
        *arguments: str,
        given: bytes | str | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        within: timedelta | None = None,
    ) -> Finished:
        """Run git as `ran` does, and return how it ended; raise `GitError` where it ends with any status but 0, saying which command and what git said."""
        ran = await self.ran(*arguments, given=given, env=env, cwd=cwd, within=within)
        if ran.status != 0:
            where = "" if cwd is None else f" in {cwd}"
            message = f"git {command_of(list(arguments))} failed{where}: {ran.said()}"
            raise GitError(message)
        return ran


def command_of(arguments: list[str]) -> str:
    """Return the git command `arguments` run, as a refusal names it: the first that's neither an option nor an option's setting.

    >>> command_of(["-c", "gc.auto=0", "fetch", "--quiet", "origin"])
    'fetch'
    """
    return next(
        (each for each in arguments if not each.startswith("-") and "=" not in each),
        "",
    )


def unconfigured() -> dict[str, str]:
    """Return the variables that have git read no configuration at all, the machine's or the operator's, nor look for a repository above where it runs: for git working outside any repository.

    >>> unconfigured()["GIT_CEILING_DIRECTORIES"]
    '/'
    """
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": "/",
    }
