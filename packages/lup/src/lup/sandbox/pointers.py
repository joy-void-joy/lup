"""Whether a linked worktree still points where the repository put it.

A linked worktree lives between three pointer files, and the value of each is
where the *next* thing git reads lives: the worktree's `.git` file holds
`gitdir: <entry>`, the entry's `commondir` holds the shared directory, and the
entry's `gitdir` holds the way back to the `.git` file. Host git follows them
in that order, and reads its config -- `core.hooksPath`, `core.fsmonitor`,
`core.sshCommand`, `alias.*`, `credential.helper`, the `merge.*.driver` family,
every key that hands git a command line -- from wherever they lead. None of
the three is a key; each is the address of the file the keys are read from.

Why this is its own guard rather than a mount. The three files sit in trees the
container writes: the `.git` file is in the checkout, `commondir` and `gitdir`
in the administrative entry under the shared directory. A mount cannot hold
them read-only without holding them against `git worktree remove`, which
unlinks exactly these files -- a read-only bind refuses the removal with an
errno about a busy device, the workflow this repository mandates breaking on
the guard meant to protect it. So the pointer is not pinned; it is *verified*,
on the host, against the one thing the container cannot forge: the shared
directory the launcher already trusts, passed in rather than read back through
the pointer under test.

What the verification reduces the escape to. A pointer forced to keep naming
`<common>/worktrees/<n>` -> `<common>` cannot name a directory the container
built, so the only config host git will read for a worktree is the one under
the shared directory -- which `config` and `hooks/` there are already guarded
against, by mount and by the semantic policy both. The pointer escape collapses
into the config escape, which is answered. What it does not answer: a `git`
the operator runs by hand in a redirected worktree, outside every lup path that
consults this. That git follows the moved pointer like any other, so the guard
is only as present as the commands that call it -- which is why it is wired
into the worktree lifecycle rather than offered as advice.

Anchored, never bootstrapped. The trusted `common` is found from the layout --
the `tree/` a worktree sits in, a bare clone's own directory, a plain
checkout's `.git` directory -- and every pointer is validated against that one
`common`. Deriving `common` from the worktree under test would let a forged
`commondir` name its own fake shared directory and pass: the check would ask
the attacker where the truth is. So a root with no such anchor, a linked
worktree outside any `tree/`, is refused rather than read through its pointer.
What is absent is left unjudged -- a worktree whose directory has gone, an
entry `git worktree add` has not finished writing -- because git opens neither
and so reads no config through it.
"""

from collections.abc import Iterator, Sequence
from itertools import takewhile
from pathlib import Path

from pydantic import BaseModel


class PointerDrift(BaseModel, frozen=True):
    """One worktree pointer that no longer names where the repository put it."""

    worktree: Path
    pointer: Path
    names: str
    expected: str


def gitdir_target(dot_git: Path) -> Path | None:
    """The path a worktree's `.git` file points its gitdir at, or ``None``.

    ``None`` where `.git` is a real directory -- a plain checkout or the shared
    directory itself -- rather than the one-line `gitdir: <path>` pointer a
    linked worktree carries. A relative pointer, which git writes under
    `worktree.useRelativePaths`, is resolved against the directory holding the
    `.git` file, as git resolves it, rather than against whoever asks.
    """
    if not dot_git.is_file():
        return None
    line = dot_git.read_text().strip()
    if not line.startswith("gitdir:"):
        return None
    return resolved_against(dot_git.parent, line.removeprefix("gitdir:"))


def resolved_against(entry: Path, contents: str) -> Path:
    """A pointer file's value as an absolute path, from an entry that may be relative.

    `commondir` is written relative to the administrative entry (`../..`), while
    `gitdir` is written absolute; resolving each against the entry answers both
    without asking which it was.
    """
    named = Path(contents.strip())
    return named if named.is_absolute() else entry / named


