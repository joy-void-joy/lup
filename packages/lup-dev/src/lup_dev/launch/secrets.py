"""Files that hold secrets, hidden from a room: each with a secret's name whose exact content its repository's git objects don't hold, wherever a room mounts a repository.

`docs/launch.md`, *Files with a secret's name*. The names are the declaration's
`secret` role (`CorePaths.secret`), patterns from a worktree's root. A launch
looks in what its room mounts whole: the project's tree, its git directory with
every worktree, and each related repository mounted. A file matching is hidden
unless the object store of the repository it sits in holds its exact content:
it's hashed as git hashes a blob, and the store is asked for that id (`shown`).
The room mounts that store and can read every object in it, so hiding a file
whose content is there protects nothing. A real value added locally is content
git doesn't hold, and a room can't put an object with a secret's content in the
store without knowing that content. A file that's ignored, untracked, or changed
to content git never held is mounted over, read-only, by the launch's empty file
(`launch/hidden.py`), as `.venv` is.

The store rather than a worktree's commit or what git ignores. Which worktree
holds a file comes from git's record of where each worktree is, which a move of
the repository leaves stale. What git ignores is decided from the `.gitignore`
files, `info/exclude` and the index, which a room writes, so `git add -f .env`
in one launch would leave the next one's `.env` in view.

A pattern is matched from the nearest directory holding a `.git`, else from the
tree: a worktree's root, wherever it's been moved. Every file with a secret's
name is hidden in a repository nested in the tree's own, such as a clone under a
worktree's `tmp/`: checking it would mean host git reading a git directory the
room wrote whole, its `config` among it. The store is asked only while it's
self-contained (`stray`): through `objects/info/alternates`, or a link under
`objects/`, git would answer from another repository's store, which the room
can't read, so every file is hidden instead.

Not looked in: what package managers install (`Search.installed`), whose keys
and certificates are packages' own, such as `certifi`'s CA bundle in every
Python environment; and what's hidden already, a worktree's `.venv`. By name
rather than by what a directory holds, since a room could plant a
`pyvenv.cfg` beside a secret to have the next launch pass over it, where it
would have to rename one of the operator's directories, which they'd see. A
directory lup can't list is hidden whole: a room could `chmod` one to have the
next launch pass over it, then `chmod` it back.

The tree is walked through directory descriptors, never following a link, as
the host reads it elsewhere (`launch/hidden.py`), and git runs pinned to each
repository's common directory (`Git.pinned`), never through a worktree's `.git`
file, which a room writes.
"""

import fnmatch
import hashlib
import os
import stat
from contextlib import ExitStack
from itertools import groupby, takewhile
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.git import Git, GitError, stray
from lup_dev.launch.hidden import Found, covering, made, status, walked
from lup_dev.layout import LaunchLayout

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from lup.rooms.container import Mount


def literal(characters: Iterable[str], wildcards: str) -> str:
    """Return the characters of `characters` before the first of `wildcards`.

    >>> literal("id_rsa*", "*?["), literal("plain", "*?[")
    ('id_rsa', 'plain')
    """
    return "".join(takewhile(lambda character: character not in wildcards, characters))


def runs(last: str) -> list[str]:
    """Return each run of characters between the wildcards of `last`, a pattern's last part holding no bracket expression.

    >>> runs("*credentials*.json")
    ['credentials', '.json']
    """
    grouped = groupby(last, key=lambda character: character in "*?")
    return ["".join(run) for wild, run in grouped if not wild]


class Pattern(Model):
    """One pattern of the `secret` role, and what a file's name must hold to match its last part."""

    pattern: str
    last: str
    """Its last part, which a file's name must match."""
    prefix: str
    """What a name matching `last` starts with, up to its first wildcard."""
    suffix: str
    """What a name matching `last` ends with, after its last wildcard."""
    part: str
    """The longest text a name matching `last` holds: its prefix, its suffix,
    or, without a bracket expression, a run between two wildcards. Empty where
    there's none, so every name is tested."""

    @classmethod
    def of(cls, pattern: str) -> Pattern:
        """Read `pattern`'s last part, and the text a name matching it must hold.

        >>> each = Pattern.of("**/*[sS]ervice*[aA]ccount*.json")
        >>> each.last, each.prefix, each.suffix, each.part
        ('*[sS]ervice*[aA]ccount*.json', '', '.json', '.json')
        >>> each = Pattern.of("**/*credentials*.json")
        >>> each.prefix, each.suffix, each.part
        ('', '.json', 'credentials')
        >>> each = Pattern.of("config/master.key")
        >>> each.last, each.prefix, each.suffix, each.part
        ('master.key', 'master.key', 'master.key', 'master.key')
        """
        last = PurePosixPath(pattern).name
        prefix = literal(last, "*?[")
        suffix = "".join(reversed(literal(reversed(last), "*?]")))
        inner = [] if "[" in last else runs(last)
        return cls(
            pattern=pattern,
            last=last,
            prefix=prefix,
            suffix=suffix,
            part=max([prefix, suffix, *inner], key=len),
        )

    def named(self, name: str) -> bool:
        """Say whether a file called `name` matches the pattern's last part."""
        return (
            name.startswith(self.prefix)
            and name.endswith(self.suffix)
            and fnmatch.fnmatchcase(name, self.last)
        )


