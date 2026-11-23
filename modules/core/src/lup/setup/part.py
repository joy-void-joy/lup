"""`Setup`, the core's part setting a repository up for lup: `lup init` in one that exists, `lup new <name>` making one.

Both are lup's own program acting on the operator's machine, never a
project's code: they read nothing of the repository's declaration but whether
its file is there, and `lup` answers them in the process it's typed in, over
lup's default modules (`lup.environment.command_line.main`). They run git and
uv through the fields declaring them, so a promise stands each in, and refuse
with nothing written where either is missing (`README.md` here).
"""

import importlib.metadata
import importlib.util
import keyword
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import ValidationError

import lup
from lup.command_line.names import typed_methods
from lup.declaration.layout import RepositoryLayout
from lup.declaration.module import Module
from lup.doors.done import Done
from lup.doors.door import RefusedError
from lup.doors.parties import Operator
from lup.doors.parts import Checked, Finished, Part, Parts, Program
from lup.programs.git import Git
from lup.running.plan import CORE, typed
from lup.setup.skeleton import Skeleton, declared
from lup.types import Model
lazy from lup.hosting.module import Hosting

if TYPE_CHECKING:
    from lup.doors.door import Method


class Initializing(Model):
    """Where to set lup up: a repository that exists."""

    directory: Path = Path()
    """A directory in the repository's worktree, whose root lup is set up at:
    where `lup` is typed, unless given."""


class Making(Model):
    """A project to make, set up for lup, with a module of its own."""

    name: str
    """Its name: its directory's, made in `directory`, its own module's, and,
    each `-` a `_`, its package's; lowercase letters and digits, words joined
    by `-` (`ProjectName`), which the command holds it to."""
    directory: Path = Path()
    """Where its directory is made: where `lup` is typed, unless given."""


class Missing(Done):
    """A program lup's other parts run that isn't there, or not at a version they take."""

    line: ClassVar[str] = "{why}"
    name: str
    why: str
    """Why it can't be run, and how to install it."""


class Unregistered(Done):
    """Why the operator's lup wasn't told of the repository set up."""

    line: ClassVar[str] = "not registered with your lup: {why}"
    why: str


class SetUp(Done):
    """What setting a repository up for lup did."""

    line: ClassVar[str] = "set {root} up for lup"

    root: Path
    """The worktree's root."""
    declaration: Path
    """The declaration written."""
    ignored: bool
    """Whether the line ignoring the repository's local layer was added to
    `.gitignore`; false where a line there ignored it already."""
    dependency: str
    """The requirement the project depends on lup's core by, which uv added."""
    module: Path | None = None
    """The directory of the module of the project's own made, where one was."""
    missing: list[Missing] = []
    """The programs lup's other parts run that aren't there, or not at a
    version they take, each saying why and how to install it: none of them
    stops a project working on this machine, but each stops the part running
    it."""
    registered: bool = False
    """Whether the operator's lup was told of the repository, and lists it:
    `lup` tells it once the command has set the repository up, where it's
    typed (`lup.environment.setup`)."""
    unregistered: Unregistered | None = None
    """Why it wasn't, where `lup` tried."""


class Made(SetUp):
    """A project made, set up for lup, with a module of its own."""

    line: ClassVar[str] = "made {root}, set up for lup"


class VcsInfo(Model):
    """`vcs_info` in an installed distribution's `direct_url.json`: the commit it was installed from."""

    commit_id: str


class DirInfo(Model):
    """`dir_info` in an installed distribution's `direct_url.json`: a directory it was installed from."""

    editable: bool = False


class DirectUrl(Model):
    """An installed distribution's `direct_url.json` (PEP 610): where it was installed from, where that wasn't an index."""

    url: str
    vcs_info: VcsInfo | None = None
    dir_info: DirInfo | None = None


