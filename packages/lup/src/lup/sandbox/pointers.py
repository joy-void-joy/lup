"""Whether a linked worktree still points where its repository put it.

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
on the host, before host git reads through it.

What vouches for a repository is where it is, never what a pointer says: a
plain checkout's `.git` directory, a repository found by walking up from a
checkout, one found from where the operator stands, or one lup recorded at a
host-side step before any container ran (:mod:`lup.sandbox.known`). A
worktree is then discovered from its repository -- an entry whose `commondir`
leads back to the repository and whose `gitdir` names the checkout, whose
`.git` names the entry back -- rather than trusted for where it sits, so no
layout is assumed: `tree/`, a bare clone, worktrees inside a clone and `git
worktree add ../x` beside one are all the same case. Git itself follows the
pointer to find the repository whose config it reads, and the check follows it
once too, only to ask whether that repository is one already vouched for. The
pointer escape collapses into the config escape, which the shared `config`
and `hooks/` are guarded against: a worktree that leads git to a trusted
repository reads a trusted config.

Only a real mismatch refuses -- a pointer naming somewhere its repository does
not list back, a repository listing a checkout whose pointer leads elsewhere.
A repository nothing vouches for is a candidate the caller records on first
sight or reports, never refused for its shape. What is absent is left
unjudged -- a worktree whose directory has gone, an entry `git worktree add`
has not finished writing -- because git opens neither and reads no config
through it. What this does not answer: a `git` the operator runs by hand,
outside every lup path that consults it.
"""

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from pydantic import BaseModel, Field


class PointerDrift(BaseModel, frozen=True):
    """One worktree pointer that no longer names where the repository put it."""

    worktree: Path
    pointer: Path
    names: str
    expected: str


def resolved_against(entry: Path, contents: str) -> Path:
    """A pointer file's value as an absolute path, from where it was written.

    `commondir` is written relative to the administrative entry (`../..`), while
    `gitdir` is written absolute unless `worktree.useRelativePaths` asked
    otherwise; resolving each against where it was written answers both
    without asking which it was.
    """
    named = Path(contents.strip())
    return named if named.is_absolute() else entry / named


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


def holds_git(path: Path) -> bool:
    """Whether a directory holds a `.git` of any kind, even a dangling symlink."""
    return (path / ".git").exists() or (path / ".git").is_symlink()


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
    """How a checkout said to belong to ``common`` no longer leads into it.

    Read from the checkout's side, the order host git follows: the `.git`
    pointer names an entry of ``common``, that entry names this checkout back,
    and its `commondir` names ``common``. Asked of the checkout itself rather
    than found through the entries, because an entry's `gitdir` back-pointer
    is as writable as the rest -- rewritten, it hides its worktree from a scan
    that starts there. A `.git` that exists but is no pointer is the pointer
    swapped for a gitdir of its own; no `.git` at all has nothing to redirect.
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
    back_file = target / "gitdir"
    back = (
        resolved_against(target, back_file.read_text()) if back_file.is_file() else None
    )
    if back is None or back.parent.resolve() != checkout.resolve():
        yield PointerDrift(
            worktree=checkout,
            pointer=back_file,
            names=str(back) if back is not None else "nothing",
            expected=str(dot_git),
        )
    yield from entry_drift(target, common, checkout)


def once(drifts: Iterable[PointerDrift]) -> list[PointerDrift]:
    """Each redirected pointer file reported once, in the order first seen."""
    return list({drift.pointer: drift for drift in drifts}.values())


def pointer_drift(common: Path, checkouts: Sequence[Path] = ()) -> list[PointerDrift]:
    """Every pointer of this repository that no longer leads to ``common``.

    ``common`` is a trusted shared directory -- the caller's, never re-read
    through a pointer under test. Three readings, one per direction a pointer
    can be forged in. The shared directory holds no `commondir` of its own,
    since git run there would follow one. Each administrative entry leads back
    to ``common``, and the `.git` its `gitdir` names still points at the entry
    -- a `.git` that has become a directory, or anything but that pointer, is
    one git reads instead. And each of ``checkouts``, said to belong here, is
    followed from its own `.git`, so rewriting an entry's back-pointer does
    not hide the worktree it described.

    A value that resolves elsewhere is a redirection, reported once per
    pointer file with what it names against what the repository put there.
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

    return once(drifted())


def refusal(drifts: Sequence[PointerDrift]) -> str:
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
        "Worktree pointers were redirected out of their repository, so host git "
        "in these worktrees would read a config the container chose:\n"
        + "\n".join(lines)
    )


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


