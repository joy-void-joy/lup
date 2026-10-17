"""Trust on launch: the code the host runs for a repository, approved before it runs.

`docs/launch.md`, *Trust on launch*. A repository's host zone is what the host runs
for it, read at the integration branch's tip, so what's approved is what the judge
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
  (`docs/related-repositories.md`, decision 8). A room writes the worktree, so
  an edit made there runs nowhere until approved: the judge and a launch read
  the copy kept with the approval. Where it changed, its diff is in the summary
  itself (`compared`).

The zone's fingerprint is kept with the commit the operator approved, per
repository, in lup's state (`Approval`). `trusted`, which a launch calls before
anything else, and `lup-dev trust` compare the tip's zone with it (`Trust.check`).
Where it changed, or nothing was approved, the operator reads a summary first
(`Change.summary`): what's approved and why it runs on the host, the commit
approved before and the tip, and git's own count of each file changed since
(`git diff --stat --compact-summary`), coloured, as git prints it. Then they're
asked whether to show the whole diff, no by default, a yes showing it through the
terminal's pager; then whether to approve, no by default (`Asker`). The question
is an item in the operator's inbox from the start (`Approvals`, the host service
started where none runs), which the launching terminal answers as `lup-dev inbox
answer` at any other does, whichever comes first; the terminal stops asking where
another answered first (`Approving`, `Elsewhere`). Launches asking about the same
zone at once wait on one approval. The answer:
- yes: the tip's copy is installed as the repository's own (`Toolchain`, into
  `Layout.judge`; for the workspace's source, the engine built first through the
  declaration's own step and runner, as the gate builds it), which the host
  service runs for each of the repository's hooks; and the approval recorded. On
  lup's own repository, whose copy is lup's own command, it's installed as the
  user's `lup-dev` too, the one a person runs and the host service runs from, and
  the service is restarted on it where one runs;
- no: the copy approved before stays, and the launch says the tip isn't the code
  judging its session; with nothing approved yet, nothing launches.

A repository's copy approved but missing from its place, removed or never
installed there, is installed from the commit approved, asking nothing.

A push from a room that moves the integration branch puts the approval of the
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
import tomllib
from abc import ABC, abstractmethod
from contextlib import contextmanager
from importlib.machinery import SOURCE_SUFFIXES, FileFinder, SourceFileLoader
from importlib.util import resolve_name
from pathlib import Path
from typing import TYPE_CHECKING, override

import typer
from filelock import FileLock
from pydantic import Field, ValidationError
from rich.console import Console
from rich.text import Text

from lup.programs import run
from lup.types import Model, MutableModel
from lup_dev.approval import Approval, ReleaseTool, Tool, WorkspaceTool, approved
from lup_dev.clock import Clock, SystemClock
from lup_dev.declaration.load import (
    Pyproject,
    import_roots,
    load,
    person_layer,
    read_by_import,
)
from lup_dev.declaration.resolve import resolve
from lup_dev.errors import LupDevError
from lup_dev.gate import invoked
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient, Outstanding
from lup_dev.host.protocol import HostError
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AskApproval,
    AwaitApproval,
    Settled,
    Shown,
)
from lup_dev.inbox.store import Decided, Item, Superseded
from lup_dev.layout import CheckoutLayout, JudgeLayout, Layout
from lup_dev.settings import LupDevSettings
from lup_dev.stored import write_model

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from contextlib import AbstractContextManager

    from lup_dev.catalog.gate import Step
    from lup_dev.declaration.resolve import Resolved


class TrustError(LupDevError):
    """The host zone can't be read, or no approved copy is there for the host to run."""


