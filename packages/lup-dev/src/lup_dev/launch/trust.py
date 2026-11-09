"""Trust on launch: the code the host runs for a repository, approved before it runs.

`docs/trust.md`. A repository's host zone is what the host runs
for it, read at the running branch's tip, so what's approved is what the judge
and the host service run, never a branch's own copy (`Zone`), with the person's own
layer beside it:
- its declaration, `lup_project.py` or the package `lup_project/`, and every file
  importing it runs on the host: each of the project's own modules it imports,
  with the `__init__.py` of each package holding one, and in turn what they
  import; and each conditions module its modules name, with its packages. They're
  found by reading the declaration with `ast` (`declared`), following its imports
  to the files they resolve to, so no code of the project runs before the
  operator is asked;
- the `lup-dev` the host runs (`Tool`): where the repository's lock resolves it
  from the repository's own workspace, as lup's does, that source
  (`WorkspaceTool`: uv's files, the project file and modules of each workspace
  package `lup-dev` needs, and the engine's source); otherwise the release the lock
  pins, with every package it needs at its locked version (`ReleaseTool`);
- the person's own layer of the declaration, `lup_project.local.py` in the
  repository's main worktree (`person_layer`), which git ignores, so it's in the zone by its
  content (`Zone.local`), and what it imports of the commit with the rest
  (`docs/trust.md`, *Trusted by its content*). A room writes the worktree, so
  an edit made there runs nowhere until approved: the judge and a launch read
  the copy kept with the approval. Where it changed, its diff is in the summary
  itself (`compared`);
- the person's profiles file, `~/.config/lup/profiles.py`, which no repository
  holds, by its content too (`Zone.profiles`): a launch runs the copy approved
  with the repository's zone, so an edit asks again in each repository, at its
  next launch. It runs apart from the declaration, importing nothing of the
  commit, and the judge doesn't read it: the repository's roles and rules
  aren't its own.

Which branch that is comes from the declaration already approved, since reading
the tip's would run the project's code before the operator is asked, and `dev`
before the first approval: an answer's yes reads the branches the declaration just
approved names, and keeps them with the approval (`Trust.answered`,
`Approval.branches`), so a change to them takes effect once it's approved, and its
diff is in what's approved.

The zone's fingerprint is kept with the commit the operator approved, per
repository, in lup's state (`Approval`). `trusted`, which a launch calls before
anything else, and `lup-dev trust` compare the tip's zone with it (`Trust.check`).
Where it changed, or nothing was approved, the operator reads a summary first
(`Change.summary`): what's approved and why it runs on the host, the commit
approved before and the tip, and git's own count of each file changed since
(`git diff --stat --compact-summary`), coloured, as git prints it; each file
changed is kept whole with the judge's reading of it, the change judged as a move
of `HEAD` is, by the declaration approved last, never the tip's own, which
importing would run (`Trust.read`), for the dashboard's review. That reading
comes in two passes, so a type check doesn't hold the question up: the first,
before it's asked, from each file's parse alone (what it asks by its path, its
content, its public names and its directives); the second, the whole judgement,
types and lup's rules included, read by the host service once the approval is
in the inbox (`Trust.typed`). A first approval trusts the zone as it is, its
files read by their roles alone, asking nothing (`trusted_whole`). Then they're
asked whether to show the whole diff, no by default, a yes showing it through the
terminal's pager; then whether to approve, no by default (`Asker`). The question
is an item in the operator's inbox from the start (`Approvals`, the host service
started where none runs), which the launching terminal answers as `lup-dev inbox
answer` at any other does, whichever comes first; the terminal stops asking where
another answered first (`Approving`, `Elsewhere`). Launches asking about the same
zone at once wait on one approval. The answer:
- yes: the tip's copy is installed as the repository's own (`Toolchain`), in a
  directory of its own under `Layout.judge`, never over the copy a process
  runs, and switched to in one rename once it's whole (`lup_dev/copies.py`;
  for the workspace's source, the engine built first through the declaration's
  own step and runner, as the gate builds it): the host service starts the
  repository's process from it at its next request, and the approval is
  recorded. On
  lup's own repository, whose copy is lup's own command, the dashboard is
  installed with it, and it's what the person's `lup-dev` and the host service
  run too: it's tried first, and the service moved to it with the way back
  where it doesn't answer (`lup_dev/switching.py`), a copy that doesn't answer
  leaving the approval where it was (`Unanswered`);
- no: the copy approved before stays, and the launch says the tip isn't the code
  judging its session; with nothing approved yet, nothing launches.

A repository's copy approved but missing from its place, removed or never
installed there, is installed from the commit approved, asking nothing.

A push from a room that moves the running branch puts the approval of the
zone at its tip in the inbox too, asking nothing at any terminal (`proposed`),
so the operator isn't left to notice that the code the host runs changed. The
terminal answering it with `lup-dev inbox answer` then acts on a yes as a
launch waiting on it would (`settle`), once between them, unless the branch
moved again since it was asked, which `lup-dev trust` asks about anew.
"""

import ast
import hashlib
import os
import select
import tempfile
import termios
import time
import tomllib
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from importlib.machinery import SOURCE_SUFFIXES, FileFinder, SourceFileLoader
from importlib.util import resolve_name
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, override

import typer
from filelock import FileLock
from pydantic import Field, ValidationError
from rich.console import Console
from rich.text import Text

from lup.programs import run
from lup.types import Model, MutableModel
from lup_dev.approval import (
    Approval,
    ReleaseTool,
    Tool,
    WorkspaceTool,
    approved,
    approved_branches,
)
from lup_dev.clock import Clock, SystemClock
from lup_dev.codescan import conditions
from lup_dev.codescan.contract import Checker, Parser
from lup_dev.codescan.engine import EngineChecker, EngineParser
from lup_dev.codescan.ruff import Linter, Ruff
from lup_dev.copies import Copies
from lup_dev.copies import Kept as KeptCopy
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import (
    Pyproject,
    import_roots,
    load,
    person_layer,
    read_by_import,
)
from lup_dev.declaration.project import Project
from lup_dev.declaration.requirements import Machine, Tools, check
from lup_dev.declaration.resolve import Declaration, resolve
from lup_dev.errors import LupDevError
from lup_dev.gate import invoked
from lup_dev.git import Git, Tracked
from lup_dev.host.client import HostClient, Outstanding
from lup_dev.host.protocol import Branches, HostError
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AskApproval,
    AwaitApproval,
    Settled,
    Shown,
)
from lup_dev.inbox.store import (
    Binary,
    ChangedFile,
    Content,
    Decided,
    Item,
    Reading,
    Superseded,
    cited,
)
from lup_dev.layout import CheckoutLayout, CopyLayout, JudgeLayout, Layout
from lup_dev.policy.checkpoint import Judging, Worktree
from lup_dev.policy.judge import Change as FileChange
from lup_dev.policy.judge import Judge
from lup_dev.policy.roles import Roles
from lup_dev.policy.store import Store
from lup_dev.settings import LupDevSettings
from lup_dev.stored import write_model
from lup_dev.switching import (
    Programs,
    Serving,
    Switched,
    Switcher,
    Switching,
    host_starter,
)
from lup_dev.trial import running_tip

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from contextlib import AbstractContextManager

    from lup_dev.catalog.gate import Step
    from lup_dev.declaration.resolve import Resolved
    from lup_ledger.parties import Conversation


class TrustError(LupDevError):
    """The host zone can't be read, or no approved copy is there for the host to run."""


class SupersededError(TrustError):
    """An approval a later one of the same repository replaced, the running branch's tip having moved: the later one is asked."""


class LockSource(Model):
    """Where `uv.lock` says a package comes from: one of these is set."""

    registry: str | None = None
    """The index a release is resolved from."""
    editable: str | None = None
    """The directory of a workspace package installed editable, from the lock's."""
    virtual: str | None = None
    """The directory of a workspace package that isn't built, from the lock's."""
    directory: str | None = None
    path: str | None = None
    git: str | None = None
    url: str | None = None

    def workspace(self) -> Path | None:
        """Return a workspace package's directory, from the lock's; none for any other."""
        where = self.editable or self.virtual
        return Path(where) if where is not None else None

    def said(self) -> str:
        """Say where the package comes from, as the lock spells it."""
        given = self.model_dump(exclude_none=True)
        return ", ".join(f"{kind} {where}" for kind, where in given.items()) or (
            "nowhere the lock says"
        )


class LockDependency(Model):
    """One package another needs, as `uv.lock` lists it."""

    name: str
    version: str | None = None
    """Which of the package's versions, where the lock holds several."""
    extra: list[str] = []
    """The package's extras it's needed with."""


class LockedPackage(Model):
    """One package `uv.lock` pins: where it comes from, and what it needs."""

    name: str
    version: str | None = None
    source: LockSource
    dependencies: list[LockDependency] = []
    optional_dependencies: dict[str, list[LockDependency]] = Field(
        default={}, alias="optional-dependencies"
    )
    """What each of its extras needs besides, by the extra's name."""


class LockManifest(Model):
    """`[manifest]`: the workspace the lock was resolved for."""

    members: list[str] = []
    """The workspace's packages, by name."""