class Setup(Part):
    """Setting a repository up for lup: `lup init` and `lup new`, the operator's, run where they're typed."""

    module: Module
    git: Program = Program(
        name="git",
        optional=True,
        why="finds the repository lup sets up, and makes a new one's",
        install="https://git-scm.com/downloads",
    )
    """Optional, as uv is, so a project's container without them still starts
    its other parts: missing, this part isn't made, and `init` and `new` are
    refused, saying how to install it, before anything is written."""
    uv: Program = Program(
        name="uv",
        optional=True,
        why="adds lup's core to a project, and makes a new one's workspace",
        install="https://docs.astral.sh/uv/getting-started/installation/",
    )
    # lup: defer(issue=23, why="lup's core is pinned from GitHub, at the commit of the lup running `init`, until its releases are published to PyPI, when a project depends on a version of it")
    source: str = "https://github.com/joy-void-joy/lup"
    """The repository lup's core is pinned from, at the commit installed."""
    within: str = "modules/core"
    """The core's directory in that repository."""

    @lup.command
    async def init(self, initializing: Initializing, by: Operator) -> SetUp:
        """Set up the repository you're in for lup.

        It writes its declaration of lup's default modules and the gitignore
        line for its local layer, and adds lup's core as its dependency,
        through uv. Refuse where git or uv is missing, where the directory is in no git
        worktree, or where a declaration is there already, which it never
        overwrites: nothing is written then.
        """
        del by
        layout = await RepositoryLayout.found(initializing.directory, self.git)
        if layout is None:
            message = (
                f"{initializing.directory} is in no git worktree: `lup new <name>` "
                "makes a repository set up for lup"
            )
            raise RefusedError(message)
        if layout.declaration.exists():
            message = (
                f"{layout.declaration} is there already, and lup never overwrites a "
                "declaration"
            )
            raise RefusedError(message)
        return await self.prepared(layout, None)

    @lup.command
    async def new(self, making: Making, by: Operator) -> Made:
        """Make a project set up for lup, with a module of its own.

        Its directory, a git repository and a uv workspace, what `init` writes,
        and a module of its own, which its declaration selects. Refuse where git or uv is missing, where the directory is there
        already, or where the name would shadow a command of lup's or a
        package Python finds: nothing is written then. Where a step fails
        after, the directory it made is removed.
        """
        del by
        try:
            own = Skeleton(name=making.name, requires=self.requires())
        except ValidationError as unnamed:
            message = (
                f"`{making.name}` isn't a project's name: lowercase letters and "
                "digits, words joined by `-`, starting with a letter"
            )
            raise RefusedError(message) from unnamed
        self.named(own)
        root = (making.directory / making.name).absolute()
        if root.exists():
            message = f"{root} is there already: `lup init` sets up a repository there"
            raise RefusedError(message)
        root.mkdir(parents=True)
        kept = False
        try:
            done = await self.built(root, own)
            kept = True
        finally:
            if not kept:
                shutil.rmtree(root, ignore_errors=True)
        return done

    async def built(self, root: Path, own: Skeleton) -> Made:
        """Make the project at `root`, its directory made, with `own` as its module."""
        await Git.initialised(root, self.git)
        self.succeeded(
            await self.uv.ran(
                "--directory",
                str(root),
                "init",
                "--bare",
                "--no-workspace",
                f"--name={own.name}-workspace",
                f"--python={own.requires}",
            ),
            "uv init",
        )
        for path, text in own.files().items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        (root / ".gitignore").write_text(".venv/\n__pycache__/\n")
        done = await self.prepared(RepositoryLayout(root=root, main=root), own)
        member = await self.added(root, "--workspace", f"./{own.directory()}")
        self.succeeded(member, "uv add")
        # lup: defer(issue=14, why="lup's harness imports the dashboard's server, so checking promises takes the `dashboard` extra beside `environment`, which says it's what checking promises needs, until the harness imports it only where a promise opens a dashboard")
        checking = await self.added(
            root, "--dev", "pytest", "lup-core[environment,dashboard]"
        )
        self.succeeded(checking, "uv add")
        return Made.model_validate(
            {**done.model_dump(), "module": root / own.directory()}
        )

    async def prepared(self, layout: RepositoryLayout, own: Skeleton | None) -> SetUp:
        """Write what `init` writes in `layout`'s worktree: lup's core as its dependency, first, where uv can refuse it, then its declaration, selecting `own` where given, and the line ignoring its local layer."""
        root = layout.root
        dependency = await self.pinned()
        begun = False
        if not layout.pyproject.exists():
            self.succeeded(
                await self.uv.ran(
                    "--directory",
                    str(root),
                    "init",
                    "--bare",
                    "--no-workspace",
                    f"--python={self.requires()}",
                ),
                "uv init",
            )
            begun = True
        added = await self.added(root, dependency)
        if added.status != 0:
            if begun:
                layout.pyproject.unlink(missing_ok=True)
            self.succeeded(added, "uv add")
        layout.declaration.write_text(declared(own))
        ignoring = f"/{layout.local.name}"
        ignore = root / ".gitignore"
        kept = ignore.read_text() if ignore.exists() else ""
        lines = [each.strip() for each in kept.splitlines()]
        ignored = ignoring not in lines and layout.local.name not in lines
        if ignored:
            ended = kept if not kept or kept.endswith("\n") else f"{kept}\n"
            ignore.write_text(f"{ended}{ignoring}\n")
        return SetUp(
            root=root,
            declaration=layout.declaration,
            ignored=ignored,
            dependency=dependency,
            missing=[
                Missing(name=each.name, why=each.why) for each in await self.wanting()
            ],
        )

    async def added(self, root: Path, *words: str) -> Finished:
        """Run `uv add` with `words` in the project at `root`, locking what it adds and syncing no environment.

        uv would otherwise sync the environment `UV_PROJECT_ENVIRONMENT`
        names, which, where `lup` itself runs under `uv run`, is the one it runs
        in, not the project's: the project's first `uv run` syncs its own.
        """
        return await self.uv.ran("--directory", str(root), "add", "--no-sync", *words)

    async def wanting(self) -> list[Checked]:
        """Check the programs lup's shipped parts run, the core's and the machine's, beyond git and uv, where this part runs, and list those that aren't there or aren't at a version their part takes: podman, which runs a project's parts in containers, among them."""
        declared = {
            program.name: program
            for module in [self.module, Hosting()]
            for part in module.held(Parts)
            for program in part.programs().values()
            if program.name not in (self.git.name, self.uv.name)
        }
        runs = self.git.runs
        checked = [
            await each.model_copy(update={"runs": runs}).checked()
            for each in declared.values()
        ]
        return [each for each in checked if not each.fits]

    def named(self, own: Skeleton) -> None:
        """Refuse a name the project's module can't take: the core's, one `lup` types a command of the core's by, or one whose package Python finds already, which it would shadow."""
        taken: dict[str, Method] = typed_methods(self.module)
        package = own.package()
        if own.name == CORE or typed(own.name) in taken:
            message = (
                f"`{own.name}` is typed as one of lup's own commands, so `lup` "
                "couldn't type the module of that name: name the project otherwise"
            )
            raise RefusedError(message)
        if keyword.iskeyword(package) or importlib.util.find_spec(package):
            message = (
                f"`{package}` is a name Python has already, which the project's "
                "package would shadow: name the project otherwise"
            )
            raise RefusedError(message)

    def requires(self) -> str:
        """Return the Python versions lup's core runs on, as its distribution says: those a project depending on it runs on."""
        return importlib.metadata.metadata("lup-core").get("Requires-Python") or ""

    async def pinned(self) -> str:
        """Return the requirement a project depends on lup's core by: the core from GitHub, at the commit of the lup running this.

        An install from git says its commit; one from a directory, as lup's
        own workspace installs it, is a checkout whose `HEAD` git gives.
        Raise `RefusedError` where it's neither, which says no commit.
        """
        found = importlib.metadata.distribution("lup-core").read_text("direct_url.json")
        try:
            installed = DirectUrl.model_validate_json(found or "")
        except ValidationError as unsaid:
            message = (
                "lup's core was installed from an index, which says no commit to "
                "pin it at, until its releases are published (#23)"
            )
            raise RefusedError(message) from unsaid
        if installed.vcs_info is not None:
            commit = installed.vcs_info.commit_id
        else:
            checkout = Path.from_uri(installed.url)
            worktree = await Git.located(checkout, self.git)
            head = None if worktree is None else await worktree.head()
            if head is None:
                message = (
                    f"lup's core was installed from {checkout}, which holds no "
                    "commit to pin it at"
                )
                raise RefusedError(message)
            commit = head
        return f"lup-core @ git+{self.source}@{commit}#subdirectory={self.within}"

    def succeeded(self, finished: Finished, ran: str) -> None:
        """Refuse, quoting what it said, where the program run as `ran` failed."""
        if finished.status != 0:
            message = f"`{ran}` failed: {finished.said()}"
            raise RefusedError(message)