class Searched(Model):
    """What a walk of one tree found: the files with a secret's name, and the directories it couldn't list."""

    files: list[Path] = []
    nested: list[Path] = []
    """Those of `files` in a repository nested in the tree's own, hidden whatever
    they hold."""
    large: list[Path] = []
    """Those of `files` holding more than `Search.largest` bytes, hidden unread."""
    unlisted: list[Path] = []


class Search(Model):
    """What a launch looks for in the trees its room mounts, and what it passes over."""

    patterns: list[str]
    """The declaration's `secret` role: paths from a worktree's root, matched
    whole (`PurePath.full_match`)."""
    installed: list[str] = ["node_modules", "site-packages", "dist-packages"]
    """Directories package managers install into, by name, not looked in: their
    keys and certificates are packages' own. Each one of 95 `cacert.pem` found in
    the operator's repositories' environments was `certifi`'s."""
    hidden: list[Path] = []
    """Paths hidden already, not looked in: each worktree's `.venv`."""
    largest: int = 1 << 20
    """The most bytes a file with a secret's name holds to be read and checked,
    1 MiB; one holding more is hidden unread, and said so. The files these names
    give are small, the largest of the 86 in view on the operator's machine 6 KB,
    and a room could plant a sparse one of a terabyte, in an instant, for the next
    launch to hash."""

    def found(self, tree: Path, git: Path | None) -> Searched:
        """Walk `tree`, holding the repository whose common git directory is `git`, for each file whose path from its worktree's root (`Listing.root`) matches a pattern, and those of them in a repository nested in it; and each directory that couldn't be listed.

        A nested repository is a git directory other than `git` (`Listing.git`),
        with what's under it, and the directory holding it where it's that
        directory's `.git`: a clone's worktree. A `.git` directory that isn't a
        git directory, which git wouldn't read either, nests nothing.

        A directory's names are tested first, all at once in C, for the text
        each pattern's last part holds (`Pattern.part`), so the millions of files
        a tree may hold cost little more than listing them: only a name in a
        directory holding some pattern's text is matched, against those
        patterns alone.
        """
        patterns = [Pattern.of(each) for each in self.patterns]
        unlisted: list[Path] = []
        repositories: list[Path] = []

        def files() -> Iterator[Path]:
            for listing in listed(tree, self.installed, self.hidden, unlisted):
                if listing.git and listing.directory != git:
                    directory = listing.directory
                    repositories.append(
                        directory.parent if directory.name == ".git" else directory
                    )
                joined = "\0".join(listing.names)
                present = [each for each in patterns if each.part in joined]
                for name in listing.names if present else []:
                    if not any(each.named(name) for each in present):
                        continue
                    path = listing.directory / name
                    relative = PurePath(path.relative_to(listing.root))
                    if any(relative.full_match(each.pattern) for each in patterns):
                        yield path

        matched = list(files())
        holding = dict.fromkeys(repositories)
        nested = [
            path for path in matched if any(each in holding for each in path.parents)
        ]
        large = [
            path
            for path in matched
            if path not in nested
            and (seen := status(tree, path)) is not None
            and seen.st_size > self.largest
        ]
        return Searched(files=matched, nested=nested, large=large, unlisted=unlisted)