class Lock(Model):
    """The parts of `uv.lock` trust reads: its packages, and its workspace's members."""

    package: list[LockedPackage] = []
    manifest: LockManifest = LockManifest()

    @classmethod
    def parse(cls, text: str) -> Lock:
        """Read `uv.lock`'s text."""
        return cls.model_validate(tomllib.loads(text))

    def matching(self, wanted: LockDependency) -> list[LockedPackage]:
        """Return the packages a dependency names: one, unless the lock forks."""
        return [
            package
            for package in self.package
            if package.name == wanted.name
            and (wanted.version is None or package.version == wanted.version)
        ]

    def wants(self, wanted: LockDependency) -> list[LockDependency]:
        """List what the packages a dependency names need, its extras' included."""
        return [
            each
            for package in self.matching(wanted)
            for each in [
                *package.dependencies,
                *(
                    needed
                    for extra in wanted.extra
                    for needed in package.optional_dependencies.get(extra, [])
                ),
            ]
        ]

    def needed(self, name: str) -> list[LockedPackage]:
        """Return the package `name` and every package it needs, in the order met.

        An extra's needs are followed where a dependency asks for it. Markers
        aren't read, so a package needed on one platform only is among them.
        """

        def walk(
            frontier: list[LockDependency], walked: list[LockDependency]
        ) -> Iterator[LockDependency]:
            fresh = [
                each
                for at, each in enumerate(frontier)
                if each not in walked and each not in frontier[:at]
            ]
            if not fresh:
                return
            yield from fresh
            further = [each for wanted in fresh for each in self.wants(wanted)]
            yield from walk(further, [*walked, *fresh])

        reached = walk([LockDependency(name=name)], [])
        packages = [package for wanted in reached for package in self.matching(wanted)]
        return [
            package
            for at, package in enumerate(packages)
            if package not in packages[:at]
        ]

    def tool(self, name: str, beside: list[str] | None = None) -> Tool:
        """Return the package `name` the host runs, as the lock resolves it.

        Where it's a member of the lock's workspace, the workspace's own source,
        with each of the members `beside` names that the workspace has, installed
        beside it in the person's own copy; where it comes from an index, that
        release. Raise `TrustError` where the lock doesn't pin it, pins it twice,
        or resolves it from anywhere else.
        """
        pinned = [package for package in self.package if package.name == name]
        if not pinned:
            message = (
                f"`uv.lock` doesn't pin `{name}`, so which the host runs isn't known: "
                "the project depends on it, for development, to declare itself"
            )
            raise TrustError(message)
        if len(pinned) > 1:
            versions = ", ".join(str(package.version) for package in pinned)
            message = (
                f"`uv.lock` pins `{name}` at {versions}, so which the host runs "
                "isn't one"
            )
            raise TrustError(message)
        [package] = pinned
        needed = self.needed(name)
        home = package.source.workspace()
        if home is not None and name in self.manifest.members:
            members = [
                each.source.workspace()
                for each in needed
                if each.name in self.manifest.members
            ]
            besides = [
                each.source.workspace()
                for each in self.package
                if each.name in (beside or []) and each.name in self.manifest.members
            ]
            return WorkspaceTool(
                name=name,
                package=home,
                members=[each for each in members if each is not None],
                beside=[each for each in besides if each is not None],
            )
        if package.source.registry is not None and package.version is not None:
            return ReleaseTool(
                name=name,
                version=package.version,
                registry=package.source.registry,
                pins=pinned_versions(needed, name),
            )
        message = (
            f"`uv.lock` resolves `{name}` from {package.source.said()}: the host runs "
            "a release from an index, or the repository's own workspace source, and "
            "lup approves no other"
        )
        raise TrustError(message)


def pinned_versions(packages: list[LockedPackage], name: str) -> dict[str, str]:
    """Return the version of each of `packages` but `name`, by name.

    Raise `TrustError` where one is pinned at two versions, since the copy can't
    be held to both.
    """
    others = [
        package
        for package in packages
        if package.name != name and package.version is not None
    ]
    clashes = [
        f"`{one.name}` at {one.version} and {other.version}"
        for at, one in enumerate(others)
        for other in others[at + 1 :]
        if one.name == other.name
    ]
    if clashes:
        message = (
            f"`uv.lock` pins what `{name}` needs at two versions, "
            f"{'; '.join(clashes)}, so its copy can't be held to one"
        )
        raise TrustError(message)
    return {
        package.name: package.version
        for package in others
        if package.version is not None
    }


class Zone(Model):
    """A repository's host zone at one commit: what the host runs for it."""

    commit: str
    paths: list[Path]
    """Each of its paths in the repository, a file or a directory, from the root:
    what its diff and its fingerprint read."""
    tool: Tool
    local: str | None = None
    """The person's own layer, `lup_project.local.py` in the worktree trust runs
    from, whole: git holds none of it, so it's in the zone by its content; none
    where there's none."""
    profiles: str | None = None
    """The person's profiles file, `~/.config/lup/profiles.py`, whole: no
    repository holds it, so it's in the zone by its content; none where there's
    none."""
    unread: list[str] = []
    """What of the declaration couldn't be followed, each said, so a file it runs
    may be missing from `paths`; empty where all of it was."""


class Named(Model):
    """The files a declaration runs on the host and the conditions modules it names, read without running any."""

    paths: list[Path] = []
    """From the commit's root, in the order they were found."""
    unread: list[str] = []
    """What couldn't be followed, each said: a file that doesn't parse, an import
    leaving its package, a conditions module that isn't there."""


class Standing(Model):
    """The tip's host zone, beside the one approved last."""

    zone: Zone
    fingerprint: str
    approval: Approval | None

    def approved(self) -> bool:
        """Say whether the tip's zone is the one approved."""
        return (
            self.approval is not None and self.approval.fingerprint == self.fingerprint
        )


class Diffed(Model):
    """git's diff of some of the zone's paths between two trees, and its count of each file."""

    stat: str = ""
    """git's count of each file and of the whole (`git diff --stat
    --compact-summary`), coloured, as git prints it; empty where none changed."""
    diff: str = ""
    """The diff, coloured for the terminal."""


WHY = (
    "The host runs this repository's declaration and this `lup-dev` outside every "
    "room: they judge its sessions' writes, and carry out their pushes and GitHub "
    "actions with your credentials."
)
"""What's approved, and why it runs on the host: the summary's first words."""

WHOLE = "Show the whole diff?"
"""The question before the diff, which only a yes shows."""


class Change(Model):
    """What the operator reads before approving the tip's host zone."""

    commit: str
    approved: str | None
    """The commit approved last; none the first time."""
    since: str | None
    """Where the diff of the zone's paths starts: the commit approved last, where
    the repository still holds it; none shows the zone whole."""
    changed: Diffed
    """The paths approved before, since `since`; every path, whole, where it's none."""
    joined: Diffed
    """The paths the zone holds that the approval didn't, whole."""
    local: Diffed = Diffed()
    """The person's own layer, from the copy approved before to the worktree's;
    empty where it's the same."""
    profiles: Diffed = Diffed()
    """The person's profiles file, from the copy approved before to the one in
    their configuration; empty where it's the same."""
    files: list[ChangedFile]
    """Each file the diff shows, whole on each side, in its order, with the
    judge's reading of it: what the dashboard shows (`docs/dashboard.md`, *The
    review*)."""
    typing: bool = False
    """Whether that reading is of each file's parse alone, for the host service
    to read the change's types once it's asked (`Trust.typed`); not for a first
    approval's, read by roles, or where the judge couldn't read the change."""
    tool: list[str]
    """How the `lup-dev` release changed, line by line; none for the workspace's
    own source, whose change is in the diff."""
    unread: list[str] = []
    """What of the declaration couldn't be followed, so the zone may miss a file it runs."""
    unjudged: str = ""
    """Why the judge couldn't read the zone's change, so its files carry no
    reading; empty where it read them."""

    def before(self) -> str:
        """Say which commit was approved before, and whether the zone is shown since it or whole."""
        if self.approved is None:
            return (
                "Approved before: nothing. A first approval trusts the zone as it is, "
                "as you chose it by pulling: what changes from here comes for review."
            )
        if self.since is None:
            return (
                f"Approved before: {self.approved}, which the repository no longer "
                "holds, so the zone is shown whole."
            )
        return f"Approved before: {self.approved}."

    def summary(self) -> str:
        """Return what the operator reads first: what's approved and why, the commits, and git's count of each file.

        The count is git's own, as git prints it: the paths approved before,
        then those joining the zone, shown whole. The person's own layer and
        their profiles, which git doesn't hold, are each shown whole where they
        changed: their diff, not a count, since they're short and nothing else
        shows them. A release's change is said
        by its versions, then what of the declaration couldn't be followed, and
        last why the judge couldn't read the change, where it couldn't.
        """
        changed = self.changed.stat.splitlines() or ["No file of the zone changed."]
        joined = (
            ["Joining the zone, shown whole:", *self.joined.stat.splitlines()]
            if self.joined.stat
            else []
        )
        local = (
            [
                "Your own layer, which git doesn't hold, changed since approved:",
                *self.local.diff.splitlines(),
            ]
            if self.local.diff
            else []
        )
        profiles = (
            [
                "Your profiles, which no repository holds, changed since approved:",
                *self.profiles.diff.splitlines(),
            ]
            if self.profiles.diff
            else []
        )
        unknown = "Not followed, so the zone may miss a file the declaration runs:"
        unread = (
            [unknown, *(f"  {each}" for each in self.unread)] if self.unread else []
        )
        failed = "The judge couldn't read the zone's change, so the review opens"
        unjudged = [f"{failed} every file: {self.unjudged}"] if self.unjudged else []
        said = [
            WHY,
            "",
            self.before(),
            f"The tip: {self.commit}.",
            "",
            *changed,
            *joined,
            *local,
            *profiles,
            *self.tool,
            *unread,
            *unjudged,
        ]
        return "\n".join(said)

    def diff(self) -> str:
        """Return the whole diff, coloured: the paths approved before, then those joining the zone, then the person's own layer, then their profiles."""
        return (
            self.changed.diff + self.joined.diff + self.local.diff + self.profiles.diff
        )

    def question(self) -> str:
        """Ask whether to approve the zone, and run its `lup-dev` on the host: the first time, whether to trust it as it is."""
        if self.approved is None:
            return (
                f"Trust this repository's host zone as it is at {self.commit}, and "
                "install its `lup-dev` as the one the host runs?"
            )
        return (
            f"Approve the host zone at {self.commit}, and install its `lup-dev` as "
            "the one the host runs?"
        )


def reinstalled(approval: Approval, *, again: bool) -> str:
    """Say, where `again`, that the copy approved was missing and is installed again; nothing otherwise."""
    if not again:
        return ""
    return (
        f" This repository's copy of `lup-dev` from {approval.commit} was missing, "
        "and is installed again."
    )


class BranchesRead(Model):
    """The branches a declaration just approved names, what the approval's answer says of them, and the declaration as judging reads it."""

    branches: Branches
    said: str | None = None
    """What changed of them, or why they couldn't be read; none where they stand
    as they did."""
    declaration: Declaration | None = None
    """What the approval keeps of it (`Approval.declaration`): where it doesn't
    load, what the approval before kept."""


def branches_moved(before: Branches, after: Branches) -> str | None:
    """Say what changed between `before` and `after`; none where nothing did.

    >>> print(branches_moved(Branches(), Branches(running="live")))
    The running branch is now `live`: trust reads it, and `land` lands on it.
    >>> print(branches_moved(Branches(), Branches(integration="trunk", running="trunk")))
    The integration branch is now `trunk`: branches start from it, and pull requests target it. The running branch is now `trunk`: trust reads it, and `land` lands on it.
    >>> branches_moved(Branches(), Branches()) is None
    True
    """
    integrating = (
        f"The integration branch is now `{after.integration}`: branches start from "
        "it, and pull requests target it."
    )
    running = (
        f"The running branch is now `{after.running}`: trust reads it, and `land` "
        "lands on it."
    )
    said = [
        *([integrating] if after.integration != before.integration else []),
        *([running] if after.running != before.running else []),
    ]
    return " ".join(said) or None


