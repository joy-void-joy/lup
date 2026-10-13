"""Trust on launch: the code the host runs for a repository, approved before it runs.

`docs/launch.md`, *Trust on launch*. A repository's host zone is what the host runs
for it, read at the integration branch's tip as the judge reads the declaration, so
what's approved is what the judge and the host service run, never a branch's own
copy (`Zone`):
- its declaration, `lup_project.py` or the package `lup_project/`, and the files a
  selected module names that the host imports: each conditions module, with the
  `__init__.py` of each package holding it;
- the `lup-dev` the host runs (`Tool`): where the repository's lock resolves it
  from the repository's own workspace, as lup's does, that source
  (`WorkspaceTool`: uv's files, the project file and modules of each workspace
  package `lup-dev` needs, and the engine's source); otherwise the release the lock
  pins, with every package it needs at its locked version (`ReleaseTool`).

The zone's fingerprint is kept with the commit the operator approved, per
repository, in lup's state (`Approval`). `trusted`, which a launch calls before
anything else, and `lup-dev trust` compare the tip's zone with it (`Trust.check`).
Where it changed, or nothing was approved, the change since the approved commit is
shown through the terminal's pager and the operator asked once, yes or no
(`Asker`):
- yes: the tip's copy is installed as the host's `lup-dev` (`Toolchain`; for the
  workspace's source, the engine built first through the declaration's own step
  and runner, as the gate builds it), the host service restarted on it where one
  runs, and the approval recorded;
- no: the copy approved before stays, and the launch says the tip isn't the code
  judging its session; with nothing approved yet, nothing launches.
"""

import hashlib
import io
import itertools
import tarfile
import tempfile
import tomllib
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, override

import sh
import typer
from filelock import FileLock
from pydantic import Field
from rich.console import Console
from rich.text import Text

from lup.types import Model
from lup_dev.clock import Clock, SystemClock
from lup_dev.codescan.conditions import ConditionError, module_file
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.load import load
from lup_dev.declaration.resolve import Declaration, resolve
from lup_dev.declaration.runner import Uv
from lup_dev.errors import LupDevError
from lup_dev.gate import invoked
from lup_dev.git import Git
from lup_dev.host.client import Detached, HostClient
from lup_dev.layout import CheckoutLayout, Layout, PackageLayout
from lup_dev.settings import LupDevSettings
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup_dev.catalog.gate import Step
    from lup_dev.declaration.resolve import Resolved


class TrustError(LupDevError):
    """The host zone can't be read, or no approved copy is there for the host to run."""


class WorkspaceTool(Model):
    """`lup-dev` from the repository's own workspace, as lup's lock resolves it.

    The host runs a copy built from the approved commit's source.
    """

    kind: Literal["workspace"] = "workspace"
    name: str
    """The package, as the lock names it."""
    package: Path
    """Its directory in the repository, which `uv tool install` installs."""
    members: list[Path]
    """The directory of each workspace package it needs, its own first: the copy
    carries their modules."""

    def paths(self) -> list[Path]:
        """List what the copy is built from, from the repository's root.

        uv's files, which hold the copy's dependencies to the lock and say where
        the workspace's packages are; each package's project file and modules; and
        the engine's source, which the build bundles into the package.
        """
        packages = [PackageLayout(root=member) for member in self.members]
        return [
            *(Path(each) for each in Uv().environment()),
            *(place for each in packages for place in [each.pyproject, each.source]),
            PackageLayout(root=self.package).engine,
        ]

    def said(self, before: Tool | None) -> list[str]:
        """Say how the `lup-dev` the host runs changed beyond its source's diff."""
        match before:
            case ReleaseTool():
                said = (
                    f"`{self.name}` was the release {before.version} from "
                    f"{before.registry}; it becomes this repository's own source, "
                    f"at {self.package}."
                )
                return [said]
            case _:
                return []


