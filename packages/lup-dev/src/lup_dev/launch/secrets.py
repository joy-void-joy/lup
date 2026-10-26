"""Files that hold secrets, hidden from a room: each with a secret's name that no commit holds as it is, wherever a room mounts a repository.

`docs/launch.md`, *Files with a secret's name*. The names are the declaration's
`secret` role (`CorePaths.secret`), patterns from a worktree's root. A launch
looks in what its room mounts whole: the project's tree, its git directory with
every worktree, and each related repository mounted. A file matching is hidden
unless its worktree's commit holds it with exactly its content: a tracked
`.env.example` unchanged is the repository's history already, and stays.
Ignored, untracked, or changed since, it's mounted over, read-only, by the
launch's empty file (`launch/hidden.py`), as `.venv` is; one outside every
worktree, which no commit holds, too.

The commit rather than what git ignores: a room writes the `.gitignore` files,
`info/exclude` and the index git decides that from, so `git add -f .env` in one
launch would leave the next one's `.env` in view; a commit holding a file's
content can't be made by a room that never read it.

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
from itertools import batched, groupby, takewhile
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.git import Git, GitError, nul_separated
from lup_dev.launch.hidden import Found, covering, made, walked
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

    def found(self, tree: Path, roots: list[Path]) -> Searched:
        """Walk `tree` for each file whose path from its worktree's root, the nearest of `roots` holding it, else from `tree`, matches a pattern; and each directory that couldn't be listed.

        A directory's names are tested first, all at once in C, for the text
        each pattern's last part holds (`Pattern.part`), so the millions of files
        a tree may hold cost little more than listing them: only a name in a
        directory holding some pattern's text is matched, against those
        patterns alone.
        """
        patterns = [Pattern.of(each) for each in self.patterns]
        nearest = sorted(roots, key=lambda root: len(root.parts), reverse=True)
        unlisted: list[Path] = []

        def matching(path: Path) -> bool:
            root = next((each for each in nearest if path.is_relative_to(each)), tree)
            relative = PurePath(path.relative_to(root))
            return any(relative.full_match(each.pattern) for each in patterns)

        def files() -> Iterator[Path]:
            for listing in listed(tree, self.installed, self.hidden, unlisted):
                joined = "\0".join(listing.names)
                present = [each for each in patterns if each.part in joined]
                for name in listing.names if present else []:
                    if not any(each.named(name) for each in present):
                        continue
                    if matching(path := listing.directory / name):
                        yield path

        return Searched(files=list(files()), unlisted=unlisted)


class Listing(Model):
    """A directory being walked: the regular files in it, its descriptor, held while what's under it is walked, and the directories in it still to walk."""

    directory: Path
    names: list[str]
    """The names of the regular files in it."""
    descriptor: int
    inside: list[str]
    """The names of the directories in it still to walk, taken as each is."""


def listed(
    tree: Path, installed: list[str], hidden: list[Path], unlisted: list[Path]
) -> Iterator[Listing]:
    """Yield each directory under `tree`, itself among them, with the names of the regular files in it, never following a link; passing over a directory named among `installed` or at one of `hidden`, and adding to `unlisted` each one that couldn't be listed.

    Depth first, holding a descriptor for each directory on the way down
    alone, so a directory holding thousands never runs out of them. Each
    listing is built without validation (`model_construct`): a tree may hold a
    hundred thousand directories, and what's built is the walk's own.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    hiding = [each.name for each in hidden]

    def entered(directory: Path, name: str, holding: int | None) -> Listing | None:
        try:
            descriptor = (
                os.open(tree, flags)
                if holding is None
                else os.open(name, flags, dir_fd=holding)
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
        return Listing.model_construct(
            directory=directory,
            names=[
                each.name for each in entries if each.is_file(follow_symlinks=False)
            ],
            descriptor=descriptor,
            inside=[
                each.name
                for each in entries
                if each.is_dir(follow_symlinks=False)
                and each.name not in installed
                and (each.name not in hiding or directory / each.name not in hidden)
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
            below = entered(current.directory / name, name, current.descriptor)
            if below is not None:
                walking.append(below)
                yield below
    finally:
        for each in walking:
            os.close(each.descriptor)


class Checkout(Model):
    """One of a repository's worktrees as git lists it from the common directory, and the commit it's at."""

    root: Path
    commit: str | None
    """The commit its `HEAD` is at; none on a branch with no commit yet, and for
    a bare repository's own directory, which holds no commit's files."""


def checkouts(common: Path) -> list[Checkout]:
    """Return each worktree of the repository whose common git directory is `common`, as `git worktree list` gives them there, pinned (`Git.pinned`)."""
    listed = Git.pinned(common).run("worktree", "list", "--porcelain", "-z").output
    fields = nul_separated(listed)
    starts = [at for at, field in enumerate(fields) if field.startswith("worktree ")]
    records = [
        fields[start:end]
        for start, end in zip(starts, [*starts[1:], len(fields)], strict=True)
    ]

    def commit(record: list[str]) -> str | None:
        heads = [
            each.removeprefix("HEAD ") for each in record if each.startswith("HEAD ")
        ]
        return next(
            (each for each in heads if any(digit != "0" for digit in each)), None
        )

    return [
        Checkout(root=Path(record[0].removeprefix("worktree ")), commit=commit(record))
        for record in records
    ]


def git_directory(path: Path) -> Path | None:
    """Return the common git directory of the repository a room mounts at `path`, without running git there: a clone's `.git` directory, or a bare repository's own; none for anything else, in which no commit holds a file.

    git found from `path` would follow a `.git` file or a `commondir` file,
    either of which a room writes in a repository it works in; pinned there, it
    reads neither.
    """
    clone = path / ".git"
    if clone.is_dir() and not clone.is_symlink():
        return clone
    bare = all((path / name).exists() for name in ["HEAD", "objects", "refs"])
    return path if bare else None


class Blob(Model):
    """A file as a commit holds it: its object's id and size."""

    object: str
    size: int