class Unchanged(Model):
    """The tip's host zone is the one approved: nothing was asked."""

    commit: str
    approval: Approval
    again: bool = False
    """Whether the repository's copy approved was missing, and installed again."""

    def report(self) -> str:
        """Say that nothing changed, in one line."""
        return (
            f"The host zone at {self.commit} is the one you approved at "
            f"{self.approval.commit}: nothing to review."
            + reinstalled(self.approval, again=self.again)
        )


class Trusted(Model):
    """The operator approved the tip's host zone: its copy is installed, and recorded."""

    approval: Approval
    restarted: bool
    """Whether a host service ran, and was restarted on the copy, which it runs
    from only where the copy is lup's own command: where none ran, it's started."""
    installed: bool = True
    """Whether the copy was installed: not where only the person's own layer
    or their profiles changed, the copy approved before being the commit's
    already."""
    layer: bool = True
    """Whether the person's own layer is among what changed, where nothing was installed."""
    profiles: bool = False
    """Whether the person's profiles are among what changed, where nothing was installed."""
    branches: str | None = None
    """What approving it changed of the branches, or why they couldn't be read
    (`BranchesRead.said`); none where they stand as they did."""

    def report(self) -> str:
        """Say what was installed, where the host service stands, and what became of the branches."""
        said = self.installing()
        return said if self.branches is None else f"{said} {self.branches}"

    def installing(self) -> str:
        """Say what was installed, and where the host service stands."""
        if not self.installed:
            approved = [
                *(
                    [
                        (
                            "your own layer, which judges this repository's "
                            "sessions from their next hook"
                        )
                    ]
                    if self.layer
                    else []
                ),
                *(
                    ["your profiles, which its launches run on from the next"]
                    if self.profiles
                    else []
                ),
            ]
            return (
                f"Approved: {', and '.join(approved)}, beside `lup-dev` from "
                f"{self.approval.commit} as before."
            )
        approved = (
            f"Approved: `lup-dev` from {self.approval.commit} judges this "
            "repository's sessions"
        )
        if not self.approval.tool.lups_own():
            return f"{approved}, from their next hook."
        service = (
            "the host service restarted on it"
            if self.restarted
            else "the host service started on it"
        )
        return f"{approved}, and is the `lup-dev` you run; {service}."


class Kept(Model):
    """The operator declined the tip's host zone: the copy approved before stays."""

    commit: str
    approval: Approval
    again: bool = False
    """Whether the repository's copy approved before was missing, and installed again."""

    def report(self) -> str:
        """Say that the tip isn't the code judging the session, and what is."""
        return (
            "Declined: the tip isn't the code judging this session. The host keeps "
            f"running `lup-dev` from {self.approval.commit}, which you approved; the "
            f"host zone at {self.commit} differs from it."
            + reinstalled(self.approval, again=self.again)
        )


class Unanswered(Model):
    """The operator approved the tip's host zone, but its copy doesn't answer as the host service and the dashboard: what's approved and what runs stay as they were."""

    commit: str
    approval: Approval
    """What stays approved."""
    said: str
    """What came of the switch, why among it (`Stayed.report`, `FellBack.report`)."""

    def report(self) -> str:
        """Say what came of it, and that the tip is asked about again."""
        return (
            f"{self.said} The host zone at {self.commit} stays unapproved, so the "
            "next launch asks about it again."
        )


type Outcome = Unchanged | Trusted | Kept | Unanswered
"""What `Trust.ensure` came to: approved before, approved at this check, declined, or approved with a copy that doesn't answer."""


class Elsewhere(ABC):
    """An approval waiting in the inbox, which another terminal may answer: readable once something may have come of it."""

    @abstractmethod
    def fileno(self) -> int:
        """Return what turns readable once the approval may have been answered elsewhere, which `select` watches."""

    @abstractmethod
    def given(self) -> bool | None:
        """Return the answer given elsewhere, yes or no, without waiting; none while it waits."""


class Given(Model):
    """The operator's answer to an approval, and whether this terminal gave it."""

    approved: bool
    here: bool


class Approvals(ABC):
    """Where an approval waits for the operator: lup's inbox, which any terminal answers."""

    @abstractmethod
    def asked(self, asking: AskApproval) -> int:
        """Put the approval in the inbox, or join the one waiting there about the same zone; return its number."""

    @abstractmethod
    def waited(self, number: int) -> AbstractContextManager[Elsewhere]:
        """Wait on approval `number` while the context is open, for an answer given elsewhere."""

    @abstractmethod
    def answer(self, number: int, *, approved: bool, comment: str = "") -> Given:
        """Answer approval `number` here, with the operator's `comment`; return the answer that holds, which another terminal may have given first."""


class Asker(ABC):
    """Where the operator reads the change and answers: a terminal."""

    @abstractmethod
    def say(self, text: str) -> None:
        """Print `text` for the operator as it is, its colours kept."""

    @abstractmethod
    def show(self, text: str) -> None:
        """Show `text` to the operator, through the terminal's pager."""

    @abstractmethod
    def ask(self, question: str, elsewhere: Elsewhere) -> bool | None:
        """Ask `question`, no by default, until it's answered here or `elsewhere`: whether the operator answered yes here; none where it was answered elsewhere first."""


def line(descriptor: int) -> str | None:
    """Read one line from `descriptor` a byte at a time, so nothing past it leaves the stream `select` watches; none where its input ended before anything of one was read."""
    ended = False

    def read() -> Iterator[bytes]:
        nonlocal ended
        while (byte := os.read(descriptor, 1)) != b"\n":
            if byte == b"":
                ended = True
                return
            yield byte

    said = b"".join(read())
    return None if ended and not said else said.decode(errors="replace")


def yes(said: str) -> bool | None:
    """Read a yes or a no as `typer.confirm` does, no where nothing is said; none where it's neither.

    >>> yes("Y"), yes(""), yes("maybe")
    (True, False, None)
    """
    match said.strip().lower():
        case "y" | "yes":
            return True
        case "n" | "no" | "":
            return False
        case _:
            return None


class Terminal(Model, Asker):
    """The terminal: the summary printed, the diff through its pager, each question no by default, until it's answered elsewhere."""

    stdin: int = 0
    """The descriptor the operator's answers are read from."""

    @override
    def say(self, text: str) -> None:
        typer.echo(text)

    @override
    def show(self, text: str) -> None:
        console = Console()
        with console.pager(styles=True):
            console.print(Text.from_ansi(text), soft_wrap=True)

    @override
    def ask(self, question: str, elsewhere: Elsewhere) -> bool | None:
        """Ask until the operator answers y or n, Enter answering no, while watching for an answer given elsewhere.

        Where one comes first, the question stops, and what was typed of an
        answer is dropped, so it reaches nothing after. Where the input ends,
        as a launch's run by a program with nothing to answer does, nobody
        answers here, rather than its end reading as Enter, a no: the
        question waits for its answer elsewhere alone.
        """
        typer.echo(f"{question} [y/N]: ", nl=False)
        watched: list[int | Elsewhere] = [self.stdin, elsewhere]
        while True:
            readable, _, _ = select.select(watched, [], [])
            if elsewhere in readable and elsewhere.given() is not None:
                typer.echo()
                if os.isatty(self.stdin):
                    termios.tcflush(self.stdin, termios.TCIFLUSH)
                return None
            if self.stdin in readable:
                said = line(self.stdin)
                if said is None:
                    typer.echo(
                        "\nNothing answers here, its input having ended: it waits "
                        "for your answer in the inbox."
                    )
                    watched = [elsewhere]
                    continue
                answer = yes(said)
                if answer is not None:
                    return answer
                typer.echo(f"Answer y or n. {question} [y/N]: ", nl=False)


class Unattended(Model, Asker):
    """No terminal: what's said goes to the launch's log, and each question waits for its answer in the inbox alone, which the dashboard gives, as a held launch's launcher asks (`lup_dev.launch.held`)."""

    say_to: Callable[[str], None]
    """Where it says what it would print."""
    within: timedelta = timedelta(hours=1)
    """How long a question waits for its answer before nothing waits on it any
    more: a launch with no one waiting on it isn't started by a late answer."""

    @override
    def say(self, text: str) -> None:
        self.say_to(text)

    @override
    def show(self, text: str) -> None:
        del text

    @override
    def ask(self, question: str, elsewhere: Elsewhere) -> bool | None:
        """Wait for the question's answer in the inbox, and return none: it's answered elsewhere; raise `TrustError` where none comes within `within`."""
        self.say_to(f"{question} It waits for your answer in the inbox.")
        deadline = time.monotonic() + self.within.total_seconds()
        while elsewhere.given() is None:
            left = deadline - time.monotonic()
            if left <= 0:
                message = (
                    f"no answer to the approval came within {self.within}, so the "
                    "launch that asked it doesn't start"
                )
                raise TrustError(message)
            select.select([elsewhere], [], [], left)
        return None


class Approving(Model, arbitrary_types_allowed=True):
    """An approval as a terminal asks it: the summary, the whole diff only when asked for, then the question; until it's answered here or elsewhere."""

    asker: Asker
    approvals: Approvals
    number: int
    """The approval's item in the inbox."""
    summary: str
    question: str
    diff: str
    """The whole diff, coloured; empty where no file changed, when it isn't offered."""

    def given(self) -> Given:
        """Ask, and return the answer that holds: this terminal's, or one given elsewhere first, which is said."""
        with self.approvals.waited(self.number) as elsewhere:
            self.asker.say(self.summary)
            whole = self.asker.ask(WHOLE, elsewhere) if self.diff else False
            if whole:
                self.asker.show(self.diff)
            approve = (
                None
                if whole is None or elsewhere.given() is not None
                else self.asker.ask(self.question, elsewhere)
            )
            given = (
                self.elsewhere(elsewhere)
                if approve is None
                else self.approvals.answer(self.number, approved=approve)
            )
        if not given.here:
            said = "approved" if given.approved else "declined"
            self.asker.say(f"{cited(self.number)} was {said} elsewhere.")
        return given

    def elsewhere(self, elsewhere: Elsewhere) -> Given:
        """Return the answer given elsewhere, once the terminal stopped asking for it."""
        approved = elsewhere.given()
        if approved is None:
            message = (
                f"the terminal stopped asking about {cited(self.number)} with no "
                "answer given here or elsewhere"
            )
            raise TrustError(message)
        return Given(approved=approved, here=False)