class ReleaseTool(Model):
    """A `lup-dev` release the repository's lock pins, from an index."""

    kind: Literal["release"] = "release"
    name: str
    version: str
    registry: str
    """The index the lock resolves it from."""
    pins: dict[str, str]
    """Every other package it needs, by name, at the version the lock pins: the
    copy's dependencies are held to them."""

    def paths(self) -> list[Path]:
        """List none: a release is its version and pins, not the repository's files."""
        return []

    def requirement(self) -> str:
        """Return the release as a requirement: its name at its version."""
        return f"{self.name}=={self.version}"

    def constraints(self) -> str:
        """Return the pins as a requirements file, which uv takes as constraints."""
        return "".join(f"{name}=={version}\n" for name, version in self.pins.items())

    def said(self, before: Tool | None) -> list[str]:
        """Say how the release, and the versions it's held to, changed."""
        here = f"{self.version} from {self.registry}"
        match before:
            case ReleaseTool():
                there = f"{before.version} from {before.registry}"
                heading = (
                    f"`{self.name}` {here}, as before:"
                    if there == here
                    else f"`{self.name}` {there} becomes {here}:"
                )
                earlier = before.pins
            case _:
                heading = f"`{self.name}` {here}, needing:"
                earlier = {}

        def moved(name: str) -> str:
            was = earlier.get(name)
            pinned = self.pins.get(name)
            if was is None:
                return f"  {name} {pinned}, added" if earlier else f"  {name} {pinned}"
            if pinned is None:
                return f"  {name} {was}, dropped"
            return f"  {name} {was} becomes {pinned}"

        names = list(dict.fromkeys([*earlier, *self.pins]))
        changed = [name for name in names if earlier.get(name) != self.pins.get(name)]
        return [heading, *(moved(name) for name in changed)]


type Tool = Annotated[WorkspaceTool | ReleaseTool, Field(discriminator="kind")]
"""The `lup-dev` the host runs for a repository: its workspace's own, or a release."""


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
    unloaded: str = ""
    """Why the declaration doesn't load here, so the files its modules name aren't
    among `paths`; empty where it loads."""


class Named(Model):
    """The files a declaration's modules name that the host imports, or why not."""

    paths: list[Path] = []
    unloaded: str = ""
    """Why the declaration doesn't load, so they aren't known; empty where it does."""


class Approval(Model):
    """The host zone the operator approved last for a repository, and when."""

    commit: str
    fingerprint: str
    paths: list[Path]
    """The zone's paths at `commit`: a later change shows what changed in them
    since, and any path the zone holds beside them whole."""
    tool: Tool
    time: datetime


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
    """git's diff of some of the zone's paths between two trees, and its count."""

    shortstat: str = ""
    """git's one-line count of it (`git diff --shortstat`); empty where none changed."""
    diff: str = ""
    """The diff, coloured for the terminal."""


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
    tool: list[str]
    """How the `lup-dev` release changed, line by line; none for the workspace's
    own source, whose change is in the diff."""
    unloaded: str = ""

    def opening(self) -> str:
        """Say which commit is shown, since which, and how much changed."""
        counted = self.changed.shortstat or "no file of it changed"
        if self.since is not None:
            return (
                f"The host zone at {self.commit}, since {self.since}, the commit you "
                f"approved last: {counted}."
            )
        if self.approved is not None:
            return (
                f"The host zone at {self.commit}, whole, since {self.approved}, the "
                f"commit you approved last, isn't in the repository: {counted}."
            )
        return (
            f"The host zone at {self.commit}, whole, since nothing was approved yet: "
            f"{counted}."
        )

    def text(self) -> str:
        """Return what the pager shows: the opening, what else changed, the diff."""
        joined = (
            [f"Joining the zone, shown whole: {self.joined.shortstat}."]
            if self.joined.shortstat
            else []
        )
        unknown = (
            "The declaration doesn't load with the `lup-dev` running this, so the "
            f"files its modules name aren't known or shown: {self.unloaded}"
        )
        unloaded = [unknown] if self.unloaded else []
        said = [self.opening(), *joined, *unloaded, *self.tool, ""]
        return "\n".join(said) + "\n" + self.changed.diff + self.joined.diff

    def question(self) -> str:
        """Ask whether to approve the zone, and run its `lup-dev` on the host."""
        return (
            f"Approve the host zone at {self.commit}, and install its `lup-dev` as "
            "the one the host runs?"
        )


class Unchanged(Model):
    """The tip's host zone is the one approved: nothing was asked or installed."""

    commit: str
    approval: Approval

    def report(self) -> str:
        """Say that nothing changed, in one line."""
        return (
            f"The host zone at {self.commit} is the one you approved at "
            f"{self.approval.commit}: nothing to review."
        )