def committed(git: Git, commit: str, paths: list[Path]) -> dict[PurePosixPath, Blob]:
    """Return each of `paths`, from the worktree's root, that `commit` holds as a file, with its blob; none where git can't read the commit."""
    shape = "%(objecttype)%x00%(objectname)%x00%(objectsize)%x00%(path)"

    def listed(asked: list[str]) -> list[str]:
        arguments = ["-r", "-z", "--full-tree", f"--format={shape}", commit, "--"]
        found = git.run("--literal-pathspecs", "ls-tree", *arguments, *asked)
        return nul_separated(found.output)

    try:
        fields = [
            field
            for some in batched(paths, 256, strict=False)
            for field in listed([str(each) for each in some])
        ]
    except GitError:
        return {}
    return {
        PurePosixPath(path): Blob(object=name, size=int(size))
        for kind, name, size, path in batched(fields, 4, strict=True)
        if kind == "blob"
    }


def same(tree: Path, path: Path, blob: Blob, hashing: str) -> bool:
    """Say whether the regular file at `path`, inside `tree`, holds exactly `blob`'s content, hashed as git hashes a blob with `hashing` (`sha1` or `sha256`); read through the directory holding it, never following a link."""
    with ExitStack() as stack:
        holding = walked(tree, path, stack)
        if holding is None:
            return False
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            reading = os.open(path.name, flags, dir_fd=holding)
        except OSError:
            return False
        stack.callback(os.close, reading)
        seen = os.fstat(reading)
        if not stat.S_ISREG(seen.st_mode) or seen.st_size != blob.size:
            return False
        digest = hashlib.new(hashing, f"blob {blob.size}\0".encode())
        for chunk in iter(lambda: os.read(reading, 1 << 20), b""):
            digest.update(chunk)
        return digest.hexdigest() == blob.object


def unheld(
    tree: Path, git: Path | None, at: list[Checkout], files: list[Path]
) -> list[Path]:
    """Return each of `files`, inside `tree`, that its worktree's commit doesn't hold with exactly its content, in the repository whose common git directory is `git`, whose worktrees are `at`: all of them where there's none."""
    if git is None or not files:
        return files
    pinned = Git.pinned(git)
    try:
        hashing = pinned.text("rev-parse", "--show-object-format")
    except GitError:
        return files
    nearest = sorted(at, key=lambda each: len(each.root.parts), reverse=True)
    holding = {
        path: next((each for each in nearest if path.is_relative_to(each.root)), None)
        for path in files
    }
    blobs = {
        each.root: committed(
            pinned,
            each.commit,
            [
                path.relative_to(each.root)
                for path, held in holding.items()
                if held == each
            ],
        )
        for each in nearest
        if each.commit is not None and each in holding.values()
    }

    def held(path: Path) -> bool:
        checkout = holding[path]
        if checkout is None or checkout.commit is None:
            return False
        blob = blobs[checkout.root].get(PurePosixPath(path.relative_to(checkout.root)))
        return blob is not None and same(tree, path, blob, hashing)

    return [path for path in files if not held(path)]


class Tree(Model):
    """A directory a room mounts whole, and the common git directory of the repository it holds, where it holds one."""

    path: Path
    git: Path | None


def hiding(search: Search, tree: Tree) -> Searched:
    """Return what to hide in `tree`: each file with a secret's name its worktree's commit doesn't hold as it is, and each directory that couldn't be listed.

    Where git can't list the repository's worktrees, no commit holds a file.
    """
    try:
        at = [] if tree.git is None else checkouts(tree.git)
    except GitError:
        tree = tree.model_copy(update={"git": None})
        at = []
    searched = search.found(tree.path, [each.root for each in at])
    return Searched(
        files=unheld(tree.path, tree.git, at, searched.files),
        unlisted=searched.unlisted,
    )


class RoomSecrets(Model):
    """The files with a secret's name a launch hides from its room, and each directory it couldn't look in, hidden whole (`docs/launch.md`, *Files with a secret's name*)."""

    launch: LaunchLayout
    search: Search
    own: Tree
    """The project's tree, looked in again at the launch's end."""
    found: list[Found] = []
    """Each path hidden, as it was found."""

    @classmethod
    def of(
        cls, search: Search, own: Tree, related: list[Tree], launch: LaunchLayout
    ) -> RoomSecrets:
        """Look in the project's tree `own` and each of the `related` repositories mounted, as the room is about to start."""

        def hidden(tree: Tree) -> list[Found]:
            searched = hiding(search, tree)
            return [
                seen
                for path in [*searched.files, *searched.unlisted]
                if (seen := Found.at(tree.path, path)) is not None
            ]

        found = [seen for tree in [own, *related] for seen in hidden(tree)]
        return cls(launch=launch, search=search, own=own, found=found)

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
        listed = "\n".join(f"  {each}" for each in files)
        named = (
            "Hidden from the room, each reading as an empty file: the files with a "
            "secret's name no commit holds as they are "
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