class Listing(Model):
    """A directory being walked: the regular files in it, the root of the worktree it's in, whether it's a git directory, its descriptor, held while what's under it is walked, and the directories in it still to walk."""

    directory: Path
    names: list[str]
    """The names of the regular files in it."""
    root: Path
    """The root of the worktree it's in, which patterns are matched from: the
    nearest directory at or above it holding a `.git` file or directory, else
    the tree walked."""
    git: bool
    """Whether it's a git directory: a `HEAD` file, and `objects/` and `refs/`,
    in it."""
    descriptor: int
    inside: list[str]
    """The names of the directories in it still to walk, taken as each is."""


def listed(
    tree: Path, installed: list[str], hidden: list[Path], unlisted: list[Path]
) -> Iterator[Listing]:
    """Yield each directory under `tree`, itself among them, with the names of the regular files in it, never following a link; passing over a directory named among `installed` or at one of `hidden`, and adding to `unlisted` each one that couldn't be listed.

    Each says the root of the worktree it's in (`Listing.root`), from its
    entries and its parent's: never from what a `.git` file says, which in a
    moved worktree names where it was. Depth first, holding a descriptor for
    each directory on the way down alone, so a directory holding thousands
    never runs out of them. Each listing is built without validation
    (`model_construct`): a tree may hold a hundred thousand directories, and
    what's built is the walk's own.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    hiding = [each.name for each in hidden]

    def entered(directory: Path, name: str, above: Listing | None) -> Listing | None:
        try:
            descriptor = (
                os.open(tree, flags)
                if above is None
                else os.open(name, flags, dir_fd=above.descriptor)
            )
        except OSError:
            unlisted.append(directory)
            return None
        try:
            # lup: ignore("os-file-ops", why="pathlib has no listing relative to a directory's descriptor, which is what keeps a link the room swaps in on the way from aiming the walk elsewhere")
            with os.scandir(descriptor) as listing:
                entries = list(listing)
        except OSError:
            os.close(descriptor)
            unlisted.append(directory)
            return None
        names = [each.name for each in entries if each.is_file(follow_symlinks=False)]
        directories = [
            each.name for each in entries if each.is_dir(follow_symlinks=False)
        ]
        return Listing.model_construct(
            directory=directory,
            names=names,
            root=(
                directory
                if above is None or ".git" in names or ".git" in directories
                else above.root
            ),
            git="objects" in directories and "refs" in directories and "HEAD" in names,
            descriptor=descriptor,
            inside=[
                each
                for each in directories
                if each not in installed
                and (each not in hiding or directory / each not in hidden)
            ],
        )

    top = entered(tree, tree.name, None)
    walking = [] if top is None else [top]
    try:
        yield from walking
        while walking:
            current = walking[-1]
            if not current.inside:
                os.close(walking.pop().descriptor)
                continue
            name = current.inside.pop()
            below = entered(current.directory / name, name, current)
            if below is not None:
                walking.append(below)
                yield below
    finally:
        for each in walking:
            os.close(each.descriptor)


def git_directory(path: Path) -> Path | None:
    """Return the common git directory of the repository a room mounts at `path`, without running git there: a clone's `.git` directory, or a bare repository's own; none for anything else, whose files no store is asked about.

    git found from `path` would follow a `.git` file or a `commondir` file,
    either of which a room writes in a repository it works in; pinned there, it
    reads neither.
    """
    clone = path / ".git"
    if clone.is_dir() and not clone.is_symlink():
        return clone
    bare = all((path / name).exists() for name in ["HEAD", "objects", "refs"])
    return path if bare else None


def blob(tree: Path, path: Path, hashing: str, largest: int) -> str | None:
    """Return the id git would give the regular file at `path`, inside `tree`, as a blob hashed with `hashing` (`sha1` or `sha256`); none where it isn't one, or holds more than `largest` bytes. Read through the directory holding it, never following a link.

    A file that changes size as it's read gets an id no object has.
    """
    with ExitStack() as stack:
        holding = walked(tree, path, stack)
        if holding is None:
            return None
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            reading = os.open(path.name, flags, dir_fd=holding)
        except OSError:
            return None
        stack.callback(os.close, reading)
        seen = os.fstat(reading)
        if not stat.S_ISREG(seen.st_mode) or seen.st_size > largest:
            return None
        digest = hashlib.new(hashing, f"blob {seen.st_size}\0".encode())
        for chunk in iter(lambda: os.read(reading, 1 << 20), b""):
            digest.update(chunk)
        return digest.hexdigest()


def shown(tree: Path, git: Path | None, files: list[Path], largest: int) -> list[Path]:
    """Return those of `files`, inside `tree`, whose exact content the object store of the repository whose common git directory is `git` holds, asked of git pinned there; none of those holding more than `largest` bytes, which aren't read.

    None where there's no repository, git can't say, or the store reads objects
    from outside itself (`stray`), from a store the room can't read.
    """
    if git is None or not files or stray(git / "objects"):
        return []
    pinned = Git.pinned(git)
    try:
        hashing = pinned.text("rev-parse", "--show-object-format")
        hashed = {path: blob(tree, path, hashing, largest) for path in files}
        ids = [each for each in hashed.values() if each is not None]
        held = pinned.blobs(list(dict.fromkeys(ids)))
    except GitError:
        return []
    return [path for path, each in hashed.items() if each in held]


class Tree(Model):
    """A directory a room mounts whole, and the common git directory of the repository it holds, where it holds one."""

    path: Path
    git: Path | None


def hiding(search: Search, tree: Tree) -> Searched:
    """Return what to hide in `tree`: each file with a secret's name whose exact content its repository's object store doesn't hold, each in a repository nested in the tree's own, and each directory that couldn't be listed."""
    searched = search.found(tree.path, tree.git)
    unread = [*searched.nested, *searched.large]
    asked = [each for each in searched.files if each not in unread]
    held = shown(tree.path, tree.git, asked, search.largest)
    return searched.model_copy(
        update={"files": [each for each in searched.files if each not in held]}
    )