def decision(item: Item) -> bool:
    """Return an approval's answer, yes or no; refuse where it has none, with `SupersededError` where a later one replaced it."""
    match item.state:
        case Decided(approved=approved):
            return approved
        case Superseded(by=by):
            message = (
                f"{cited(item.number)} was superseded by {cited(by)}, an approval of "
                "the host zone at the running branch's tip."
            )
            raise SupersededError(message)
        case _:
            message = f"{cited(item.number)} has no answer, yes or no"
            raise TrustError(message)


class Awaited(MutableModel, Elsewhere, arbitrary_types_allowed=True):
    """An approval waited on through the host service; waited on again from the service that runs next where one stops."""

    host: HostClient
    number: int
    outstanding: Outstanding
    answer: bool | None = None
    """The answer given elsewhere, once it came."""

    @override
    def fileno(self) -> int:
        return self.outstanding.fileno()

    @override
    def given(self) -> bool | None:
        """Read the answer where the service sent it; where the service closed the wait without one, as it does stopping, wait again on the one that runs next."""
        if self.answer is not None or not self.outstanding.ready():
            return self.answer
        replied = self.outstanding.reply(Shown)
        self.outstanding.close()
        if replied is None:
            self.outstanding = self.host.rejoined(AwaitApproval(number=self.number))
            return None
        self.answer = decision(replied.item)
        return self.answer


class InboxApprovals(Model, Approvals, arbitrary_types_allowed=True):
    """lup's inbox, through the host service, which is started where none runs: an approval any terminal answers."""

    host: HostClient

    @override
    def asked(self, asking: AskApproval) -> int:
        """Put the approval in the inbox, the service started where none runs; a refusal is said with what may cause it."""
        self.host.ensure()
        try:
            return self.host.ask(asking, Shown).item.number
        except HostError as refused:
            message = (
                f"the host service didn't take the approval into your inbox: "
                f"{refused}. A service running a `lup-dev` older than this one "
                "doesn't know approvals: `lup-dev host stop`, then ask again"
            )
            raise TrustError(message) from refused

    @override
    @contextmanager
    def waited(self, number: int) -> Generator[Elsewhere]:
        awaited = Awaited(
            host=self.host,
            number=number,
            outstanding=self.host.held(AwaitApproval(number=number)),
        )
        try:
            yield awaited
        finally:
            awaited.outstanding.close()

    @override
    def answer(self, number: int, *, approved: bool, comment: str = "") -> Given:
        settled = self.host.ask(
            AnswerApproval(number=number, approved=approved, comment=comment), Settled
        )
        return Given(approved=decision(settled.item), here=settled.here)


class Toolchain(ABC):
    """What installs the copies of `lup-dev` the host runs, and names the user's own command."""

    @abstractmethod
    def install(
        self, tool: Tool, git: Git, commit: str, copy: CopyLayout, *, users: bool
    ) -> None:
        """Install `tool` at `commit`, read from the repository `git` runs in, as the repository's `copy`, a directory no process runs.

        With `users`, it's the copy a person runs and the host service runs from
        too, which what's installed beside it for them comes with: the dashboard.
        """

    @abstractmethod
    def commands(self) -> Path:
        """Return the directory of the person's own commands."""


def building(resolved: Resolved) -> list[Step]:
    """Return the declaration's steps that build what a copy carries, in the gate's order: the engine, and the dashboard's page.

    They're lup's own repository's (`LupDevelopment`, in its `lup_project.py`):
    the steps of its gate that build a file. Raise `TrustError` where there's
    none, since a copy can't be built without its engine.
    """
    steps = [step for step in resolved.gate if step.builds is not None]
    if not steps:
        message = (
            "the declaration has no step building the engine, which lup's own "
            "declares, so its `lup-dev` can't be built"
        )
        raise TrustError(message)
    return steps


class UvToolchain(Model, Toolchain, arbitrary_types_allowed=True):
    """uv: the engine built as the gate builds it, and each copy installed as a uv tool.

    Each of the repository's copies is a uv tool of its own, in its own
    directories (`UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, set for that install
    alone).
    """

    executable: str = "uv"
    tools: Tools = Field(default_factory=Machine)
    """Where the declaration's requirements are looked for before its builds
    run: the host's programs."""

    @override
    def install(
        self, tool: Tool, git: Git, commit: str, copy: CopyLayout, *, users: bool
    ) -> None:
        """Install the commit's copy: built from its source, or the release it pins.

        A workspace's source is exported whole into a scratch directory and built
        there once, never installed from a worktree, so what installs is the
        commit's: each file written from git's objects, as the diff the operator
        approved read them, whatever the repository's `.gitattributes` say.
        """
        match tool:
            case WorkspaceTool():
                with tempfile.TemporaryDirectory() as scratch:
                    tree = Path(scratch)
                    git.export(commit, tree)
                    self.build(tree)
                    self.built(tool, tree, copy, users=users)
            case ReleaseTool():
                self.released(tool, copy)

    def uv(self, place: CopyLayout) -> list[str]:
        """Return the command running uv's tools in the repository's copy `place`."""
        return [
            "env",
            f"UV_TOOL_DIR={place.tools}",
            f"UV_TOOL_BIN_DIR={place.bin}",
            self.executable,
        ]

    @override
    def commands(self) -> Path:
        """Return uv's directory of tools' commands, which is on the person's `PATH`."""
        found = run(self.executable, "tool", "dir", "--bin")
        return Path(found.text().strip())

    def build(self, tree: Path) -> None:
        """Run the tree's own steps building what the copy carries, as the gate runs them.

        The steps are read from the tree's declaration and run through its runner,
        unless they say not, so the gate and trust build the engine, and the
        dashboard's page, one way. The declaration's requirements are checked
        first, as the gate checks them, since this is where its builds run on
        the host, where no gate runs: lup's own needs Node, uv, and pnpm 11 or
        later, which installs the engine's and the page's packages. A required
        one missing raises `RequirementError`, naming each, before any runs.
        """
        resolved = resolve(load(tree).project)
        check(resolved.requirements, self.tools).require()
        for step in building(resolved):
            program, *arguments = invoked(step, resolved.runner)
            run(program, *arguments, cwd=tree, shown=True)

    def built(
        self, tool: WorkspaceTool, tree: Path, place: CopyLayout, *, users: bool
    ) -> None:
        """Install the package from `tree` in `place`, its dependencies held to its `uv.lock`.

        `uv tool install` resolves a tool's dependencies afresh, ignoring the
        workspace's lock, so the locked versions are exported as constraints, the
        whole workspace's, which hold what's installed beside it too. A workspace
        package it needs is installed from the tree as a copy; with `users`, each
        package beside it is installed with it (`--with`).
        """
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            run(
                self.executable,
                "export",
                "--all-packages",
                "--no-dev",
                "--no-emit-workspace",
                "--no-hashes",
                "--frozen",
                "--format",
                "requirements-txt",
                "--quiet",
                "--output-file",
                str(constraints),
                cwd=tree,
            )
            program, *arguments = self.uv(place)
            withs = tool.beside if users else []
            run(
                program,
                *arguments,
                "tool",
                "install",
                "--force",
                "--constraints",
                str(constraints),
                *(part for each in withs for part in ["--with", str(tree / each)]),
                str(tree / tool.package),
                cwd=tree,
                shown=True,
            )

    def released(self, tool: ReleaseTool, place: CopyLayout) -> None:
        """Install the release from its index in `place`, its dependencies held to the pins."""
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            constraints.write_text(tool.constraints())
            program, *arguments = self.uv(place)
            run(
                program,
                *arguments,
                "tool",
                "install",
                "--force",
                "--constraints",
                str(constraints),
                "--default-index",
                tool.registry,
                tool.requirement(),
                shown=True,
            )


def dotted(name: str) -> list[str] | None:
    """Read a module's dotted name into its parts, as Python's parser reads it; none where it isn't one.

    >>> dotted("audiobook.conditions"), dotted("not a module")
    (['audiobook', 'conditions'], None)
    """

    def parts(node: ast.expr) -> list[str] | None:
        match node:
            case ast.Name(id=first):
                return [first]
            case ast.Attribute(value=value, attr=last):
                before = parts(value)
                return None if before is None else [*before, last]
            case _:
                return None

    try:
        return parts(ast.parse(name, mode="eval").body)
    except SyntaxError:
        return None


class Place(Model):
    """Where a module is in a commit's export, as Python's path finder finds it."""

    file: Path | None
    """Its file: a module's, or a regular package's `__init__.py`; none for a
    namespace package, which has none."""
    search: list[Path] | None
    """Where its submodules are found, for a package; none for a module."""


def place(name: list[str], directories: list[Path]) -> Place | None:
    """Find the module `name` among `directories`, as Python's path finder would, importing nothing.

    The first directory holding it as a module or a regular package has it;
    otherwise every directory holding it as a directory with no `__init__.py`
    shares it as a namespace package. None where none holds it.
    """
    finders = [
        FileFinder(str(directory), (SourceFileLoader, SOURCE_SUFFIXES))
        for directory in directories
    ]
    specs = [finder.find_spec(".".join(name)) for finder in finders]
    found = [spec for spec in specs if spec is not None]
    regular = next((spec for spec in found if spec.origin is not None), None)
    if regular is not None and regular.origin is not None:
        search = regular.submodule_search_locations
        return Place(
            file=Path(regular.origin),
            search=None if search is None else [Path(each) for each in search],
        )
    shared = [
        Path(each) for spec in found for each in spec.submodule_search_locations or []
    ]
    return Place(file=None, search=shared) if shared else None


class Ran(Model):
    """A file of a commit's export that importing a module runs, and the module it is."""

    file: Path
    name: list[str]
    """The module's dotted name, by its parts."""

    def package(self) -> list[str]:
        """Return the package a relative import in this file starts from."""
        return self.name if self.file.stem == "__init__" else self.name[:-1]


