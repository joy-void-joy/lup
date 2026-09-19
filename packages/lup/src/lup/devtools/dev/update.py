"""Every carrier moved to one upstream commit, by one command.

Three mechanisms carry an upstream scaffold into a project: a pin for the
library, a regeneration for the native trees, a hand-port for the copied
half. Moved separately, they come apart — the pin lands a library whose
callers are still last month's, and nothing says so until something breaks.
So the update is one command, and what it moves them all to is one commit.

The commit is read back rather than chosen twice. `uv lock` resolves the pin
and writes the commit it got; that commit is what the scaffold is compiled at
and what the migrations are read between, so the three carriers agree by
construction instead of by being run in the right order on the same afternoon.

Where they do not agree — an update interrupted by a conflict, a lock moved by
hand, a scaffold branch nobody merged — :class:`CarrierDrift` says so in one
line, and the same line is what the gate and the prompt-time fold report.
"""

from collections.abc import Callable
from pathlib import Path

import typer
from pydantic import BaseModel

import lup.devtools.dev.library as library
import lup.devtools.dev.migrations as migrations
import lup.devtools.dev.scaffold as scaffold
from lup.devtools.sync import ensure_local, find_project
from lup.devtools.utils import short_sha, uv


class CarrierDrift(BaseModel, frozen=True):
    """Where each carrier stands, for a reader deciding whether to update.

    Three facts, none of them stored: the commit the lock resolved, the commit
    the last merged scaffold was compiled at, and how many migrations lie
    between them. A project whose carriers agree is the quiet case and says
    nothing at all.
    """

    library: str
    """The commit the library pin resolved, empty where nothing pins a commit."""

    scaffold: str
    """The commit the copied half was last merged at, empty before adoption."""

    pending: int = 0
    """Declared migrations between the two, which no merge applies on its own."""

    def settled(self) -> bool:
        """Whether every carrier stands at one commit with nothing owed.

        A carrier that says nothing settles nothing either way: a project
        resolving a released library pins no commit, and one that has not
        adopted a scaffold branch has merged none — neither is drift, and
        reporting them as drift would leave a row nobody can act on.
        """
        agreed = not self.library or not self.scaffold or self.library == self.scaffold
        return agreed and not self.pending

    def spelled(self) -> str:
        """The one line a gate row and a prompt-time fold both report."""
        return (
            f"library at {short_sha(self.library) or 'no pinned commit'}, "
            f"scaffold merged at {short_sha(self.scaffold) or 'nothing yet'}, "
            f"{self.pending} migration(s) pending"
        )


def drift(
    root: Path,
    source: scaffold.ScaffoldSource,
    distribution: str = library.DISTRIBUTION,
) -> CarrierDrift:
    """Read where this project's carriers stand, from git and the lock alone."""
    return CarrierDrift(
        library=scaffold.pinned_commit(root, distribution),
        scaffold=scaffold.merged_at(root, source.branch),
    )


def upstream_checkout(project: str, report: Callable[[str], None]) -> Path:
    """The local clone of upstream, materialized and fetched if need be.

    The registration is the one `sync` already keeps: a project that tracks
    its upstream for review is the same project that compiles its scaffold
    from it, and a second way of naming the same repository is a second thing
    to get wrong.
    """
    return ensure_local(find_project(project), report).checkout


def resolved_pin(
    root: Path, distribution: str, commit: str, report: Callable[[str], None]
) -> str:
    """Move the pin, and hand back the commit the lock resolved it to.

    A named commit is pinned as a revision; an unnamed one re-resolves whatever
    ref the project already declared, which is what following a branch means.
    Either way the answer is read out of `uv.lock` rather than assumed, because
    the lock is what the environment is built from and a commit this decided
    for itself would be a fourth carrier to keep in step.
    """
    if commit:
        source = library.read_git_source(root)
        library.set_mode(
            root,
            library.LibraryMode.GIT,
            git=library.GitSource(
                url=source.url if source else library.REPOSITORY_URL,
                ref_kind="rev",
                ref=commit,
            ),
        )
    report(f"Resolving {distribution}...")
    uv("lock", "--upgrade-package", distribution, _cwd=str(root))
    return scaffold.pinned_commit(root, distribution)