class Trusted(Model):
    """The operator approved the tip's host zone: its copy is installed, and recorded."""

    approval: Approval
    restarted: bool
    """Whether a host service ran, and was restarted on the copy."""

    def report(self) -> str:
        """Say what was installed, and where the host service stands."""
        service = (
            "the host service restarted on it"
            if self.restarted
            else "the next launch starts the host service on it"
        )
        return (
            f"Approved: `lup-dev` from {self.approval.commit} is the one the host "
            f"runs, and {service}."
        )


class Kept(Model):
    """The operator declined the tip's host zone: the copy approved before stays."""

    commit: str
    approval: Approval

    def report(self) -> str:
        """Say that the tip isn't the code judging the session, and what is."""
        return (
            "Declined: the tip isn't the code judging this session. The host keeps "
            f"running `lup-dev` from {self.approval.commit}, which you approved; the "
            f"host zone at {self.commit} differs from it."
        )


type Outcome = Unchanged | Trusted | Kept
"""What `Trust.ensure` came to: approved before, approved at this check, or declined."""


class Asker(ABC):
    """Where the operator reads the change and answers: the terminal, until the inbox."""

    @abstractmethod
    def show(self, text: str) -> None:
        """Show `text` to the operator, through the terminal's pager."""

    @abstractmethod
    def ask(self, question: str) -> bool:
        """Ask `question` once, and say whether the operator answered yes."""


class Terminal(Asker):
    """The terminal: the change through its pager, then a question, no by default."""

    @override
    def show(self, text: str) -> None:
        console = Console()
        with console.pager(styles=True):
            console.print(Text.from_ansi(text), soft_wrap=True)

    @override
    def ask(self, question: str) -> bool:
        return typer.confirm(question, default=False)


class Toolchain(ABC):
    """What installs a copy of `lup-dev` as the host's, and names the command running it."""

    @abstractmethod
    def install(self, tool: Tool, root: Path, commit: str) -> None:
        """Install `tool` at `commit`, in the repository at `root`, replacing any copy."""

    @abstractmethod
    def command(self, name: str) -> list[str]:
        """Return the command running the copy of package `name` installed."""


def engine(resolved: Resolved) -> Step:
    """Return the declaration's step that builds the engine, which a copy carries.

    It's lup's own repository's (`LupDevelopment`, in its `lup_project.py`): the
    one step of its gate that builds a file. Raise `TrustError` where there's none,
    or more than one.
    """
    building = [step for step in resolved.gate if step.builds is not None]
    match building:
        case [step]:
            return step
        case []:
            message = (
                "the declaration has no step building the engine, which lup's own "
                "declares, so its `lup-dev` can't be built"
            )
        case _:
            names = ", ".join(f"`{step.name}`" for step in building)
            message = (
                f"the declaration has several steps that build a file, {names}, so "
                "which builds the engine isn't clear"
            )
    raise TrustError(message)


def export(root: Path, commit: str, into: Path) -> None:
    """Write every file `commit` holds into `into`, as `git archive` gives them."""
    archived = Git(cwd=root).run("archive", "--format=tar", commit)
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as archive:
        archive.extractall(into, filter="data")


class UvToolchain(Model, Toolchain):
    """uv: the engine built as the gate builds it, and each copy installed as a uv tool."""

    executable: str = "uv"

    @override
    def install(self, tool: Tool, root: Path, commit: str) -> None:
        """Install the commit's copy: built from its source, or the release it pins.

        A workspace's source is exported whole into a scratch directory and built
        there, never installed from a worktree, so what installs is the commit's.
        """
        match tool:
            case WorkspaceTool():
                with tempfile.TemporaryDirectory() as scratch:
                    tree = Path(scratch)
                    export(root, commit, tree)
                    self.build(tree)
                    self.built(tool, tree)
            case ReleaseTool():
                self.released(tool)

    @override
    def command(self, name: str) -> list[str]:
        """Return the copy uv installed, in its directory of tools' commands."""
        found = sh.Command(self.executable)("tool", "dir", "--bin", _tty_out=False)
        return [str(Path(str(found).strip()) / name)]

    def build(self, tree: Path) -> None:
        """Run the tree's own step building the engine, as the gate runs it.

        The step is read from the tree's declaration and runs through its runner,
        unless it says not, so the gate and trust build the engine one way.
        """
        resolved = resolve(load(tree).project)
        program, *arguments = invoked(engine(resolved), resolved.runner)
        sh.Command(program)(*arguments, _cwd=str(tree), _fg=True)

    def built(self, tool: WorkspaceTool, tree: Path) -> None:
        """Install the package from `tree`, its dependencies held to its `uv.lock`.

        `uv tool install` resolves a tool's dependencies afresh, ignoring the
        workspace's lock, so the locked versions are exported as constraints. A
        workspace package it needs is installed from the tree as a copy.
        """
        uv = sh.Command(self.executable)
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            uv(
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
                _cwd=str(tree),
            )
            uv(
                "tool",
                "install",
                "--force",
                "--constraints",
                str(constraints),
                str(tree / tool.package),
                _cwd=str(tree),
                _fg=True,
            )

    def released(self, tool: ReleaseTool) -> None:
        """Install the release from its index, its dependencies held to the pins."""
        with tempfile.TemporaryDirectory() as scratch:
            constraints = Path(scratch) / "constraints.txt"
            constraints.write_text(tool.constraints())
            sh.Command(self.executable)(
                "tool",
                "install",
                "--force",
                "--constraints",
                str(constraints),
                "--default-index",
                tool.registry,
                tool.requirement(),
                _fg=True,
            )