class Located(Model):
    """What importing a module from a commit's export runs, found without running it."""

    name: list[str]
    packages: list[Ran] = []
    """The `__init__.py` of each regular package holding it, outermost first, which
    run before it; as far as they're found, where the module isn't."""
    own: Ran | None = None
    """Its own file; none for a namespace package, or where it isn't found."""
    whole: bool = False
    """Whether the module itself was found, not only some packages before it."""

    def ran(self) -> list[Ran]:
        """List every file importing it runs: its packages', then its own."""
        return [*self.packages, *([self.own] if self.own is not None else [])]


def located(name: list[str], roots: list[Path]) -> Located:
    """Say what importing the module `name` from `roots` runs, finding each package on the way."""

    def within(depth: int, directories: list[Path], packages: list[Ran]) -> Located:
        prefix = name[:depth]
        found = place(prefix, directories)
        if found is None:
            return Located(name=name, packages=packages)
        ran = [] if found.file is None else [Ran(file=found.file, name=prefix)]
        if depth == len(name):
            own = ran[0] if ran else None
            return Located(name=name, packages=packages, own=own, whole=True)
        if found.search is None:
            return Located(name=name, packages=[*packages, *ran])
        return within(depth + 1, found.search, [*packages, *ran])

    return within(1, roots, [])


class Mentioned(Model):
    """What a module names that importing it may run: the modules it imports, and the conditions modules it names."""

    imported: list[list[str]] = []
    """Each module it imports, by its parts; a name imported from a module is
    there too, in case it's a submodule."""
    conditions: list[list[str]] = []
    """Each conditions module named as a string, `conditions = "audiobook.conditions"`
    or `Core(conditions=…)`, by its parts."""
    unread: list[str] = []


def mentioned(module: Ran, shown: Path) -> Mentioned:
    """Read what `module` imports and the conditions modules it names, with `ast`, running nothing.

    Every import counts, inside a function or a `TYPE_CHECKING` block too: reading
    more than runs only shows more.
    """

    def named(node: ast.AST) -> Mentioned:
        match node:
            case ast.Import(names=aliases):
                return Mentioned(
                    imported=[
                        parts for alias in aliases if (parts := dotted(alias.name))
                    ]
                )
            case ast.ImportFrom(module=source, names=aliases, level=level):
                relative = "." * level + (source or "")
                try:
                    absolute = resolve_name(relative, ".".join(module.package()))
                except ImportError as failed:
                    return Mentioned(
                        unread=[f"`{shown}` imports `{relative}`: {failed}"]
                    )
                base = dotted(absolute) or []
                names = [[*base, alias.name] for alias in aliases if alias.name != "*"]
                return Mentioned(imported=[base, *names] if base else [])
            case (
                ast.Assign(
                    targets=[ast.Name(id="conditions")],
                    value=ast.Constant(value=str() as address),
                )
                | ast.AnnAssign(
                    target=ast.Name(id="conditions"),
                    value=ast.Constant(value=str() as address),
                )
                | ast.keyword(
                    arg="conditions", value=ast.Constant(value=str() as address)
                )
            ):
                parts = dotted(address)
                if parts is None:
                    said = (
                        f"`{shown}` names `{address}` as a conditions module, which "
                        "isn't a module's dotted name"
                    )
                    return Mentioned(unread=[said])
                return Mentioned(conditions=[parts])
            case _:
                return Mentioned()

    try:
        tree = ast.parse(module.file.read_bytes(), filename=str(shown))
    except (SyntaxError, ValueError) as failed:
        said = f"`{shown}` doesn't parse ({failed}), so what it imports isn't followed"
        return Mentioned(unread=[said])
    each = [named(node) for node in ast.walk(tree)]
    return Mentioned(
        imported=[name for one in each for name in one.imported],
        conditions=[name for one in each for name in one.conditions],
        unread=[said for one in each for said in one.unread],
    )


class Reached(Model):
    """What one file of the declaration reaches: the files it runs and those it names to be read."""

    run: list[Ran] = []
    """Files importing it runs, followed in turn."""
    read: list[Ran] = []
    """Conditions modules, read on the host and never run, so not followed."""
    unread: list[str] = []


def declared(tree: Path, covered: list[Path]) -> Named:
    """Find the files the declaration in `tree` runs on the host, reading them with `ast`.

    `tree` is a commit's export of what importing its declaration reads, with
    the person's own layer beside it where there's one, which runs too and is
    followed the same way. The
    declaration runs as the judge imports it, from its root, `src/` and each uv
    workspace member (`import_roots`): each module it imports that's found
    there, with each package holding it, and in turn what they import. A
    conditions module its modules name is read on the host, never run, so it's
    named without what it imports; the packages holding it run, since finding
    it imports them. Nothing in `tree` runs. A path under one of `covered`,
    already in the zone whole (the `lup-dev` source the host runs), isn't
    followed.
    """
    layout = CheckoutLayout(root=tree)
    try:
        pyproject = Pyproject.read(layout.pyproject)
        broken = ""
    except (tomllib.TOMLDecodeError, ValidationError) as failed:
        pyproject = Pyproject()
        broken = (
            f"`{layout.pyproject.name}` doesn't read ({failed}), so the workspace's "
            "members aren't searched"
        )
    roots = import_roots(tree, pyproject)

    def shown(file: Path) -> Path:
        return file.relative_to(tree)

    def module(file: Path) -> Ran:
        where = shown(file)
        own = [] if where.stem == "__init__" else [where.stem]
        return Ran(file=file, name=[*where.parent.parts, *own])

    def kept(each: Ran) -> bool:
        return not any(shown(each.file).is_relative_to(place) for place in covered)

    def reached(current: Ran) -> Reached:
        named = mentioned(current, shown(current.file))
        imports = [located(name, roots) for name in named.imported]
        conditions = [located(name, roots) for name in named.conditions]
        missing = [
            f"`{shown(current.file)}` names `{'.'.join(found.name)}` as a conditions "
            "module, which isn't in the commit"
            for found in conditions
            if not found.whole
        ]
        run = [
            *(each for found in imports for each in found.ran()),
            *(each for found in conditions for each in found.packages),
        ]
        read = [found.own for found in conditions if found.own is not None]
        return Reached(
            run=[each for each in run if kept(each)],
            read=[each for each in read if kept(each)],
            unread=[*named.unread, *missing],
        )

    def walk(frontier: list[Ran], seen: list[Path]) -> Iterator[Reached]:
        fresh = list(
            {
                shown(each.file): each
                for each in frontier
                if shown(each.file) not in seen
            }.values()
        )
        if not fresh:
            return
        done = [reached(each) for each in fresh]
        yield from done
        further = [each for one in done for each in one.run]
        yield from walk(further, [*seen, *(shown(each.file) for each in fresh)])

    starts = [
        *([module(layout.declaration)] if layout.declaration.is_file() else []),
        *(module(file) for file in sorted(layout.declaration_package.rglob("*.py"))),
        *(
            [module(layout.local_declaration)]
            if layout.local_declaration.is_file()
            else []
        ),
    ]
    walked = list(walk(starts, []))
    paths = dict.fromkeys(
        shown(each.file) for one in walked for each in [*one.run, *one.read]
    )
    return Named(
        paths=list(paths),
        unread=[
            *([broken] if broken else []),
            *(s for one in walked for s in one.unread),
        ],
    )


class Sides(Model):
    """Each file differing between two commits, by its path, with its entry on each side that has one."""

    before: dict[Path, Tracked]
    after: dict[Path, Tracked]


def sides(git: Git, start: str | None, end: str, paths: list[Path]) -> Sides:
    """Return each file under `paths` differing from the commit `start` to the commit `end`, or each `end` holds where there's no `start`, read from each object's own bytes (`Git.own_changes`): raise `GitError` where one can't be read or isn't what its id says."""

    def under(changes: dict[PurePosixPath, Tracked | None]) -> dict[Path, Tracked]:
        return {
            Path(path): entry
            for path, entry in changes.items()
            if entry is not None
            and any(Path(path).is_relative_to(each) for each in paths)
        }

    return Sides(
        before={} if start is None else under(git.own_changes(end, start)),
        after=under(git.own_changes(start, end)),
    )


def diffed(
    git: Git,
    start: str | None,
    end: str,
    paths: list[Path],
    *,
    width: int = 100_000,
    graph: int = 40,
) -> Diffed:
    """Return git's diff of `paths` from the commit `start`, or from nothing where there's none, to the commit `end`, coloured, and its count of each file.

    git's own diff, with no external diff command or text conversion the
    repository's configuration could name, made in a scratch store holding only
    the files that differ, each hashed against its id (`sides`, `Git.contents`),
    so nothing a room writes in the repository's store, its attributes among it,
    has a say in what the operator reads. The count is git's `--stat`: each file
    on a line with its lines changed and a bar of those added and removed, a
    file created or removed marked (`--compact-summary`), then the totals. It's
    `width` columns wide at most, so git never shortens a path to fit, its bar
    `graph` columns at most. Text that isn't UTF-8 is shown with replacement
    characters.
    """
    if not paths:
        return Diffed()
    found = sides(git, start, end, paths)
    blobs = list(
        dict.fromkeys(
            each.object
            for each in [*found.before.values(), *found.after.values()]
            if each.kind == "blob"
        )
    )
    with tempfile.TemporaryDirectory(prefix="lup-diff-") as scratch:
        root = Path(scratch)
        Git(cwd=root).run("init", "--quiet", "--bare", "--template=", str(root))
        apart = Git.pinned(root)
        apart.run(
            "fast-import",
            "--quiet",
            stdin=b"".join(
                b"blob\ndata %d\n%b\n" % (len(content), content)
                for content in git.contents(blobs)
            ),
        )

        def tree(entries: dict[Path, Tracked], name: str) -> str:
            staging = apart.model_copy(update={"index": root / name})
            listed = b"".join(
                f"{each.mode} {each.object}\t".encode() + os.fsencode(each.path) + b"\0"
                for each in entries.values()
            )
            staging.run("update-index", "-z", "--index-info", stdin=listed)
            return staging.text("write-tree")

        was, now = tree(found.before, "before"), tree(found.after, "after")
        own = ["diff", "--no-ext-diff", "--no-textconv", "--color=always"]
        counted = apart.run(
            *own,
            f"--stat={width}",
            f"--stat-graph-width={graph}",
            "--compact-summary",
            was,
            now,
        )
        shown = apart.run(*own, was, now)
    return Diffed(
        stat=counted.output.decode(errors="replace"),
        diff=shown.output.decode(errors="replace"),
    )