class RoomSecrets(Model):
    """The files with a secret's name a launch hides from its room, and each directory it couldn't look in, hidden whole (`docs/launch.md`, *Files with a secret's name*)."""

    launch: LaunchLayout
    search: Search
    own: Tree
    """The project's tree, looked in again at the launch's end."""
    found: list[Found] = []
    """Each path hidden, as it was found."""
    large: list[Path] = []
    """Each file among `found` hidden unread, holding more than `Search.largest`
    bytes."""

    @classmethod
    def of(
        cls, search: Search, own: Tree, related: list[Tree], launch: LaunchLayout
    ) -> RoomSecrets:
        """Look in the project's tree `own` and each of the `related` repositories mounted, as the room is about to start."""
        searched = [(tree, hiding(search, tree)) for tree in [own, *related]]
        found = [
            seen
            for tree, each in searched
            for path in [*each.files, *each.unlisted]
            if (seen := Found.at(tree.path, path)) is not None
        ]
        large = [path for _, each in searched for path in each.large]
        return cls(launch=launch, search=search, own=own, found=found, large=large)

    @property
    def mounts(self) -> list[Mount]:
        """The launch's empty file read-only over each file found, its empty directory over each directory it couldn't list."""
        return covering(self.found, self.launch)

    def write(self) -> None:
        """Make what the mounts are mounted from."""
        made(self.launch)

    def said(self) -> list[str]:
        """Return what the launch says of what it hides, where it hides anything."""
        files = [each.path for each in self.found if not each.directory]
        bound = f"over {self.search.largest / (1 << 20):g} MiB"
        listed = "\n".join(
            f"  {each} (too large to check, {bound})"
            if each in self.large
            else f"  {each}"
            for each in files
        )
        named = (
            "Hidden from the room, each reading as an empty file: the files with a "
            "secret's name whose content their repository's git objects don't hold "
            "(`docs/launch.md`, *Files with a secret's name*):\n"
            f"{listed}"
        )
        return [
            *([named] if files else []),
            *(
                f"Hidden from the room whole, since lup couldn't look in it for files "
                f"with a secret's name: {each.path}"
                for each in self.found
                if each.directory
            ),
        ]

    def end(self) -> list[str]:
        """Look in the project's tree again as the launch ends, and say each file with a secret's name that appeared or changed while the room ran, and each directory lup can't look in that it could as the room started.

        The host's tools read such a file, so the operator looks at it first;
        none is removed, since one may be the operator's own.
        """
        before = [each.path for each in self.found]
        searched = hiding(self.search, self.own)
        files = [path for path in searched.files if path not in before]
        listed = "\n".join(f"  {each}" for each in files)
        named = (
            "These files with a secret's name appeared or changed while the room "
            "ran, so the room may have written them, and your tools read such a "
            f"file: look at each before they do.\n{listed}"
        )
        return [
            *([named] if files else []),
            *(
                f"lup can't look in {each} as the room ends, which it could as it "
                "started."
                for each in searched.unlisted
                if each not in before
            ),
        ]