def is_repository_directory(path: Path) -> bool:
    """Whether git would take this directory as a repository of its own.

    Git accepts a directory as a gitdir when it holds a `HEAD`, an `objects/`
    and a `refs/` -- the latter two read through `commondir` where there is
    one. A bare clone passes on its own; an administrative entry never does,
    because it keeps no `objects/` of its own, so an entry that has lost its
    `commondir` is refused by git outright and runs nothing. One that has
    grown `objects/` and `refs/` stands alone, and its own `config` is the
    config git reads.
    """
    return (
        (path / "HEAD").is_file()
        and (path / "objects").is_dir()
        and (path / "refs").is_dir()
    )


def entry_drift(entry: Path, common: Path, worktree: Path) -> Iterator[PointerDrift]:
    """How one administrative entry no longer leads back to ``common``.

    A `commondir` naming anywhere else is one way. A missing `commondir` is
    the other only where the entry stands alone as a repository; without that
    it is an entry mid-`git worktree add`, or one git refuses to open, and
    neither reads a config.
    """
    commondir_file = entry / "commondir"
    if not commondir_file.is_file():
        if is_repository_directory(entry):
            yield PointerDrift(
                worktree=worktree,
                pointer=commondir_file,
                names="nothing, leaving the entry a repository of its own",
                expected=str(common),
            )
        return
    named = resolved_against(entry, commondir_file.read_text())
    if named.resolve() != common.resolve():
        yield PointerDrift(
            worktree=worktree,
            pointer=commondir_file,
            names=str(named),
            expected=str(common),
        )


def chain_drift(checkout: Path, common: Path) -> Iterator[PointerDrift]:
    """How a checkout's own `.git` no longer leads into ``common``.

    Read from the checkout's side, the order host git follows: the `.git`
    pointer names an entry, and the entry's `commondir` names the shared
    directory. Asked of the checkout itself rather than found through the
    entries, because an entry's `gitdir` back-pointer is as writable as the
    rest -- rewritten, it hides its worktree from a scan that starts there. A
    checkout whose `.git` exists but is no pointer is the pointer swapped for a
    gitdir of its own; one with no `.git` at all has nothing here to redirect.
    """
    dot_git = checkout / ".git"
    target = gitdir_target(dot_git)
    if target is None:
        if holds_git(checkout):
            yield PointerDrift(
                worktree=checkout,
                pointer=dot_git,
                names="no gitdir pointer",
                expected=f"an entry in {common / 'worktrees'}",
            )
        return
    if target.resolve().parent != (common / "worktrees").resolve():
        yield PointerDrift(
            worktree=checkout,
            pointer=dot_git,
            names=str(target),
            expected=f"an entry in {common / 'worktrees'}",
        )
        return
    yield from entry_drift(target, common, checkout)


def holds_git(path: Path) -> bool:
    """Whether a directory holds a `.git` of any kind, even a dangling symlink."""
    return (path / ".git").exists() or (path / ".git").is_symlink()


def tree_checkouts(tree: Path) -> list[Path]:
    """Every directory in ``tree`` that stands where a worktree stands.

    Each child holding a `.git`, and, for a child holding none, each of its
    own children -- a resolver run gathers its workers one level down, in
    `tree/<name>-resolve-<id>/`.
    """
    children = sorted(child for child in tree.iterdir() if child.is_dir())
    return [
        checkout
        for child in children
        for checkout in (
            [child]
            if holds_git(child)
            else sorted(inner for inner in child.iterdir() if inner.is_dir())
        )
    ]