def compared(
    approved: str | None,
    current: str | None,
    name: str | None = None,
    here: str = "worktree",
) -> Diffed:
    """Return git's diff of a file git doesn't hold, from the copy `approved` to the `current` one, coloured; empty where they're the same.

    The file is `name`, the person's own layer where it's none. Git holds
    neither copy, so each is written into a scratch directory, as `approved/`
    and `here/`, where the current one is (`worktree/` for the layer), and git
    compares them there (`git diff --no-index`), its own diff with no external
    diff command or text conversion. A copy that's none is no file: the file
    created, or removed.
    """
    if approved == current:
        return Diffed()
    name = name or CheckoutLayout(root=Path()).local_declaration.name
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)

        def placed(side: str, text: str | None) -> str:
            if text is None:
                return os.devnull
            path = root / side / name
            path.parent.mkdir()
            path.write_text(text)
            return str(path.relative_to(root))

        before = placed("approved", approved)
        after = placed(here, current)
        own = [
            "diff",
            "--no-index",
            "--no-ext-diff",
            "--no-textconv",
            "--no-prefix",
            "--color=always",
        ]
        git = Git(cwd=root)
        counted = git.run(*own, "--stat", "--compact-summary", before, after, ok=[1])
        shown = git.run(*own, before, after, ok=[1])
    return Diffed(
        stat=counted.output.decode(errors="replace"),
        diff=shown.output.decode(errors="replace"),
    )


def files_between(
    git: Git, start: str | None, end: str, paths: list[Path]
) -> list[ChangedFile]:
    """Return each file under `paths` whose content differs from the commit `start`, or from nothing where there's none, to the commit `end`, whole on each side, by path.

    A file created or deleted has none on the side it's missing from. A
    submodule is left out, as a commit's export leaves it: its files aren't the
    commit's. The contents are read by one `git cat-file`, each hashed against
    its id (`sides`, `Git.contents`).
    """
    if not paths:
        return []
    found = sides(git, start, end, paths)

    def files(side: dict[Path, Tracked]) -> dict[Path, str]:
        return {path: each.object for path, each in side.items() if each.kind == "blob"}

    before = files(found.before)
    after = files(found.after)
    either = dict.fromkeys([*before, *after])
    changed = sorted(path for path in either if before.get(path) != after.get(path))
    wanted = [
        blob
        for path in changed
        for blob in (before.get(path), after.get(path))
        if blob is not None
    ]
    read = dict(zip(wanted, git.contents(wanted), strict=True))
    return [
        ChangedFile.of(
            path,
            read.get(before.get(path, "")),
            read.get(after.get(path, "")),
        )
        for path in changed
    ]


def layer_changed(
    approved: str | None, current: str | None, name: Path | None = None
) -> list[ChangedFile]:
    """Return a file git doesn't hold, whole on each side, where it changed from the copy `approved` to the `current` one; none where they're the same.

    The file is at `name`, the person's own layer where it's none: from the
    repository's root, or absolute for one outside every repository, their
    profiles, which the judge doesn't read (`Trust.read`).
    """
    if approved == current:
        return []
    name = name or CheckoutLayout(root=Path()).local_declaration
    return [
        ChangedFile.of(
            name,
            None if approved is None else approved.encode(),
            None if current is None else current.encode(),
        )
    ]


def judged(content: Content | None) -> str | None:
    """Return one side of a changed file as the judge reads it: its text, an empty one where it isn't text, none where the file isn't there.

    >>> judged(Binary(size=3))
    ''
    """
    match content:
        case None:
            return None
        case Binary():
            return ""
        case _:
            return content.text


