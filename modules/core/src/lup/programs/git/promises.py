"""git's companion's promises: what a module asking git through it can count on.

Each runs real git on scratch repositories it makes in a directory of its own
(`lup.testing.RealGit`), and asks them through the companion as lup's own code
does, through `lup.programs`, on an event loop of asyncio's own in a thread of
its own, since the harness's loop starts no process (`README.md` here, *Its
promises*). A part asking through its own program is promised by the parts that
do, `lup init` among them.
"""

import asyncio
import os
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import lup
from lup.testing import RealGit, Testing, raises

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Generator

GIT = RealGit()
"""git, run for real for the promises' own repositories."""


def looped[T](story: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run `story` on an event loop of asyncio's own, in a thread of its own, and return what it gives: the harness's loop starts no process."""
    with ThreadPoolExecutor(max_workers=1) as apart:
        return apart.submit(asyncio.run, story()).result()


@contextmanager
def scratch() -> Generator[Path]:
    """Hold a directory of its own for as long as the block runs, its links resolved, as git names it."""
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory).resolve()


class Layout(lup.Model):
    """A worktree a promise made, and the main worktree lup should find for it."""

    worktree: Path
    main: Path


def layouts(root: Path) -> list[Layout]:
    """Make, under `root`, a repository in each layout lup works in, a commit in each, and return each: a plain clone, a bare repository's linked worktree, and a clone's linked worktree."""
    clone = GIT.made(root / "clone")
    GIT.committed(clone, {"a.py": "a\n"})
    bare = GIT.made(root / "bare.git", bare=True)
    GIT.git("worktree", "add", "--quiet", "--orphan", "-b", "dev", "tree/dev", cwd=bare)
    linked = bare / "tree" / "dev"
    GIT.committed(linked, {"a.py": "a\n"})
    GIT.git("worktree", "add", "--quiet", "-b", "side", "../side", cwd=clone)
    return [
        Layout(worktree=clone, main=clone),
        Layout(worktree=linked, main=bare),
        Layout(worktree=root / "side", main=clone),
    ]


def planted(store: Path, object_id: str, content: bytes) -> None:
    """Write over the loose object `object_id` in the object store `store`, as a room could, a blob of `content`, which hashes to another id."""
    [place] = [
        each
        for each in (store / "objects").glob("*/*")
        if each.parent.name + each.name == object_id
    ]
    place.chmod(0o644)
    place.write_bytes(zlib.compress(b"blob %d\0%b" % (len(content), content)))


class Asked(lup.Model):
    """What a worktree said of itself: the commit its `HEAD` names, and whether it tracks a file."""

    head: str | None
    tracks: bool


class GitPromises(lup.Part):
    """What a module asking git through its companion can count on."""

    awkward: list[str] = [
        "plain.py",
        "with space.py",
        "ünïcödé.py",
        "new\nline.py",
        "tab\tname.py",
        'quote"d.py',
        "*star.py",
        ":(exclude)magic.py",
        "-dash.py",
        "trailing space ",
    ]
    """File names git holds as written, which a reader splitting on spaces,
    lines or quotes, or reading a pathspec's magic, would take apart."""

    @lup.promise
    async def a_worktree_is_found_in_every_layout(self, by: Testing) -> None:
        """From any directory in a worktree, git's companion finds its root and its main worktree, in a plain clone, a bare repository's linked worktree and a clone's linked worktree alike; it finds none outside a worktree, a bare repository's own directory among them."""
        with scratch() as root:
            made = layouts(root)
            outside = root / "outside"
            outside.mkdir()

            async def found() -> list[lup.programs.git.Worktree | None]:
                within = [
                    await lup.programs.git.Git.located(each.worktree / "deeper")
                    for each in made
                ]
                none = [
                    await lup.programs.git.Git.located(each)
                    for each in [outside, root / "bare.git"]
                ]
                return [*within, *none]

            for each in made:
                (each.worktree / "deeper").mkdir()
            *within, beside, bare = looped(found)
            for layout, each in zip(made, within, strict=True):
                assert each is not None
                assert each.root == layout.worktree
                assert each.main == layout.main
            assert beside is None
            assert bare is None

    @lup.promise
    async def files_are_what_git_would_commit(self, by: Testing) -> None:
        """A worktree's files are each file git would commit, its name read whole however awkward, tracked or not: never one it ignores, one deleted, or a repository nested in it; and only those under the paths asked for, where some are."""
        committed = by.any(bool)
        with scratch() as root:
            worktree = GIT.made(root / "clone")
            named = {f"src/{each}": "x\n" for each in self.awkward}
            ignored = {".gitignore": "ignored.py\n", "ignored.py": "x\n"}
            GIT.committed(worktree, {"gone.py": "x\n", **ignored})
            (worktree / "gone.py").unlink()
            if committed:
                GIT.committed(worktree, named)
            else:
                for path, text in named.items():
                    (worktree / path).parent.mkdir(exist_ok=True)
                    (worktree / path).write_text(text)
            GIT.made(worktree / "tmp" / "nested")
            (worktree / "tmp" / "nested" / "f.py").write_text("x\n")

            async def listed() -> list[list[PurePosixPath]]:
                found = await lup.programs.git.Git.located(worktree)
                assert found is not None
                return [await found.files(), await found.files([worktree / "src"])]

            every, under = looped(listed)
            names = [PurePosixPath(each) for each in named]
            assert every == sorted([*names, PurePosixPath(".gitignore")])
            assert under == sorted(names)

    @lup.promise
    async def staged_is_what_a_commit_of_everything_holds(self, by: Testing) -> None:
        """The tree a worktree's files are staged as is the tree a commit of every change in it holds, its own index left as it was, a repository nested in it with no commit yet left out."""
        nested = by.any(bool)
        with scratch() as root:
            worktree = GIT.made(root / "clone")
            GIT.committed(worktree, {"kept.py": "x\n", "changed.py": "a\n"})
            (worktree / "changed.py").write_text("b\n")
            (worktree / "new.py").write_text("c\n")
            if nested:
                GIT.made(worktree / "tmp" / "scratch")
            index = (worktree / ".git" / "index").read_bytes()

            async def stage() -> str:
                found = await lup.programs.git.Git.located(worktree)
                assert found is not None
                return await found.staged()

            tree = looped(stage)
            assert (worktree / ".git" / "index").read_bytes() == index
            GIT.git("add", "--all", "--", ".", ":(exclude)tmp", cwd=worktree)
            GIT.git("commit", "--quiet", "--message", "all", cwd=worktree)
            assert tree == GIT.git("rev-parse", "HEAD^{tree}", cwd=worktree)

    @lup.promise
    async def head_and_tracks_say_what_the_worktree_holds(self, by: Testing) -> None:
        """A worktree's `HEAD` is none before its first commit, then that commit; it tracks a file once its index holds it, and not one only on disk."""
        with scratch() as root:
            worktree = GIT.made(root / "clone")
            (worktree / "a.py").write_text("a\n")

            async def asked() -> Asked:
                found = await lup.programs.git.Git.located(worktree)
                assert found is not None
                return Asked(
                    head=await found.head(),
                    tracks=await found.tracks(worktree / "a.py"),
                )

            before = looped(asked)
            commit = GIT.committed(worktree, {})
            after = looped(asked)
            assert before.head is None
            assert not before.tracks
            assert after.head == commit
            assert after.tracks

    @lup.promise
    async def changed_is_each_file_since_where_the_branch_left(
        self, by: Testing
    ) -> None:
        """A worktree's changed files since another branch are each file that differs from where the two meet, as the files are, committed or not, with its bytes there: none for a file added since, and a file deleted since left out."""
        with scratch() as root:
            worktree = GIT.made(root / "clone")
            GIT.committed(
                worktree, {"kept.py": "k\n", "edited.py": "e\n", "gone.py": "g\n"}
            )
            GIT.git("switch", "--quiet", "-c", "side", cwd=worktree)
            (worktree / "gone.py").unlink()
            GIT.committed(worktree, {"edited.py": "e2\n", "added.py": "a\n"})
            GIT.git("switch", "--quiet", "dev", cwd=worktree)
            GIT.committed(worktree, {"elsewhere.py": "x\n"})
            GIT.git("switch", "--quiet", "side", cwd=worktree)
            (worktree / "kept.py").write_text("k2\n")

            async def asked() -> list[lup.programs.git.Changed]:
                found = await lup.programs.git.Git.located(worktree)
                assert found is not None
                return await found.changed(since="dev")

            changed = looped(asked)
            edited = lup.programs.git.Changed(
                path=PurePosixPath("edited.py"), before=b"e\n"
            )
            kept = lup.programs.git.Changed(
                path=PurePosixPath("kept.py"), before=b"k\n"
            )
            added = lup.programs.git.Changed(
                path=PurePosixPath("added.py"), before=None
            )
            assert all(each in changed for each in [edited, kept, added])
            assert all(
                each.path.name not in ["gone.py", "elsewhere.py"] for each in changed
            )

    @lup.promise
    async def a_store_reads_its_own_config_whatever_a_room_plants(
        self, by: Testing
    ) -> None:
        """A store pinned to a repository's common git directory reads that repository's own `config`, even where a room planted a `commondir` there naming a repository of its own, whose `config` names another remote."""
        with scratch() as root:
            clone = GIT.made(root / "clone")
            GIT.git(
                "remote", "add", "origin", "https://example.invalid/ours.git", cwd=clone
            )
            theirs = GIT.made(root / "theirs.git", bare=True)
            GIT.git(
                "remote",
                "add",
                "origin",
                "https://example.invalid/theirs.git",
                cwd=theirs,
            )
            (clone / ".git" / "commondir").write_text(f"{theirs}\n")

            async def read() -> str:
                return await lup.programs.git.Git.pinned(clone / ".git").url("origin")

            assert looped(read) == "https://example.invalid/ours.git"

    @lup.promise
    async def a_commits_files_are_what_its_ids_say(self, by: Testing) -> None:
        """A store lists a commit's files, each by its path and its object, read from each object's own bytes; where a room planted other content under a file's id, reading it is refused."""
        plant = by.any(bool)
        with scratch() as root:
            clone = GIT.made(root / "clone")
            commit = GIT.committed(clone, {"a.py": "a\n", "d/b.py": "b\n", "c": ""})
            blob = GIT.git("rev-parse", f"{commit}:a.py", cwd=clone)
            if plant:
                planted(clone / ".git", blob, b"planted\n")
            store = lup.programs.git.Git.pinned(clone / ".git")

            async def held() -> list[lup.programs.git.Entry]:
                files = await store.held(commit)
                await store.verified("blob", [each.object for each in files])
                return files

            if plant:
                with raises(lup.programs.git.UnverifiedError):
                    looped(held)
            else:
                files = looped(held)
                assert sorted(str(each.path) for each in files) == [
                    "a.py",
                    "c",
                    "d/b.py",
                ]
                assert [each.object for each in files if str(each.path) == "a.py"] == [
                    blob
                ]

    @lup.promise
    async def a_graft_doesnt_change_a_history(self, by: Testing) -> None:
        """Whether a commit's history holds another is read from the commits themselves, whatever graft a room plants to say otherwise."""
        with scratch() as root:
            clone = GIT.made(root / "clone")
            first = GIT.committed(clone, {"a.py": "a\n"})
            GIT.git("checkout", "--quiet", "--orphan", "other", cwd=clone)
            other = GIT.committed(clone, {"b.py": "b\n"})
            (clone / ".git" / "info").mkdir(exist_ok=True)
            (clone / ".git" / "info" / "grafts").write_text(f"{other} {first}\n")

            async def holds() -> bool:
                return await lup.programs.git.Git.pinned(clone / ".git").holds(
                    first, other
                )

            assert not looped(holds)

    @lup.promise
    async def git_reading_a_fifo_is_stopped(self, by: Testing) -> None:
        """git reading a ref a room made a FIFO nothing writes is stopped past its time, and the call refused, rather than waiting for good."""
        with scratch() as root:
            clone = GIT.made(root / "clone")
            GIT.committed(clone, {"a.py": "a\n"})
            GIT.git("pack-refs", "--all", cwd=clone)
            packed = clone / ".git" / "packed-refs"
            packed.unlink()
            os.mkfifo(packed)
            git = lup.programs.git.Git(limit=timedelta(milliseconds=200))
            store = lup.programs.git.Store(git=git, common=clone / ".git")

            async def tip() -> str:
                return await store.branch("dev")

            with raises(lup.programs.git.GitError):
                looped(tip)

    @lup.promise
    async def two_directories_are_compared_alone(self, by: Testing) -> None:
        """Two directories compared show each line changed, added or removed between them, by each file's path from its directory, whatever diff driver a `.gitattributes` among them names."""
        with scratch() as root:
            before, after = root / "before", root / "after"
            before.mkdir()
            after.mkdir()
            (before / "a.py").write_text("old\n")
            (after / "a.py").write_text("new\n")
            for each in (before, after):
                (each / ".gitattributes").write_text("* diff=planted\n")

            async def compared() -> str:
                return await lup.programs.git.Git.diffed(before, after)

            diff = looped(compared)
            assert "-old" in diff.splitlines()
            assert "+new" in diff.splitlines()