def pointer_drift(common: Path, checkouts: Sequence[Path] = ()) -> list[PointerDrift]:
    """Every pointer of this repository that no longer leads to ``common``.

    ``common`` is the trusted shared directory -- the caller's, never re-read
    through a pointer under test. Three readings, one per direction a pointer
    can be forged in. The shared directory holds no `commondir` of its own,
    since git run there would follow one. Each administrative entry leads back
    to ``common``, and the `.git` its `gitdir` names still points at the entry
    -- a `.git` that has become a directory, or anything but that pointer, is
    one git reads instead. And each of ``checkouts``, the worktrees the
    caller's layout says belong here, is followed from its own `.git`, so
    rewriting an entry's back-pointer does not hide the worktree it described.

    A value that resolves elsewhere is a redirection, reported once per
    pointer file with what it names against what the repository put there.
    What is absent is left unjudged: a worktree whose directory has gone, or an
    entry `git worktree add` has not finished writing.
    """

    def drifted() -> Iterator[PointerDrift]:
        planted = common / "commondir"
        if planted.exists():
            yield PointerDrift(
                worktree=common,
                pointer=planted,
                names=planted.read_text().strip()
                if planted.is_file()
                else "a directory",
                expected="no commondir, since a shared directory names no other",
            )
        entries = common / "worktrees"
        for entry in sorted(entries.iterdir()) if entries.is_dir() else []:
            gitdir_file = entry / "gitdir"
            if not gitdir_file.is_file():
                continue
            dot_git = resolved_against(entry, gitdir_file.read_text())
            yield from entry_drift(entry, common, dot_git.parent)
            back = gitdir_target(dot_git)
            present = dot_git.exists() or dot_git.is_symlink()
            if present and (back is None or back.resolve() != entry.resolve()):
                yield PointerDrift(
                    worktree=dot_git.parent,
                    pointer=dot_git,
                    names=str(back) if back is not None else "no gitdir pointer",
                    expected=str(entry),
                )
        for checkout in checkouts:
            yield from chain_drift(checkout, common)

    return list({drift.pointer: drift for drift in drifted()}.values())


def refusal(drifts: list[PointerDrift]) -> str:
    """One message naming every redirected pointer and where it now leads.

    Empty for no drift, so a caller says nothing where nothing moved. Full
    rather than truncated: each redirected worktree is a place host git would
    read a container-chosen config, and a caller that dropped one would run git
    in it believing the set was clean.
    """
    if not drifts:
        return ""
    lines = [
        f"  {drift.worktree}: {drift.pointer.name} names {drift.names}, "
        f"not {drift.expected}"
        for drift in drifts
    ]
    return (
        "Worktree pointers were redirected out of the repository, so host git "
        "in these worktrees would read a config the container chose:\n"
        + "\n".join(lines)
    )


class RootAnchor(BaseModel, frozen=True):
    """Where a root's shared directory is, found from the layout alone.

    ``checkout`` is the directory git's discovery stops at from ``root``, and
    ``common`` the shared directory whose config git would read there -- each
    reached by looking at what the path holds, never by reading a pointer
    whose value is the thing under test. ``linked`` says the checkout must be
    a linked worktree of ``common``, to be followed from its own `.git`.
    ``refusal`` says why no such anchor exists; all empty means ``root`` sits
    in no repository at all.
    """

    root: Path
    checkout: Path | None = None
    common: Path | None = None
    linked: bool = False
    refusal: str = ""


def discovered(root: Path, holder: Path | None = None) -> Path | None:
    """Where git's discovery from ``root`` stops, searching below ``holder``.

    The first directory holding a `.git`, or being a repository itself --
    the two things git looks for at each level on its way up.
    """
    return next(
        (
            candidate
            for candidate in takewhile(
                lambda path: path != holder, (root, *root.parents)
            )
            if holds_git(candidate) or is_repository_directory(candidate)
        ),
        None,
    )


def own_common(path: Path) -> Path | None:
    """The shared directory of a repository that is one by what it holds.

    A `.git` directory, or the directory itself being a repository -- the two
    shapes whose shared directory is where it stands rather than where a
    pointer says.
    """
    dot_git = path / ".git"
    if dot_git.is_dir() and not dot_git.is_symlink():
        return dot_git
    if not dot_git.exists() and is_repository_directory(path):
        return path
    return None