class Trust(Model, arbitrary_types_allowed=True):
    """The check, and the question, a launch makes about what the host runs for a repository."""

    root: Path
    """The worktree it's run from; the zone is its repository's."""
    found: Path | None = None
    """The repository's git directory, where a launch found it already, from
    its starting point or as the host recorded a spawn's: git is pinned there
    (`Git.pinned`), never led through the worktree's `.git` file again, which
    a room writes. None finds it through `root`, as the operator's own
    `lup-dev trust` does in their worktree."""
    reading: Path | None = None
    """The worktree an approval it asks has its types read in, where that's not
    `root` (`proposed`): a bare repository's own directory holds no project, so
    nothing it imports resolves there."""
    layout: Layout
    asker: Asker
    """The launching terminal, where the operator reads the summary and answers."""
    approvals: Approvals
    """The inbox, where the approval waits, answered at the launching terminal or
    any other."""
    toolchain: Toolchain
    host: HostClient
    switcher: Switcher
    """What moves the host service to a copy of lup's own, and back where it
    doesn't answer."""
    clock: Clock
    checker: Checker
    """The engine the zone's change is judged with, for the review's reading of
    each file."""
    parser: Parser
    """The engine's reading of a file's parse alone, which the first reading of
    the zone's change is made of."""
    linter: Linter
    """ruff, which judging runs beside the engine."""
    inside: list[str]
    """The runtimes whose session this runs inside, by name, as their adapters
    tell: inside one, nothing is asked."""
    name: str = "lup-dev"
    """The package the host runs, as the lock names it."""
    beside: list[str] = ["lup-dashboard"]
    """The workspace's packages installed beside it in the person's own copy,
    where the workspace has them, as the lock names them: the dashboard, which
    the host service runs."""

    def check(self) -> Standing:
        """Read the tip's host zone, and compare it with the one approved last."""
        return self.standing(self.repository())

    def repository(self) -> Path:
        """Return the git directory every worktree of the repository shares, which keys its approval: the one found already, where it was."""
        if self.found is not None:
            return self.found
        return Path(
            Git(cwd=self.root).text(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            )
        )

    def git(self) -> Git:
        """Return git for the repository's objects and refs: pinned to its git directory where it was found already, else run in `root`."""
        return Git(cwd=self.root) if self.found is None else Git.pinned(self.found)

    def standing(self, repository: Path) -> Standing:
        """Read the tip's host zone, beside the approval kept for `repository`."""
        zone = self.zone()
        approval = approved(self.layout, repository)
        return Standing(
            zone=zone, fingerprint=self.fingerprint(zone), approval=approval
        )

    def zone(self) -> Zone:
        """Read the host zone at the running branch's tip, as the declaration approved names it, with the person's own layer and their profiles.

        A branch the host computes is read where the host keeps it, never by its
        ref, which a room writes (`running_tip`, `lup_dev.trial`). Where the repository has no such branch, at the integration branch's
        tip, so naming one before it exists asks about what's accepted rather
        than whatever a launch's worktree has checked out; without that either,
        at the worktree's `HEAD`. The
        person's own layer, which git doesn't hold, is read by its content from
        the repository's main worktree (a clone's root, or a bare repository's
        own directory), whichever worktree trust runs from: one layer per
        repository, so a worktree added later, which git gives no ignored file,
        asks nothing. What it imports of the commit joins the zone's paths.
        Their profiles file is read by its content from their configuration,
        importing nothing of the commit. Raise
        `TrustError` before any commit, or where the lock doesn't say which
        `lup-dev` the host runs.
        """
        git = self.git()
        repository = self.repository()
        branches = approved_branches(self.layout, repository)
        commit = (
            running_tip(self.layout, repository)
            or git.commit(branches.running_ref)
            or git.commit(branches.integration_ref)
            or git.commit("HEAD")
        )
        if commit is None:
            message = (
                f"nothing is committed in {self.root}'s repository, so it has no host "
                "zone to approve"
            )
            raise TrustError(message)
        return self.zone_at(commit)

    def zone_at(self, commit: str) -> Zone:
        """Read the host zone at the commit `commit`, with the person's own layer and their profiles: see `zone`. Raise `TrustError` where the lock doesn't say which `lup-dev` the host runs."""
        tool = self.tool(commit)
        own = person_layer(self.root, self.git())
        local = own.read_text() if own.is_file() else None
        declared = self.layout.profiles.declared
        profiles = declared.read_text() if declared.is_file() else None
        named = self.named(commit, tool.paths(), local)
        declaration = CheckoutLayout(root=Path())
        listed = list(
            dict.fromkeys(
                [
                    declaration.declaration,
                    declaration.declaration_package,
                    *named.paths,
                    *tool.paths(),
                ]
            )
        )
        paths = [
            path
            for path in listed
            if not any(path != other and path.is_relative_to(other) for other in listed)
        ]
        return Zone(
            commit=commit,
            paths=paths,
            tool=tool,
            local=local,
            profiles=profiles,
            unread=named.unread,
        )

    def tool(self, commit: str) -> Tool:
        """Read which `lup-dev` the host runs from the commit's `uv.lock`."""
        lock = CheckoutLayout(root=Path()).lock
        git = self.git()
        found = [
            each.object
            for each in git.held(commit)
            if Path(each.path) == lock and each.kind == "blob"
        ]
        if not found:
            message = (
                f"{commit} holds no `{lock}`, so which `{self.name}` the host runs "
                "isn't pinned"
            )
            raise TrustError(message)
        [content] = git.contents(found)
        return Lock.parse(content.decode()).tool(self.name, self.beside)

    def named(self, commit: str, covered: list[Path], local: str | None) -> Named:
        """Find the files the commit's declaration, and `local` on top of it, run on the host, and the conditions modules they name.

        Read with `ast` from the commit's Python modules and project files,
        exported from git's objects into a scratch directory, `local`, the
        person's own layer, written beside them where there's one
        (`declared`), so no code of the project runs before the operator is
        asked. A path under one of `covered`, in the zone whole already, isn't
        followed.
        """
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch)
            self.git().export(commit, source, read_by_import)
            if local is not None:
                CheckoutLayout(root=source).local_declaration.write_text(local)
            return declared(source, covered)

    def fingerprint(self, zone: Zone) -> str:
        """Fingerprint the zone: git's listing of its files, the `lup-dev` it runs, the person's own layer and their profiles.

        The listing names each file's path, mode and object, so any change to one
        of them, or a file joining or leaving the zone, changes it: as `git
        ls-tree` writes it, each entry read from the objects' own bytes
        (`Git.held`), so what's fingerprinted is what the commit names. The person's
        own layer and their profiles count by their content, where there's each,
        so a zone without one keeps the fingerprint it had before it existed.
        """
        listed = b"".join(
            f"{each.mode} {each.kind} {each.object}\t".encode()
            + os.fsencode(each.path)
            + b"\0"
            for each in self.git().held(zone.commit)
            if any(Path(each.path).is_relative_to(path) for path in zone.paths)
        )
        digest = hashlib.sha256(listed)
        digest.update(zone.tool.model_dump_json().encode())
        if zone.local is not None:
            name = CheckoutLayout(root=Path()).local_declaration.name
            digest.update(f"\0{name}\0".encode())
            digest.update(zone.local.encode())
        if zone.profiles is not None:
            digest.update(f"\0{self.layout.profiles.declared.name}\0".encode())
            digest.update(zone.profiles.encode())
        return digest.hexdigest()

    def change(self, standing: Standing) -> Change:
        """Say what changed since the approved commit: git's diff over the zone, and the person's own layer's.

        The paths the approval held, since its commit; the paths it didn't, whole.
        The first time, or where the repository doesn't hold the approved commit,
        every path whole. The person's own layer, from the copy approved to the
        worktree's, and their profiles, from the copy approved to theirs, where
        they differ (`compared`). Each file the diff shows is
        read whole on each side too (`files_between`, `layer_changed`), with the
        judge's first reading of it, from its parse alone (`read`), which the
        host service follows with the whole judgement once it's asked (`typed`);
        where the judge fails, the files go unread and the summary says why.
        """
        git = self.git()
        zone = standing.zone
        approval = standing.approval
        tool = zone.tool.said(approval.tool if approval is not None else None)
        before = approval.local if approval is not None else None
        local = compared(before, zone.local)
        layer = layer_changed(before, zone.local)
        mine = approval.profiles if approval is not None else None
        declared = self.layout.profiles.declared
        profiles = compared(mine, zone.profiles, declared.name, "yours")
        layer = [*layer, *layer_changed(mine, zone.profiles, declared)]
        held = approval is not None and (
            git.run(
                "cat-file", "-e", f"{approval.commit}^{{commit}}", ok=[0, 1, 128]
            ).status
            == 0
        )
        if approval is None or not held:
            files = [*files_between(git, None, zone.commit, zone.paths), *layer]
            change = Change(
                commit=zone.commit,
                approved=approval.commit if approval is not None else None,
                since=None,
                changed=diffed(git, None, zone.commit, zone.paths),
                joined=Diffed(),
                local=local,
                profiles=profiles,
                files=files,
                tool=tool,
                unread=zone.unread,
            )
        else:
            kept = [path for path in zone.paths if path in approval.paths]
            joined = [path for path in zone.paths if path not in approval.paths]
            files = [
                *files_between(git, approval.commit, zone.commit, kept),
                *files_between(git, None, zone.commit, joined),
                *layer,
            ]
            change = Change(
                commit=zone.commit,
                approved=approval.commit,
                since=approval.commit,
                changed=diffed(git, approval.commit, zone.commit, kept),
                joined=diffed(git, None, zone.commit, joined),
                local=local,
                profiles=profiles,
                files=files,
                tool=tool,
                unread=zone.unread,
            )
        if approval is None:
            return change.model_copy(update={"files": self.trusted_whole(files)})
        try:
            read = self.read(self.repository(), approval, files, typed=False)
        except LupDevError as failure:
            return change.model_copy(update={"unjudged": str(failure)})
        return change.model_copy(update={"files": read, "typing": True})

    def trusted_whole(self, files: list[ChangedFile]) -> list[ChangedFile]:
        """Return a first approval's files, each read by its path's role alone, by lup's defaults with the tip's declaration protected, asking nothing: trusted as they are, they're folded for the review, and the engine doesn't run."""
        roles = self.judge(self.repository(), None, files).roles
        return [
            each
            if each.path.is_absolute()
            else each.model_copy(
                update={"reading": Reading(role=roles.role(each.path))}
            )
            for each in files
        ]

    def read(
        self,
        repository: Path,
        approval: Approval | None,
        files: list[ChangedFile],
        *,
        typed: bool,
    ) -> list[ChangedFile]:
        """Return `files` with the judge's reading of each, which the review opens them by.

        The zone's change is judged as a move of `HEAD` is, each file against
        what it was, by the declaration the host runs for the repository: the one
        approved last (`judge`). `typed`, wholly, the engine checking each file
        with lup's rules; otherwise from each file's parse alone (`Judge.parsed`),
        which costs a parse where the check costs seconds. A side that isn't
        text is judged as an empty one: no rule reads it, and only whether it's
        there decides what it asks. A file outside every repository, at an
        absolute path, the person's profiles, goes unread: the repository's
        roles and rules aren't its own, and the operator reads its whole diff in
        the summary. Raise what the judge raises.
        """
        inside = [each for each in files if not each.path.is_absolute()]
        judge = self.judge(repository, approval, inside)
        changes = [
            FileChange(
                path=each.path,
                before=judged(each.before),
                after=judged(each.after),
                baseline=judged(each.before),
            )
            for each in inside
        ]
        judgements = (
            judge.judge(changes, inform=False)
            if typed
            else judge.parsed(changes, self.parser)
        )
        read = {
            each.path: each.model_copy(update={"reading": judgement.reading()})
            for each, judgement in zip(inside, judgements, strict=True)
        }
        return [read.get(each.path, each) for each in files]

    def typed(self, repository: Path, files: list[ChangedFile]) -> list[ChangedFile]:
        """Return an approval's `files` with the judge's whole reading of each, types and lup's rules included, in place of the reading of their parse they were asked with.

        What the host service reads once the approval is in the inbox, off its
        event loop (`docs/trust.md`), by the declaration
        approved for `repository` as it stands. Raise what the judge raises.
        """
        return self.read(
            repository, approved(self.layout, repository), files, typed=True
        )

    def judge(
        self, repository: Path, approval: Approval | None, files: list[ChangedFile]
    ) -> Judge:
        """Return the judge of the zone's change: by the declaration approved last, read as the checkpoint reads it, from its commit with the person's own layer approved beside it.

        Before any approval, by lup's defaults, never the tip's own declaration,
        which importing would run before the operator is asked; the tip's
        declaration, among `files`, is the protected path it always is. git on
        the repository is pinned to `repository`, since what reads types here
        does so in a worktree a room writes, on the host, at a moment its push
        set off.
        """
        if approval is None:
            layout = CheckoutLayout(root=Path())
            declaring = [
                layout.declaration,
                CheckoutLayout(root=layout.declaration_package).package,
            ]
            source = next(
                (
                    each.path
                    for each in files
                    if each.path in declaring and each.after is not None
                ),
                None,
            )
            declaration = Declaration.of(Project(), source)
            named = None
        else:
            worktree = Worktree(
                root=self.root,
                repository=repository,
                store=Store(
                    layout=self.layout.store(self.root),
                    worktree=self.root,
                    common=repository,
                ),
                judging=Judging(layout=self.layout),
            )
            declaration = worktree.declaration
            named = conditions.declared(worktree.loaded.root, declaration.conditions)
        return Judge(
            root=self.root,
            roles=Roles(root=self.root, declaration=declaration),
            checker=self.checker,
            linter=self.linter,
            conditions=named,
        )

    def ensure(self) -> Outcome:
        """Check the tip's host zone; where it isn't the one approved, ask, in the inbox and at this terminal.

        The approval is put in the operator's inbox, the host service started
        where none runs, and the terminal shows the summary and asks; whichever
        answers first, this terminal or `lup-dev inbox answer` at another, holds,
        and this terminal stops asking where another answered (`Approving`).
        Approved, the tip's copy is installed as the repository's own, and on
        lup's own repository as the user's `lup-dev` too, with the host service,
        which runs from that, restarted on it where one runs; and the approval
        recorded. Declined, the copy approved before stays; with none approved,
        `TrustError`, since nothing approved may run. Inside an agent's session
        nothing is asked: `TrustError`. Where the repository's copy approved is
        missing, it's installed again, asking nothing: it was approved.

        Launches at once asking about the same zone wait on one approval, each
        terminal asking it: the approval's lock is held to read the zone and ask,
        and again to act on the answer, but not while it's awaited. The first to
        take it then acts on the answer; the others read what it recorded.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        copy = self.layout.judge(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(kept.with_name(f"{kept.name}.lock"))
        with lock:
            standing = self.standing(repository)
            zone = standing.zone
            approval = standing.approval
            if approval is not None and standing.approved():
                # The tip's zone is the approved one, so its copy is the same.
                again = self.reinstall(approval, zone.commit, copy)
                return Unchanged(commit=zone.commit, approval=approval, again=again)
            if self.inside:
                message = (
                    f"this runs inside a {self.inside[0]} session, and an agent "
                    "doesn't approve the code the host runs: answer from your own "
                    "terminal"
                )
                raise TrustError(message)
            change = self.change(standing)
            summary = change.summary()
            question = change.question()
            diff = change.diff()
            number = self.approvals.asked(
                AskApproval(
                    question=question,
                    summary=summary,
                    diff=diff,
                    files=change.files,
                    typing=change.typing,
                    repository=repository,
                    fingerprint=standing.fingerprint,
                    worktree=self.root,
                    first=change.approved is None,
                )
            )
        inboxed = (
            f"It's {cited(number)} in your inbox too: `lup-dev inbox answer {number}` "
            "answers it from any terminal."
        )
        try:
            given = Approving(
                asker=self.asker,
                approvals=self.approvals,
                number=number,
                summary=f"{summary}\n\n{inboxed}",
                question=question,
                diff=diff,
            ).given()
        except SupersededError as replaced:
            self.asker.say(f"{replaced} The tip moved: asking about it instead.")
            return self.ensure()
        with lock:
            return self.answered(repository, standing, given)

    def proposed(self, pushed_by: Conversation | None = None) -> int | None:
        """Put the approval of the tip's host zone in the operator's inbox where it isn't the one approved, asking nothing here, and return its number; none where it's approved.

        What a push that moves the running branch starts, on the host
        (`cli.py`): nobody waits on the approval, and the terminal answering it
        acts on the answer (`settle`). `pushed_by` is the main conversation of
        the session who pushed, which the operator's comment on their answer
        is told to; none where no session's is known. An approval waiting about
        the same zone is joined, as a launch joins it. Its types are read in
        `reading`, where it's given: what `root` is, for a push, need hold no
        project.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            standing = self.standing(repository)
            if standing.approval is not None and standing.approved():
                return None
            return self.inboxed(repository, standing, pushed_by=pushed_by)

    def inboxed(
        self,
        repository: Path,
        standing: Standing,
        *,
        pushed_by: Conversation | None = None,
        said: str = "",
    ) -> int:
        """Put the approval of the zone `standing` read in the operator's inbox, asking nothing here, what came of the last time first, where `said` says; return its number."""
        change = self.change(standing)
        summary = change.summary()
        return self.approvals.asked(
            AskApproval(
                question=change.question(),
                summary=f"{said}\n\n{summary}" if said else summary,
                diff=change.diff(),
                files=change.files,
                typing=change.typing,
                repository=repository,
                fingerprint=standing.fingerprint,
                worktree=self.reading or self.root,
                pushed_by=pushed_by,
                first=change.approved is None,
            )
        )

    def settle(self, fingerprint: str, given: Given) -> Outcome | None:
        """Act on the operator's answer to the approval of the zone `fingerprint`, given in the inbox: install and record it, or keep the copy approved before.

        As a launch waiting on it acts (`answered`), and only once between them.
        Return none where the tip's zone isn't that one any more, the
        running branch having moved since it was asked: approving it would
        approve what the operator didn't read, so `lup-dev trust` asks anew.

        Answered from a page, nobody may be watching this run, so a copy that
        doesn't answer puts the approval back in the inbox, why first, which the
        host service that stayed or came back serves.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            standing = self.standing(repository)
            if standing.fingerprint != fingerprint:
                return None
            outcome = self.answered(repository, standing, given)
            if isinstance(outcome, Unanswered):
                self.inboxed(repository, standing, said=outcome.said)
            return outcome

    def answered(self, repository: Path, standing: Standing, given: Given) -> Outcome:
        """Act on the operator's answer about the zone `standing` read: install and record it, or keep the copy approved before.

        Where another launch waiting on the same approval acted on it first, its
        approval is read, and nothing is installed twice. Where only the
        person's own layer or their profiles changed, the copy approved before
        is the commit's already, so the approval is recorded and nothing
        installed or restarted. The branches are read here, from what the answer
        has just approved, and from here alone (`read_branches`), so a decline
        leaves them as they stand.
        """
        kept = self.layout.approved(repository)
        copy = self.layout.judge(repository)
        zone = standing.zone
        now = approved(self.layout, repository)
        if now is not None and now.fingerprint == standing.fingerprint:
            again = self.reinstall(now, zone.commit, copy)
            return Unchanged(commit=zone.commit, approval=now, again=again)
        if not given.approved:
            if now is None:
                message = (
                    f"you declined the host zone at {zone.commit}, and none was "
                    "approved before, so there's no `lup-dev` the host may run: "
                    "nothing launches"
                )
                raise TrustError(message)
            again = self.reinstall(now, now.commit, copy)
            return Kept(commit=zone.commit, approval=now, again=again)
        read = self.read_branches(zone, now)
        recorded = Approval(
            commit=zone.commit,
            fingerprint=standing.fingerprint,
            paths=zone.paths,
            tool=zone.tool,
            time=self.clock.now(),
            local=zone.local,
            profiles=zone.profiles,
            branches=read.branches,
            declaration=read.declaration,
        )
        if now is not None and now.commit == zone.commit and now.tool == zone.tool:
            # Only the person's own layer or their profiles changed, which the
            # judge and a launch read from the approval: the copy is the
            # commit's already, so nothing is installed, and no service restarts
            # under running sessions.
            self.reinstall(now, zone.commit, copy)
            write_model(kept, recorded)
            self.reapproved(recorded, copy)
            return Trusted(
                approval=recorded,
                restarted=False,
                installed=False,
                layer=now.local != zone.local,
                profiles=now.profiles != zone.profiles,
                branches=read.said,
            )
        if not zone.tool.lups_own():
            self.installed(zone.tool, zone.commit, copy)
            write_model(kept, recorded)
            return Trusted(approval=recorded, restarted=False, branches=read.said)
        with self.built(recorded, copy) as built:
            switch = self.switcher.to(built)
        if isinstance(switch, Switched):
            return Trusted(approval=recorded, restarted=switch.ran, branches=read.said)
        if now is None:
            raise TrustError(switch.report())
        return Unanswered(commit=zone.commit, approval=now, said=switch.report())

    def read_branches(self, zone: Zone, now: Approval | None) -> BranchesRead:
        """Read the branches the declaration at `zone`'s commit names, and the declaration as judging reads it, its person's own layer on it: what the operator has just approved, so it may run.

        Exported from git's objects and imported as a launch imports the
        declaration approved (`approved_declaration`). Where it doesn't load,
        they stay what `now` says, as the judge's last declaration that loaded
        stands in for one that can't, and the answer says so.
        """
        before = Branches() if now is None else now.branches
        try:
            with tempfile.TemporaryDirectory(prefix="lup-branches-") as scratch:
                source = Path(scratch)
                self.git().export(zone.commit, source, read_by_import)
                if zone.local is not None:
                    CheckoutLayout(root=source).local_declaration.write_text(zone.local)
                declared = load(source)
                after = resolve(declared.project).branches
                declaration = Declaration.of(declared.project, declared.source)
        except ProjectError as failure:
            said = (
                f"The branches stay `{before.integration}` to integrate on and "
                f"`{before.running}` to run, since its declaration doesn't load: "
                f"{failure}"
            )
            return BranchesRead(
                branches=before,
                said=said,
                declaration=None if now is None else now.declaration,
            )
        return BranchesRead(
            branches=after,
            said=branches_moved(before, after),
            declaration=declaration,
        )

    def reapproved(self, recorded: Approval, copy: JudgeLayout) -> None:
        """Keep what's approved with the copy the link names, where it's one kept: going back to it brings back this, the person's own layer and their profiles among it."""
        copies = Copies(layout=copy)
        running = copies.running()
        if running is not None:
            copies.recorded(running.model_copy(update={"approval": recorded}))

    def reinstall(self, approval: Approval, commit: str, copy: JudgeLayout) -> bool:
        """Install the repository's copy approved, from `commit`, where it's missing; say whether it was.

        `commit` holds the zone approved. Raise `TrustError` where it's gone from
        the repository.
        """
        if copy.command(approval.tool.name).is_file():
            return False
        if self.git().commit(commit) is None:
            message = (
                f"this repository's copy of `{approval.tool.name}`, approved at "
                f"{commit}, is missing from {copy.home}, and that commit is gone "
                "from the repository, so there's nothing to install it from: "
                "approve the running branch's tip once it changes the host zone"
            )
            raise TrustError(message)
        self.installed(approval.tool, commit, copy, approval)
        return True

    def kept_first(self) -> str | None:
        """Install the copy approved as one kept, and move the host service to it, where lup's own repository has none yet: what's asked of `lup-dev trust` once, after the first approval of a lup that keeps them, which the lup before it carried out. Say what came of it; none where there was nothing to do.

        The commit is the one the service runs already, and it's the operator's
        own command, since it restarts what their sessions use, so a launch
        leaves it for them. What ran stays where it is until this answers.
        """
        repository = self.repository()
        approval = approved(self.layout, repository)
        if approval is None or not approval.tool.lups_own() or self.inside:
            return None
        copy = self.layout.judge(repository)
        if Copies(layout=copy).running() is not None:
            return None
        if self.git().commit(approval.commit) is None:
            return None
        kept = self.layout.approved(repository)
        with (
            FileLock(kept.with_name(f"{kept.name}.lock")),
            self.built(approval, copy) as built,
        ):
            return self.switcher.to(built).report()

    def installed(
        self,
        tool: Tool,
        commit: str,
        copies: JudgeLayout,
        approval: Approval | None = None,
    ) -> None:
        """Install `tool` at `commit` as a copy of the repository's whose copies are `copies`, in a directory of its own, and switch to it once the install has finished, so no process ever runs a copy half installed (`Copies`).

        A copy of lup's own has the dashboard beside it, and keeps a record of
        `approval`, where it's given.
        """
        held = Copies(layout=copies)
        with held.installing() as copy:
            self.toolchain.install(
                tool, self.git(), commit, copy, users=tool.lups_own()
            )
            if approval is not None and tool.lups_own():
                held.recorded(self.kept(copy, approval))
            held.switch(copy)

    @contextmanager
    def built(self, approval: Approval, copies: JudgeLayout) -> Generator[KeptCopy]:
        """Install the copy `approval` approves, and keep its record, with nothing switched to it: the repository's lock is held while the context is open, so the sweep leaves it until it's switched to, or until what's done with it says otherwise."""
        held = Copies(layout=copies)
        with held.installing() as copy:
            self.toolchain.install(
                approval.tool, self.git(), approval.commit, copy, users=True
            )
            kept = self.kept(copy, approval)
            held.recorded(kept)
            yield kept

    def kept(self, copy: CopyLayout, approval: Approval) -> KeptCopy:
        """Return the record of `copy`, installed for `approval`, with the first line of its commit, printable alone, since a room wrote it."""
        subject = self.git().subject(approval.commit)
        return KeptCopy(
            name=copy.home.name,
            repository=self.repository(),
            approval=approval,
            subject="".join(each for each in subject if each.isprintable()),
        )