def holding(root: Path, file: Path) -> list[Path]:
    """List `file` and the `__init__.py` of each package holding it, from `root`.

    Importing a module imports each package holding it first; outside `root`,
    nothing is listed.
    """
    inits = [
        CheckoutLayout(root=parent).package
        for parent in file.parents
        if parent.is_relative_to(root) and parent != root
    ]
    packages = itertools.takewhile(Path.is_file, inits)
    return [
        each.relative_to(root)
        for each in dict.fromkeys([file, *packages])
        if each.is_relative_to(root)
    ]


def diffed(git: Git, start: str, end: str, paths: list[Path]) -> Diffed:
    """Return git's diff of `paths` from `start` to `end`, coloured, and its count.

    git's own diff, with no external diff command or text conversion the
    repository's configuration could name. Text that isn't UTF-8 is shown with
    replacement characters.
    """
    if not paths:
        return Diffed()
    spec = ["--", *(str(path) for path in paths)]
    counted = git.text("--literal-pathspecs", "diff", "--shortstat", start, end, *spec)
    shown = git.run(
        "--literal-pathspecs",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--color=always",
        start,
        end,
        *spec,
    )
    return Diffed(shortstat=counted, diff=shown.stdout.decode(errors="replace"))


class Trust(Model, arbitrary_types_allowed=True):
    """The check, and the question, a launch makes about what the host runs for a repository."""

    root: Path
    """The worktree it's run from; the zone is its repository's."""
    layout: Layout
    integration: str
    """The branch whose tip holds the zone; without one, the worktree's `HEAD`."""
    asker: Asker
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
        approval = read_model(self.layout.approved(repository), Approval)
        return Standing(
            zone=zone, fingerprint=self.fingerprint(zone), approval=approval
        )

    def zone(self) -> Zone:
        """Read the host zone at the integration branch's tip.

        Where the repository has no such branch, at the worktree's `HEAD`. Raise
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
        named = self.named(commit)
        declared = CheckoutLayout(root=Path())
        paths = [
            declared.declaration,
            declared.declaration_package,
            *named.paths,
            *tool.paths(),
        ]
        return Zone(
            commit=commit,
            paths=list(dict.fromkeys(paths)),
            tool=tool,
            unloaded=named.unloaded,
        )

    def tool(self, commit: str) -> Tool:
        """Read which `lup-dev` the host runs from the commit's `uv.lock`."""
        lock = CheckoutLayout(root=Path()).lock
        found = Git(cwd=self.root).run(
            "cat-file", "blob", f"{commit}:{lock}", ok=[0, 128]
        )
        if found.exit_code != 0:
            message = (
                f"{commit} holds no `{lock}`, so which `{self.name}` the host runs "
                "isn't pinned"
            )
            raise TrustError(message)
        return Lock.parse(found.stdout.decode()).tool(self.name)

    def named(self, commit: str) -> Named:
        """Find the files the commit's selected modules name that the host imports.

        The declaration is loaded from the commit's export, as the judge loads it;
        where it can't load, or a module it names can't be found, they aren't
        known, and why is kept.
        """
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch)
            export(self.root, commit, source)
            try:
                conditions = Declaration.read(source).conditions
                files = [module_file(source, each) for each in conditions]
            except (ProjectError, ConditionError) as failure:
                return Named(unloaded=str(failure))
            return Named(
                paths=[each for file in files for each in holding(source, file)]
            )

    def fingerprint(self, zone: Zone) -> str:
        """Fingerprint the zone: git's listing of its files, and the `lup-dev` it runs.

        The listing names each file's path, mode and object, so any change to one
        of them, or a file joining or leaving the zone, changes it.
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
        digest = hashlib.sha256(listed.stdout)
        digest.update(zone.tool.model_dump_json().encode())
        return digest.hexdigest()

    def change(self, standing: Standing) -> Change:
        """Say what changed since the approved commit: git's diff over the zone.

        The paths the approval held, since its commit; the paths it didn't, whole.
        The first time, or where the repository doesn't hold the approved commit,
        every path whole.
        """
        git = Git(cwd=self.root)
        zone = standing.zone
        approval = standing.approval
        empty = git.run("hash-object", "-t", "tree", "--stdin", stdin=b"")
        nothing = empty.stdout.decode().strip()
        tool = zone.tool.said(approval.tool if approval is not None else None)
        held = approval is not None and (
            git.run(
                "cat-file", "-e", f"{approval.commit}^{{commit}}", ok=[0, 1, 128]
            ).exit_code
            == 0
        )
        if approval is None or not held:
            return Change(
                commit=zone.commit,
                approved=approval.commit if approval is not None else None,
                since=None,
                changed=diffed(git, nothing, zone.commit, zone.paths),
                joined=Diffed(),
                tool=tool,
                unloaded=zone.unloaded,
            )
        kept = [path for path in zone.paths if path in approval.paths]
        joined = [path for path in zone.paths if path not in approval.paths]
        return Change(
            commit=zone.commit,
            approved=approval.commit,
            since=approval.commit,
            changed=diffed(git, approval.commit, zone.commit, kept),
            joined=diffed(git, nothing, zone.commit, joined),
            tool=tool,
            unloaded=zone.unloaded,
        )

    def ensure(self) -> Outcome:
        """Check the tip's host zone; where it isn't the one approved, show and ask.

        Approved, the tip's copy is installed, the host service restarted on it
        where one runs, and the approval recorded. Declined, the copy approved
        before stays; with none approved, `TrustError`, since nothing approved may
        run. Inside an agent's session nothing is asked: `TrustError`. Launches at
        once ask one at a time, so the second reads the first's answer.
        """
        repository = self.repository()
        kept = self.layout.approved(repository)
        kept.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(kept.with_name(f"{kept.name}.lock")):
            standing = self.standing(repository)
            zone = standing.zone
            approval = standing.approval
            if approval is not None and standing.approved():
                return Unchanged(commit=zone.commit, approval=approval)
            if self.inside:
                message = (
                    f"this runs inside a {self.inside[0]} session, and an agent "
                    "doesn't approve the code the host runs: answer from your own "
                    "terminal"
                )
                raise TrustError(message)
            change = self.change(standing)
            self.asker.show(change.text())
            if not self.asker.ask(change.question()):
                if approval is None:
                    message = (
                        f"you declined the host zone at {zone.commit}, and none was "
                        "approved before, so there's no `lup-dev` the host may run: "
                        "nothing launches"
                    )
                    raise TrustError(message)
                return Kept(commit=zone.commit, approval=approval)
            self.toolchain.install(zone.tool, self.root, zone.commit)
            restarted = self.restart()
            approved = Approval(
                commit=zone.commit,
                fingerprint=standing.fingerprint,
                paths=zone.paths,
                tool=zone.tool,
                time=self.clock.now(),
            )
            write_model(kept, approved)
            return Trusted(approval=approved, restarted=restarted)

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


def trusted(root: Path, inside: list[str]) -> Outcome:
    """Check what the host runs for the repository at `root`: a launch's first step.

    As `Trust.ensure` does, with this machine's settings, the terminal, uv and the
    host service's client; `inside` names the runtimes whose session this runs
    inside. Raise `TrustError` where nothing approved may run.
    """
    settings = LupDevSettings()
    layout = Layout.of(settings)
    clock = SystemClock()
    trust = Trust(
        root=root,
        layout=layout,
        integration=settings.lup_integration_branch,
        asker=Terminal(),
        toolchain=UvToolchain(),
        host=HostClient(layout=layout.host, clock=clock, starter=Detached()),
        clock=clock,
        inside=inside,
    )
    return trust.ensure()