def in_tree(root: Path, tree: Path, common: Path) -> RootAnchor:
    """A root inside a repository's `tree/`, which only its linked worktrees fill.

    Whatever discovery reaches first between the root and the repository
    holding `tree/` must be a linked worktree of it, followed from its own
    `.git`. Anything else there -- a `.git` that is a directory, a symlink, a
    directory that is a repository of its own, `tree/` itself given one -- is
    where git would read a config of its own, and swapping a worktree's
    pointer for a directory is the plainest way to plant one. Nothing found
    means git reaches the holder itself.
    """
    checkout = discovered(root, tree.parent)
    if checkout is None:
        return RootAnchor(root=root, checkout=tree.parent, common=common)
    if gitdir_target(checkout / ".git") is None:
        return RootAnchor(
            root=root,
            checkout=checkout,
            refusal=(
                f"{checkout} sits in {tree} without being a linked worktree of "
                f"{tree.parent}, so git run there would read a config of its own"
            ),
        )
    return RootAnchor(root=root, checkout=checkout, common=common, linked=True)


def outside_tree(root: Path) -> RootAnchor:
    """A root in no repository's `tree/`: a clone, a plain checkout, or neither.

    A repository directory is its own shared directory, which is how a bare
    clone mounted whole is anchored on its own path, and a `.git` directory is
    a plain checkout's. A `.git` pointer here marks a linked worktree with no
    anchor but the pointer under test, and a `.git` symlink names wherever it
    points: both are refused, with the reason, rather than read through.
    """
    checkout = discovered(root)
    if checkout is None:
        return RootAnchor(root=root)
    dot_git = checkout / ".git"
    if dot_git.is_symlink():
        return RootAnchor(
            root=root,
            checkout=checkout,
            refusal=f"{dot_git} is a symlink, which names wherever it points",
        )
    if (common := own_common(checkout)) is not None:
        return RootAnchor(root=root, checkout=checkout, common=common)
    return RootAnchor(
        root=root,
        checkout=checkout,
        refusal=(
            f"{checkout} is a linked worktree outside any tree/ directory, so "
            "its shared directory is known only through the pointer under test"
        ),
    )


def anchored(root: Path) -> RootAnchor:
    """Where host git run at ``root`` finds its shared directory, un-redirected.

    Inside a repository's `tree/` when any ancestor is a `tree/` held by a
    repository -- the nearest such, since a worktree can sit deeper than
    `tree/<name>`: a resolver run cuts its workers under
    `tree/<name>-resolve-<id>/`. The registry's and the cache's paths, the
    launch root, and a worker's lease are all given by the host, so their
    ancestors are too; what the container can write is below them, and that
    is what the anchor checks rather than trusts. Anywhere else the root is
    judged by the shape it has.
    """
    return next(
        (
            in_tree(root, tree, common)
            for tree in root.parents
            if tree.name == "tree" and (common := own_common(tree.parent)) is not None
        ),
        None,
    ) or outside_tree(root)


def root_refusal(root: Path) -> str:
    """Why host git must not run at ``root``, or empty where it may.

    Unanchorable is a refusal of its own rather than a skip: a root whose
    shared directory can only be read through its pointer is exactly the root
    whose pointer cannot be checked. A root in no repository has nothing git
    could be pointed at through it, and passes.
    """
    anchor = anchored(root)
    if anchor.refusal:
        return f"Refusing host git at {root}: {anchor.refusal}."
    if anchor.common is None:
        return ""
    checkouts = [anchor.checkout] if anchor.linked and anchor.checkout else []
    return refusal(pointer_drift(anchor.common, checkouts))


def fleet_refusal(roots: Sequence[Path]) -> str:
    """Every root of a launch host git must not run in, said together.

    Together because a launch refused over its first bad root and relaunched
    would meet the second only then; each line names its own root.
    """
    return "\n".join(message for root in roots if (message := root_refusal(root)))
