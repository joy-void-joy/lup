"""git, as the machine's parts run it on a repository a room writes: pinned to its common git directory, and what it prints read here alone.

Each method runs one git command with `Trees`' options and variables, nothing a
room planted read (`git_options`, `pinned`), and returns what it printed as a
value, so what git's output looks like is said in one place, beside the command
printing it, rather than wherever a caller reads it. A command failing raises
`GitError`, saying which and why, but where its status is an answer, as
`merge-base --is-ancestor`'s is.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from lup.doors.door import RefusedError
from lup.doors.parts import Program
from lup.hosting.trees import Entry, git_options, pinned, unconfigured
from lup.types import Model

if TYPE_CHECKING:
    from lup.doors.parts import Finished


class GitError(RefusedError):
    """git failed on a repository the machine reads or writes: the call needing it is refused, saying which command and why."""


class Merged(Model):
    """What `git merge-tree` made of two trees: the tree, and the files it conflicts in, none where it merged cleanly."""

    tree: str
    conflicted: list[str] = []


def nul_separated(output: bytes) -> list[str]:
    r"""Return the fields of git's `-z` output, each ended by a NUL, the last one's end optional.

    >>> nul_separated(b"a\x00b c\x00"), nul_separated(b"")
    (['a', 'b c'], [])
    """
    # lup: ignore("string-split", why="git's `-z` output, each field ended by a NUL, which git writes for being read this way")
    fields = output.split(b"\0")
    return [each.decode() for each in fields if each]


class Git(Model):
    """git on one repository, by its common git directory, through the machine's part's `git` program."""

    program: Program
    common: Path
    index: Path | None = None
    """An index of its own, where a command reads or writes one: never a
    worktree's."""

    async def ran(self, *arguments: str, given: bytes | None = None) -> Finished:
        """Run git pinned to the repository, and return how it ended, whatever its status."""
        env = {
            **pinned(self.common),
            **({} if self.index is None else {"GIT_INDEX_FILE": str(self.index)}),
        }
        return await self.program.ran(*git_options(), *arguments, given=given, env=env)

    async def done(self, *arguments: str, given: bytes | None = None) -> Finished:
        """Run git pinned to the repository, and raise `GitError` where it fails."""
        ran = await self.ran(*arguments, given=given)
        if ran.status != 0:
            message = f"git {arguments[0]} failed in {self.common}: {ran.said()}"
            raise GitError(message)
        return ran

    async def text(self, *arguments: str, given: bytes | None = None) -> str:
        """Run git pinned to the repository, and return what it printed, trimmed."""
        return (await self.done(*arguments, given=given)).text().strip()

    def with_index(self, index: Path) -> Git:
        """Return git on the same repository, reading and writing `index`."""
        return self.model_copy(update={"index": index})

    async def bare(self) -> bool:
        """Say whether the repository is bare, as its own configuration says."""
        return await self.text("config", "--bool", "core.bare") == "true"

    async def object_format(self) -> str:
        """Return the hash the repository's objects are named by: `sha1` or `sha256`."""
        return await self.text("rev-parse", "--show-object-format")

    async def branch(self, name: str) -> str:
        """Return the commit the local branch `name` is at; raise `GitError` where its name isn't a branch's or it isn't there."""
        await self.done("check-ref-format", f"refs/heads/{name}")
        return await self.text("rev-parse", "--verify", f"refs/heads/{name}^{{commit}}")

    async def url(self, remote: str) -> str:
        """Return the URL of `remote`, as the repository's own configuration names it, never a file a room writes."""
        return await self.text("config", "--local", "--get", f"remote.{remote}.url")

    async def remote_tip(self, url: str, ref: str) -> str | None:
        """Return the commit `ref` is at on the remote at `url`, as the remote says; none where it hasn't the ref."""
        listed = await self.text("ls-remote", url, ref)
        if not listed:
            return None
        # lup: ignore("string-split", why="`git ls-remote` prints an id and a ref apart by a tab, and has no other format")
        [tip, *_] = listed.split("\t")
        return tip

    async def fetched(self, url: str, ref: str) -> None:
        """Fetch `ref`'s objects from the remote at `url` into the repository's store, writing no ref and starting no maintenance."""
        await self.done(
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "fetch",
            "--no-write-fetch-head",
            "--no-tags",
            "--quiet",
            url,
            ref,
        )

    async def holds(self, ancestor: str, commit: str) -> bool:
        """Say whether `commit`'s history holds `ancestor`."""
        ran = await self.ran("merge-base", "--is-ancestor", ancestor, commit)
        match ran.status:
            case 0 | 1:
                return ran.status == 0
            case _:
                message = (
                    f"git can't say whether {commit} holds {ancestor}: {ran.said()}"
                )
                raise GitError(message)

    async def bases(self, tip: str, before: list[str]) -> list[str]:
        """Return the commits `tip` and those `before` have in common, best first; none where they share no history."""
        ran = await self.ran("merge-base", "--all", tip, *before)
        match ran.status:
            case 0:
                return ran.text().splitlines()
            case 1:
                return []
            case _:
                message = f"git can't find what {tip} has in common: {ran.said()}"
                raise GitError(message)

    async def merged(self, base: str, ours: str, theirs: str) -> Merged:
        """Merge the trees `ours` and `theirs` from the tree `base`, writing what it makes, conflict markers and all, into the store: its tree, and the files it conflicts in."""
        ran = await self.ran(
            "merge-tree",
            "--write-tree",
            "-z",
            "--name-only",
            "--no-messages",
            f"--merge-base={base}",
            ours,
            theirs,
        )
        if ran.status not in [0, 1]:
            message = f"git can't merge {ours} and {theirs}: {ran.said()}"
            raise GitError(message)
        [tree, *conflicted] = nul_separated(ran.output)
        return Merged(tree=tree, conflicted=conflicted if ran.status == 1 else [])

    async def stored_blobs(self, contents: list[bytes]) -> None:
        """Write each of `contents` into the store as a blob, in one `git fast-import`."""
        if contents:
            await self.done(
                "fast-import",
                "--quiet",
                given=b"".join(
                    b"blob\ndata %d\n%b\n" % (len(content), content)
                    for content in contents
                ),
            )

    async def blob(self, content: bytes) -> str:
        """Write `content` into the store as a blob, its bytes as given, and return its id."""
        return await self.text(
            "hash-object", "-w", "--no-filters", "--stdin", given=content
        )

    async def tree_of(self, entries: list[Entry]) -> str:
        """Write a tree of `entries`, the files of one, through this git's own index, and return its id."""
        listed = b"".join(
            f"{each.mode} {each.object}\t{each.path}".encode() + b"\0"
            for each in entries
        )
        await self.done("update-index", "-z", "--index-info", given=listed)
        return await self.text("write-tree")

    async def commit(self, content: bytes) -> str:
        """Write a commit object holding `content`, its bytes as given, and return its id."""
        return await self.text(
            "hash-object", "-t", "commit", "-w", "--stdin", given=content
        )

    async def pushed(self, url: str, commit: str, ref: str, expected: str) -> None:
        """Push `commit` to `ref` on the remote at `url`, where the remote holds it at `expected`, else refuse; `commit` empty deletes it."""
        await self.done(
            "push", f"--force-with-lease={ref}:{expected}", url, f"{commit}:{ref}"
        )

    async def moved(self, ref: str, commit: str) -> None:
        """Move the repository's `ref` to `commit`, as a push moves the remote's tracking ref."""
        await self.done("update-ref", ref, commit)


async def initialised(program: Program, root: Path, object_format: str) -> Git:
    """Make a bare repository of its own at `root`, its objects named by `object_format`, reading no configuration of anyone's, and return git on it."""
    made = await program.ran(
        "init",
        "--quiet",
        "--bare",
        "--template=",
        f"--object-format={object_format}",
        str(root),
        env=unconfigured(),
    )
    if made.status != 0:
        message = f"git can't make a repository at {root}: {made.said()}"
        raise GitError(message)
    return Git(program=program, common=root)