def discovered(root: Path) -> Path | None:
    """Where git's discovery from ``root`` stops: the checkout it would use.

    The first directory holding a `.git`, or being a repository itself --
    the two things git looks for at each level on its way up.
    """
    return next(
        (
            candidate
            for candidate in (root, *root.parents)
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


def found_by_path(checkout: Path) -> list[Path]:
    """Every repository the checkout's own path names, without reading a pointer.

    Walking up from the checkout, each directory that is a repository by what
    it holds. That finds a plain checkout's repository, the bare clone holding
    `tree/`, a clone with worktrees inside it, and a resolver worker's
    repository two levels up. A repository sitting inside another's shared
    directory is not taken: git keeps nothing there but its own entries, and a
    writable shared directory is where a container would build one.
    """
    found = [
        common
        for directory in (checkout, *checkout.parents)
        if (common := own_common(directory)) is not None
    ]
    return [
        common
        for common in found
        if not any(
            other != common and common.resolve().is_relative_to(other.resolve())
            for other in found
        )
    ]


def vouched_from(operator: Path) -> list[Path]:
    """The repositories found by path from where the operator stands."""
    checkout = discovered(operator)
    return found_by_path(checkout) if checkout is not None else []


def listed_worktrees(repository: Path) -> list[Path]:
    """Every checkout ``repository`` lists as one of its linked worktrees."""
    entries = repository / "worktrees"
    return [
        resolved_against(entry, (entry / "gitdir").read_text()).parent
        for entry in (sorted(entries.iterdir()) if entries.is_dir() else [])
        if (entry / "gitdir").is_file()
    ]


def lists(repository: Path, checkout: Path) -> bool:
    """Whether ``repository`` lists ``checkout`` as one of its linked worktrees."""
    wanted = checkout.resolve()
    return any(listed.resolve() == wanted for listed in listed_worktrees(repository))


class Landing(BaseModel, frozen=True):
    """Where git lands from a checkout's `.git`, followed once as git follows it."""

    repository: Path | None = Field(
        default=None, description="The repository whose config git reads there"
    )
    entry: Path | None = Field(
        default=None, description="The worktree entry the pointer names, if one"
    )


def landing(checkout: Path) -> Landing:
    """Where git lands from a checkout whose `.git` is not a directory of its own.

    A worktree entry's `commondir` names the repository. A pointer naming a
    repository directory outright -- a submodule, a separate git directory --
    lands there, and so does a `.git` symlinked to a directory. Anything else
    git refuses to open, and reads no config from.
    """
    dot_git = checkout / ".git"
    if dot_git.is_symlink() and dot_git.is_dir():
        return Landing(repository=dot_git.resolve())
    target = gitdir_target(dot_git)
    if target is None or not target.is_dir():
        return Landing()
    commondir = target / "commondir"
    if commondir.is_file():
        repository = resolved_against(target, commondir.read_text())
        if not repository.is_dir():
            return Landing()
        return Landing(repository=repository, entry=target)
    return Landing(repository=target) if is_repository_directory(target) else Landing()


class Verdict(BaseModel, frozen=True):
    """What host git at one root would read, against what vouches for it."""

    root: Path
    checkout: Path | None = Field(
        default=None, description="Where git's discovery from the root stops"
    )
    repository: Path | None = Field(
        default=None, description="The vouched-for repository git reads there"
    )
    candidate: Path | None = Field(
        default=None, description="A repository git would read that nothing vouches for"
    )
    drifts: list[PointerDrift] = []


def verdict(root: Path, trusted: Sequence[Path]) -> Verdict:
    """Judge host git at ``root`` against the repositories that vouch for themselves.

    ``trusted`` are repositories vouched for by where they are -- recorded by
    lup at a host-side step, or found by path from where the operator stands
    -- and the root's own path adds the ones it names. The checkout git would
    use is then judged, never by its shape. A repository standing where it is
    is trusted, unless a trusted repository lists that checkout as a linked
    worktree, which makes its `.git` a swapped pointer. A linked worktree is
    judged by the repository its pointer leads git to: trusted, it is checked
    against that repository and against every one that lists it; untrusted but
    listed by a trusted one, it is a mismatch; untrusted and listed by none,
    it comes back as a candidate for the caller to record or report.
    """
    checkout = discovered(root)
    if checkout is None:
        return Verdict(root=root)
    repositories = [*found_by_path(checkout), *trusted]
    listed = once(
        drift
        for repository in repositories
        if lists(repository, checkout)
        for drift in pointer_drift(repository, [checkout])
    )
    own = own_common(checkout)
    if own is not None:
        drifts = once([*pointer_drift(own), *listed])
        return Verdict(root=root, checkout=checkout, repository=own, drifts=drifts)
    lands = landing(checkout)
    if lands.repository is None:
        return Verdict(root=root, checkout=checkout, drifts=listed)
    followed = [checkout] if lands.entry is not None else []
    drifts = once([*pointer_drift(lands.repository, followed), *listed])
    reached = lands.repository.resolve()
    vouching = next(
        (repository for repository in repositories if repository.resolve() == reached),
        None,
    )
    if vouching is not None:
        return Verdict(root=root, checkout=checkout, repository=vouching, drifts=drifts)
    if listed:
        return Verdict(root=root, checkout=checkout, drifts=listed)
    return Verdict(root=root, checkout=checkout, candidate=reached, drifts=drifts)


def unvouchable(candidate: Path, checkout: Path, trusted: Sequence[Path]) -> str:
    """Why a repository nothing vouches for cannot be trusted on first sight.

    Empty where it may be. A repository sitting inside the checkout it would
    serve, inside a trusted repository's shared directory or the working tree
    a `.git` directory belongs to, or inside a checkout a trusted repository
    lists, sits where a contained session writes -- which is where one would
    be built to be trusted.
    """
    place = candidate.resolve()
    areas = [
        checkout,
        *trusted,
        *(repository.parent for repository in trusted if repository.name == ".git"),
        *(
            worktree
            for repository in trusted
            for worktree in listed_worktrees(repository)
        ),
    ]
    inside = next(
        (area for area in areas if place.is_relative_to(area.resolve())), None
    )
    if inside is None:
        return ""
    return f"it lies inside {inside}, where a contained session could have built it"