def owed_since(
    merged: str, repository: Path, report: Callable[[str], None]
) -> list[str]:
    """What this update asks of the project beyond what the merge already did.

    Read from the library that just landed, because that is where a migration
    is declared: whatever it holds that the commit this project came from did
    not is what somebody has to act on. Ancestry is asked of upstream's own
    clone, the only checkout that has both commits.

    A project with nothing merged yet is told nothing: every declaration would
    be pending for it, which is true of a project that has taken none of them
    and useless to read.
    """
    if not merged:
        return []
    pending = migrations.unapplied(migrations.DECLARED, merged, repository)
    if not pending:
        return []
    return [f"{len(pending)} migration(s) pending:", *migrations.rendered(pending)]


def regenerated(root: Path, report: Callable[[str], None]) -> None:
    """Regenerate every native tree, under the library the update just installed.

    In a subprocess rather than in this process, and that is not a style
    choice: a native tree is compiled from the library's own declarations, and
    the library imported here is the one that was installed when the command
    started — the very version this update exists to replace. Regenerating
    in-process would write the old library's trees and report them as current.
    """
    report("Regenerating the native trees...")
    uv("run", "lup-devtools", "harness", "generate", "all", _cwd=str(root))


def updated(
    root: Path,
    source: scaffold.ScaffoldSource,
    package: str,
    commit: str,
    distribution: str,
    report: Callable[[str], None],
) -> scaffold.MergeOutcome | None:
    """Move every carrier to one upstream commit, and say what it cost.

    Nothing is answered before the pin moves, because the pin is what decides
    the commit. Nothing is regenerated after a conflicted merge either: the
    trees are compiled from declarations the merge has not finished writing,
    and a regeneration over half a merge produces an artifact matching neither
    side.
    """
    repository = upstream_checkout(source.project, report)
    resolved = resolved_pin(root, distribution, commit, report)
    if not resolved:
        report(
            f"{distribution} resolves to no commit, so the copied half has "
            "nothing to be compiled at. Pin the library at a repository "
            f"(`dev library git --branch <branch>`) to update both halves."
        )
        return None
    report(f"Library at {short_sha(resolved)}; syncing the environment...")
    uv("sync", _cwd=str(root))
    already = scaffold.merged_at(root, source.branch)
    if already == resolved:
        report(f"The copied half is already merged at {short_sha(resolved)}.")
        regenerated(root, report)
        return None
    scaffold.advanced(root, repository, source, package, resolved)
    outcome = scaffold.merged(root, source)
    report(f"Copied half: {outcome.spelled()}.")
    for line in owed_since(already, repository, report):
        report(line)
    for path in outcome.conflicted:
        report(f"  conflicted  {path}")
    if not outcome.complete():
        report(
            "Resolve those, commit the merge, and run `dev update` again: the "
            "native trees are compiled from declarations the merge has not "
            "finished writing."
        )
        return outcome
    regenerated(root, report)
    return outcome


def adopted(
    root: Path,
    source: scaffold.ScaffoldSource,
    package: str,
    base: str,
    report: Callable[[str], None],
) -> str:
    """Root this project's scaffold branch, once, at the commit it was stamped from.

    Refused where the branch already stands, because rooting it twice is how a
    project ends up with two unrelated histories of the same tree and a merge
    base older than either.
    """
    standing = scaffold.branch_head(root, source.branch)
    if standing:
        raise typer.BadParameter(
            f"{source.branch} already stands at {short_sha(standing)}, compiled "
            f"at {short_sha(scaffold.compiled_at(root, standing))}. Adoption "
            "happens once; `dev update` is every time after it."
        )
    repository = upstream_checkout(source.project, report)
    rooted = scaffold.adopt(root, repository, source, package, base)
    report(
        f"{source.branch} rooted at {short_sha(base)} ({short_sha(rooted)}), "
        f"recorded as this project's merge base for every later update."
    )
    return rooted