def machine_trust(
    root: Path,
    inside: list[str],
    reading: Path | None = None,
    asker: Asker | None = None,
    *,
    found: Path | None = None,
) -> Trust:
    """Return trust on launch for the repository at `root`, with this machine's settings, the terminal, the inbox in the host service, uv, the service's client, and the engine and ruff to judge the zone's change with.

    `inside` names the runtimes whose session this runs inside, `reading`
    the worktree an approval it asks has its types read in (`Trust.reading`),
    `asker` where it asks, this terminal by default, and `found` the
    repository's git directory, where a launch found it already
    (`Trust.found`).
    """
    settings = LupDevSettings()
    layout = Layout.of(settings)
    clock = SystemClock()
    host = HostClient(layout=layout.host, clock=clock, starter=host_starter(layout))
    toolchain = UvToolchain()
    return Trust(
        root=root,
        found=found,
        reading=reading,
        layout=layout,
        asker=Terminal() if asker is None else asker,
        approvals=InboxApprovals(host=host),
        toolchain=toolchain,
        host=host,
        switcher=Switching(
            layout=layout,
            host=host,
            answers=Serving(clock=clock),
            processes=Programs(),
            clock=clock,
            commands=toolchain.commands,
        ),
        clock=clock,
        checker=EngineChecker.configured(settings),
        parser=EngineParser(),
        linter=Ruff(),
        inside=inside,
    )


def trusted(root: Path, inside: list[str], *, found: Path | None = None) -> Outcome:
    """Check what the host runs for the repository at `root`, whose git directory a launch `found` already where it's given: a launch's first step.

    As `Trust.ensure` does, on this machine (`machine_trust`). Raise
    `TrustError` where nothing approved may run.
    """
    return machine_trust(root, inside, found=found).ensure()