class SupersededError(TrustError):
    """An approval a later one of the same repository replaced, the integration branch's tip having moved: the later one is asked."""


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

    def tool(self, name: str) -> Tool:
        """Return the package `name` the host runs, as the lock resolves it.

        Where it's a member of the lock's workspace, the workspace's own source;
        where it comes from an index, that release. Raise `TrustError` where the
        lock doesn't pin it, pins it twice, or resolves it from anywhere else.
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
            return WorkspaceTool(
                name=name,
                package=home,
                members=[each for each in members if each is not None],
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
    tool: list[str]
    """How the `lup-dev` release changed, line by line; none for the workspace's
    own source, whose change is in the diff."""
    unread: list[str] = []
    """What of the declaration couldn't be followed, so the zone may miss a file it runs."""

    def before(self) -> str:
        """Say which commit was approved before, and whether the zone is shown since it or whole."""
        if self.approved is None:
            return "Approved before: nothing, so the zone is shown whole."
        if self.since is None:
            return (
                f"Approved before: {self.approved}, which the repository no longer "
                "holds, so the zone is shown whole."
            )
        return f"Approved before: {self.approved}."

    def summary(self) -> str:
        """Return what the operator reads first: what's approved and why, the commits, and git's count of each file.

        The count is git's own, as git prints it: the paths approved before,
        then those joining the zone, shown whole. The person's own layer, which
        git doesn't hold, is shown whole where it changed: its diff, not a count,
        since it's short and nothing else shows it. A release's change is said
        by its versions, and what of the declaration couldn't be followed is
        said last.
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
        unknown = "Not followed, so the zone may miss a file the declaration runs:"
        unread = (
            [unknown, *(f"  {each}" for each in self.unread)] if self.unread else []
        )
        said = [
            WHY,
            "",
            self.before(),
            f"The tip: {self.commit}.",
            "",
            *changed,
            *joined,
            *local,
            *self.tool,
            *unread,
        ]
        return "\n".join(said)

    def diff(self) -> str:
        """Return the whole diff, coloured: the paths approved before, then those joining the zone, then the person's own layer."""
        return self.changed.diff + self.joined.diff + self.local.diff

    def question(self) -> str:
        """Ask whether to approve the zone, and run its `lup-dev` on the host."""
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
    from only where the copy is lup's own command."""
    installed: bool = True
    """Whether the copy was installed: not where only the person's own layer
    changed, the copy approved before being the commit's already."""

    def report(self) -> str:
        """Say what was installed, and where the host service stands."""
        if not self.installed:
            return (
                "Approved: your own layer, which judges this repository's sessions "
                f"from their next hook, beside `lup-dev` from {self.approval.commit} "
                "as before."
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
            else "the next launch starts the host service on it"
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


type Outcome = Unchanged | Trusted | Kept
"""What `Trust.ensure` came to: approved before, approved at this check, or declined."""


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
    def answer(self, number: int, *, approved: bool) -> Given:
        """Answer approval `number` here; return the answer that holds, which another terminal may have given first."""


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


def line(descriptor: int) -> str:
    """Read one line from `descriptor` a byte at a time, so nothing past it leaves the stream `select` watches; empty at its end."""

    def read() -> Iterator[bytes]:
        while (byte := os.read(descriptor, 1)) not in [b"", b"\n"]:
            yield byte

    return b"".join(read()).decode(errors="replace")


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
        answer is dropped, so it reaches nothing after.
        """
        typer.echo(f"{question} [y/N]: ", nl=False)
        while True:
            readable, _, _ = select.select([self.stdin, elsewhere], [], [])
            if elsewhere in readable and elsewhere.given() is not None:
                typer.echo()
                if os.isatty(self.stdin):
                    termios.tcflush(self.stdin, termios.TCIFLUSH)
                return None
            if self.stdin in readable:
                answer = yes(line(self.stdin))
                if answer is not None:
                    return answer
                typer.echo(f"Answer y or n. {question} [y/N]: ", nl=False)


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
            self.asker.say(f"Item {self.number} was {said} elsewhere.")
        return given

    def elsewhere(self, elsewhere: Elsewhere) -> Given:
        """Return the answer given elsewhere, once the terminal stopped asking for it."""
        approved = elsewhere.given()
        if approved is None:
            message = (
                f"the terminal stopped asking about item {self.number} with no "
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
                f"Item {item.number} was superseded by item {by}, an approval of "
                "the host zone at the integration branch's tip."
            )
            raise SupersededError(message)
        case _:
            message = f"item {item.number} has no answer, yes or no"
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
    def answer(self, number: int, *, approved: bool) -> Given:
        settled = self.host.ask(
            AnswerApproval(number=number, approved=approved), Settled
        )
        return Given(approved=decision(settled.item), here=settled.here)


class Toolchain(ABC):
    """What installs the copies of `lup-dev` the host runs, and names the user's own command."""

    @abstractmethod
    def install(
        self, tool: Tool, root: Path, commit: str, copy: JudgeLayout, *, users: bool
    ) -> None:
        """Install `tool` at `commit`, in the repository at `root`, as the repository's `copy`.

        With `users`, it's installed as the user's own `lup-dev` too, the one a
        person runs and the host service runs from. Each replaces the copy there.
        """

    @abstractmethod
    def command(self, name: str) -> list[str]:
        """Return the command running the user's own copy of package `name`."""


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


class UvToolchain(Model, Toolchain):
    """uv: the engine built as the gate builds it, and each copy installed as a uv tool.

    The repository's own copy is a uv tool of its own, in its own directories
    (`UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, set for that install alone); the user's
    own is in uv's.
    """

    executable: str = "uv"

    @override
    def install(
        self, tool: Tool, root: Path, commit: str, copy: JudgeLayout, *, users: bool
    ) -> None:
        """Install the commit's copy: built from its source, or the release it pins.

        A workspace's source is exported whole into a scratch directory and built
        there once, never installed from a worktree, so what installs is the
        commit's: each file written from git's objects, as the diff the operator
        approved read them, whatever the repository's `.gitattributes` say.
        """
        places = [copy, *([None] if users else [])]
        match tool:
            case WorkspaceTool():
                with tempfile.TemporaryDirectory() as scratch:
                    tree = Path(scratch)
                    Git(cwd=root).export(commit, tree)
                    self.build(tree)
                    self.built(tool, tree, places)
            case ReleaseTool():
                self.released(tool, places)

    def uv(self, place: JudgeLayout | None) -> list[str]:
        """Return the command running uv's tools in `place`: a repository's own copy, or the user's where none."""
        if place is None:
            return [self.executable]
        return [
            "env",
            f"UV_TOOL_DIR={place.tools}",
            f"UV_TOOL_BIN_DIR={place.bin}",
            self.executable,
        ]

    @override
    def command(self, name: str) -> list[str]:
        """Return the copy uv installed, in its directory of tools' commands."""
        found = run(self.executable, "tool", "dir", "--bin")
        return [str(Path(found.text().strip()) / name)]

    def build(self, tree: Path) -> None:
        """Run the tree's own steps building what the copy carries, as the gate runs them.

        The steps are read from the tree's declaration and run through its runner,
        unless they say not, so the gate and trust build the engine, and the
        dashboard's page, one way.
        """
        resolved = resolve(load(tree).project)
        for step in building(resolved):
            program, *arguments = invoked(step, resolved.runner)
            run(program, *arguments, cwd=tree, shown=True)

    def built(
        self, tool: WorkspaceTool, tree: Path, places: list[JudgeLayout | None]
    ) -> None:
        """Install the package from `tree` in each of `places`, its dependencies held to its `uv.lock`.

        `uv tool install` resolves a tool's dependencies afresh, ignoring the
        workspace's lock, so the locked versions are exported as constraints. A
        workspace package it needs is installed from the tree as a copy.
        """
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            run(
                self.executable,
                "export",
                "--package",
                tool.name,
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
            for place in places:
                program, *arguments = self.uv(place)
                run(
                    program,
                    *arguments,
                    "tool",
                    "install",
                    "--force",
                    "--constraints",
                    str(constraints),
                    str(tree / tool.package),
                    cwd=tree,
                    shown=True,
                )

    def released(self, tool: ReleaseTool, places: list[JudgeLayout | None]) -> None:
        """Install the release from its index in each of `places`, its dependencies held to the pins."""
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            constraints.write_text(tool.constraints())
            for place in places:
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


def diffed(
    git: Git,
    start: str,
    end: str,
    paths: list[Path],
    *,
    width: int = 100_000,
    graph: int = 40,
) -> Diffed:
    """Return git's diff of `paths` from `start` to `end`, coloured, and its count of each file.

    git's own diff, with no external diff command or text conversion the
    repository's configuration could name. The count is git's `--stat`: each
    file on a line with its lines changed and a bar of those added and removed,
    a file created or removed marked (`--compact-summary`), then the totals. It's
    `width` columns wide at most, so git never shortens a path to fit, its bar
    `graph` columns at most. Text that isn't UTF-8 is shown with replacement
    characters.
    """
    if not paths:
        return Diffed()
    spec = ["--", *(str(path) for path in paths)]
    own = [
        "--literal-pathspecs",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--color=always",
    ]
    counted = git.run(
        *own,
        f"--stat={width}",
        f"--stat-graph-width={graph}",
        "--compact-summary",
        start,
        end,
        *spec,
    )
    shown = git.run(*own, start, end, *spec)
    return Diffed(
        stat=counted.output.decode(errors="replace"),
        diff=shown.output.decode(errors="replace"),
    )


def compared(approved: str | None, current: str | None) -> Diffed:
    """Return git's diff of the person's own layer, from the copy `approved` to the `current` one, coloured; empty where they're the same.

    Git holds neither copy, so each is written into a scratch directory, as
    `approved/` and `worktree/`, and git compares them there (`git diff
    --no-index`), its own diff with no external diff command or text
    conversion. A copy that's none is no file: the layer created, or removed.
    """
    if approved == current:
        return Diffed()
    name = CheckoutLayout(root=Path()).local_declaration.name
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
        after = placed("worktree", current)
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


class Trust(Model, arbitrary_types_allowed=True):
    """The check, and the question, a launch makes about what the host runs for a repository."""

    root: Path
    """The worktree it's run from; the zone is its repository's."""
    layout: Layout
    integration: str
    """The branch whose tip holds the zone; without one, the worktree's `HEAD`."""
    asker: Asker
    """The launching terminal, where the operator reads the summary and answers."""
    approvals: Approvals
    """The inbox, where the approval waits, answered at the launching terminal or
    any other."""
    toolchain: Toolchain
    host: HostClient
    clock: Clock
    inside: list[str]
    """The runtimes whose session this runs inside, by name, as their adapters
    tell: inside one, nothing is asked."""
    name: str = "lup-dev"
    """The package the host runs, as the lock names it."""

    def check(self) -> Standing:
        """Read the tip's host zone, and compare it with the one approved last."""
        return self.standing(self.repository())

    def repository(self) -> Path:
        """Return the git directory every worktree of the repository shares, which keys its approval."""
        return Path(
            Git(cwd=self.root).text(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            )
        )

    def standing(self, repository: Path) -> Standing:
        """Read the tip's host zone, beside the approval kept for `repository`."""
        zone = self.zone()
        approval = approved(self.layout, repository)
        return Standing(
            zone=zone, fingerprint=self.fingerprint(zone), approval=approval
        )

    def zone(self) -> Zone:
        """Read the host zone at the integration branch's tip, with the person's own layer.

        Where the repository has no such branch, at the worktree's `HEAD`. The
        person's own layer, which git doesn't hold, is read by its content from
        the repository's main worktree (a clone's root, or a bare repository's
        own directory), whichever worktree trust runs from: one layer per
        repository, so a worktree added later, which git gives no ignored file,
        asks nothing. What it imports of the commit joins the zone's paths. Raise
        `TrustError` before any commit, or where the lock doesn't say which
        `lup-dev` the host runs.
        """
        git = Git(cwd=self.root)
        commit = git.commit(f"refs/heads/{self.integration}") or git.commit("HEAD")
        if commit is None:
            message = (
                f"nothing is committed in {self.root}'s repository, so it has no host "
                "zone to approve"
            )
            raise TrustError(message)
        tool = self.tool(commit)
        own = person_layer(self.root)
        local = own.read_text() if own.is_file() else None
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
            commit=commit, paths=paths, tool=tool, local=local, unread=named.unread
        )

    def tool(self, commit: str) -> Tool:
        """Read which `lup-dev` the host runs from the commit's `uv.lock`."""
        lock = CheckoutLayout(root=Path()).lock
        found = Git(cwd=self.root).run(
            "cat-file", "blob", f"{commit}:{lock}", ok=[0, 128]
        )
        if found.status != 0:
            message = (
                f"{commit} holds no `{lock}`, so which `{self.name}` the host runs "
                "isn't pinned"
            )
            raise TrustError(message)
        return Lock.parse(found.output.decode()).tool(self.name)

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
            Git(cwd=self.root).export(commit, source, read_by_import)
            if local is not None:
                CheckoutLayout(root=source).local_declaration.write_text(local)
            return declared(source, covered)

    def fingerprint(self, zone: Zone) -> str:
        """Fingerprint the zone: git's listing of its files, the `lup-dev` it runs, and the person's own layer.

        The listing names each file's path, mode and object, so any change to one
        of them, or a file joining or leaving the zone, changes it. The person's
        own layer counts by its content, where there's one, so a zone without one
        keeps the fingerprint it had before the layer existed.
        """
        listed = Git(cwd=self.root).run(
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            zone.commit,
            "--",
            *(str(path) for path in zone.paths),
        )
        digest = hashlib.sha256(listed.output)
        digest.update(zone.tool.model_dump_json().encode())
        if zone.local is not None:
            name = CheckoutLayout(root=Path()).local_declaration.name
            digest.update(f"\0{name}\0".encode())
            digest.update(zone.local.encode())
        return digest.hexdigest()

    def change(self, standing: Standing) -> Change:
        """Say what changed since the approved commit: git's diff over the zone, and the person's own layer's.

        The paths the approval held, since its commit; the paths it didn't, whole.
        The first time, or where the repository doesn't hold the approved commit,
        every path whole. The person's own layer, from the copy approved to the
        worktree's, where they differ (`compared`).
        """
        git = Git(cwd=self.root)
        zone = standing.zone
        approval = standing.approval
        empty = git.run("hash-object", "-t", "tree", "--stdin", stdin=b"")
        nothing = empty.output.decode().strip()
        tool = zone.tool.said(approval.tool if approval is not None else None)
        local = compared(approval.local if approval is not None else None, zone.local)
        held = approval is not None and (
            git.run(
                "cat-file", "-e", f"{approval.commit}^{{commit}}", ok=[0, 1, 128]
            ).status
            == 0
        )
        if approval is None or not held:
            return Change(
                commit=zone.commit,
                approved=approval.commit if approval is not None else None,
                since=None,
                changed=diffed(git, nothing, zone.commit, zone.paths),
                joined=Diffed(),
                local=local,
                tool=tool,
                unread=zone.unread,
            )
        kept = [path for path in zone.paths if path in approval.paths]
        joined = [path for path in zone.paths if path not in approval.paths]
        return Change(
            commit=zone.commit,
            approved=approval.commit,
            since=approval.commit,
            changed=diffed(git, approval.commit, zone.commit, kept),
            joined=diffed(git, nothing, zone.commit, joined),
            local=local,
            tool=tool,
            unread=zone.unread,
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
                    repository=repository,
                    fingerprint=standing.fingerprint,
                    worktree=self.root,
                )
            )
        inboxed = (
            f"It's item {number} in your inbox too: `lup-dev inbox answer {number}` "
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

    def proposed(self) -> int | None:
        """Put the approval of the tip's host zone in the operator's inbox where it isn't the one approved, asking nothing here, and return its number; none where it's approved.

        What a push that moves the integration branch starts, on the host
        (`cli.py`): nobody waits on the approval, and the terminal answering it
        acts on the answer (`settle`). An approval waiting about the same zone is
        joined, as a launch joins it.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            standing = self.standing(repository)
            if standing.approval is not None and standing.approved():
                return None
            change = self.change(standing)
            return self.approvals.asked(
                AskApproval(
                    question=change.question(),
                    summary=change.summary(),
                    diff=change.diff(),
                    repository=repository,
                    fingerprint=standing.fingerprint,
                    worktree=self.root,
                )
            )

    def settle(self, fingerprint: str, given: Given) -> Outcome | None:
        """Act on the operator's answer to the approval of the zone `fingerprint`, given in the inbox: install and record it, or keep the copy approved before.

        As a launch waiting on it acts (`answered`), and only once between them.
        Return none where the tip's zone isn't that one any more, the
        integration branch having moved since it was asked: approving it would
        approve what the operator didn't read, so `lup-dev trust` asks anew.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            standing = self.standing(repository)
            if standing.fingerprint != fingerprint:
                return None
            return self.answered(repository, standing, given)

    def answered(self, repository: Path, standing: Standing, given: Given) -> Outcome:
        """Act on the operator's answer about the zone `standing` read: install and record it, or keep the copy approved before.

        Where another launch waiting on the same approval acted on it first, its
        approval is read, and nothing is installed twice. Where only the
        person's own layer changed, the copy approved before is the commit's
        already, so the approval is recorded and nothing installed or restarted.
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
        recorded = Approval(
            commit=zone.commit,
            fingerprint=standing.fingerprint,
            paths=zone.paths,
            tool=zone.tool,
            time=self.clock.now(),
            local=zone.local,
        )
        if now is not None and now.commit == zone.commit and now.tool == zone.tool:
            # Only the person's own layer changed, which the judge reads from the
            # approval at each hook: the copy is the commit's already, so nothing
            # is installed, and no service restarts under running sessions.
            self.reinstall(now, zone.commit, copy)
            write_model(kept, recorded)
            return Trusted(approval=recorded, restarted=False, installed=False)
        own = zone.tool.lups_own()
        self.toolchain.install(zone.tool, self.root, zone.commit, copy, users=own)
        restarted = own and self.restart()
        write_model(kept, recorded)
        return Trusted(approval=recorded, restarted=restarted)

    def reinstall(self, approval: Approval, commit: str, copy: JudgeLayout) -> bool:
        """Install the repository's copy approved, from `commit`, where it's missing; say whether it was.

        `commit` holds the zone approved. Raise `TrustError` where it's gone from
        the repository.
        """
        if copy.command(approval.tool.name).is_file():
            return False
        if Git(cwd=self.root).commit(commit) is None:
            message = (
                f"this repository's copy of `{approval.tool.name}`, approved at "
                f"{commit}, is missing from {copy.home}, and that commit is gone "
                "from the repository, so there's nothing to install it from: "
                "approve the integration branch's tip once it changes the host zone"
            )
            raise TrustError(message)
        self.toolchain.install(approval.tool, self.root, commit, copy, users=False)
        return True

    def restart(self) -> bool:
        """Restart the host service on the copy just installed, where one runs.

        Say whether one ran. Its launches stay recorded through the stop, and the
        copy started serves them again in the directories their rooms mounted.
        """
        if not self.host.stop():
            return False
        starter = Detached(command=[*self.toolchain.command(self.name), "host"])
        self.host.model_copy(update={"starter": starter}).ensure()
        return True


def machine_trust(root: Path, inside: list[str]) -> Trust:
    """Return trust on launch for the repository at `root`, with this machine's settings, the terminal, the inbox in the host service, uv and the service's client.

    `inside` names the runtimes whose session this runs inside.
    """
    settings = LupDevSettings()
    layout = Layout.of(settings)
    clock = SystemClock()
    host = HostClient(layout=layout.host, clock=clock, starter=Detached())
    return Trust(
        root=root,
        layout=layout,
        integration=settings.lup_integration_branch,
        asker=Terminal(),
        approvals=InboxApprovals(host=host),
        toolchain=UvToolchain(),
        host=host,
        clock=clock,
        inside=inside,
    )


def trusted(root: Path, inside: list[str]) -> Outcome:
    """Check what the host runs for the repository at `root`: a launch's first step.

    As `Trust.ensure` does, on this machine (`machine_trust`). Raise
    `TrustError` where nothing approved may run.
    """
    return machine_trust(root, inside).ensure()
