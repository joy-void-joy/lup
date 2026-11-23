"""`Projects`: the machine's part running each project, from planning its declaration to starting the containers its plan says.

A project runs the commit the operator approved last (`Approvals`), written
out from git's objects (`Trees`), and nothing before their first approval.
Opening it plans its declaration in a container, which prints the plan, then
starts its containers from the plan, in place of those it ran before: one for
every part holding nothing, and one for each part holding something that isn't
the whole machine's, given only the secrets it holds. Each container's
directory of sockets comes from `Carrying`, which is told where each part runs
(`README.md` here, *Projects*).

A project's Python environment is made in its container, as rooms make theirs:
the machine's own uv-managed interpreters mounted read-only, nothing fetched,
and each container's environment, uv's cache and its parts' data kept in
directories of that container's own under this part's data, so it starts on
what it synced and kept before, and code running in one container never writes
what another imports or reads what another keeps.
"""

import os
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

from pydantic import Field, TypeAdapter, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

import lup
from lup.command_line.filled import Common, Repository
from lup.doors.done import Done
from lup.doors.door import RefusedError
from lup.doors.events import Stopping
from lup.doors.parties import Agent, Machine, Operator
from lup.doors.parts import Data, Part, Program, Runtime, SshAgent
from lup.errors import LupError
from lup.hosting.approvals import Approvals, Asking
from lup.hosting.carrying import Carrying, Naming, Placement, Placing
from lup.hosting.containers import (
    Bind,
    Clearing,
    ContainerError,
    Containers,
    Image,
    Named,
    Once,
    Spec,
)
from lup.hosting.logins import Borrowing, Logins
from lup.hosting.secrets import Holding, Secrets
from lup.hosting.settings import Lending
from lup.hosting.trees import Commit, Exporting, Trees
from lup.running.plan import Name, PartPlan, Plan
from lup.running.wire import Planning, Rendering, Start, read
from lup.shell.blocks import Blocks, Fold, Line, Span
from lup.told.guidance import Guidance
from lup.types import Model

PLANS = TypeAdapter[Plan](Plan)


class Opening(Model):
    """A project to run: its repository, as lup names it, where git keeps it, and its declaration."""

    repository: Repository
    common: Common
    """Its common git directory on the machine, which the commit approved is
    written out from."""
    declaration: Path = Path("lup_project.py")
    """Its declaration, relative to its root."""


class Source(Model):
    """A project's commit as its containers run it: written out on the machine, mounted read-only at the same path, and where the machine's uv keeps its interpreters."""

    opening: Opening
    commit: Commit
    root: Path
    """The commit's files, written out."""
    interpreters: Path
    """Where the machine's uv keeps its Python interpreters, mounted read-only
    at this path, which an environment's links name, so a container runs the
    Python the project asks for without fetching one."""


class Opened(Model):
    """A project running: the commit it runs, its plan, and the containers started for it."""

    repository: str
    commit: Commit
    plan: Plan
    root: Path
    """The commit's files, written out, which its containers mount."""
    containers: list[str] = []
    waiting: list[str] = []
    """Parts holding a secret nothing's kept yet, by `module.Part`, not
    started until the operator gives it."""
    unlent: dict[str, str] = {}
    """Parts holding what the machine couldn't lend them of the operator's (their
    GitHub login, their SSH agent), by `module.Part`, with why: not started
    until the project opens again."""


class Lent(Model):
    """What the machine lends one part of a project as its container starts: the secrets it holds and the operator's GitHub login, by their fields' names, the operator's SSH agent, and the project's git directory, each on the machine."""

    secrets: dict[str, str] = Field(default={}, repr=False)
    ssh: SshAgent | None = None
    git: Path | None = None
    unlent: str | None = None
    """Why the machine couldn't lend it what it holds of the operator's, which
    keeps it waiting; none where it lends it all."""


OPENINGS = TypeAdapter(dict[str, Opening])


class Locating(Model):
    """A project, by its repository, as lup names it."""

    repository: str


class Located(Model):
    """Where a project running is, and what it runs: where git keeps it, the commit approved, its files written out, and its plan."""

    opening: Opening
    opened: Opened


class Telling(Model):
    """A session of a project, whose guidance at its start is asked for: the project, and the session's own agent."""

    repository: str
    agent: Agent


class Sharing(Model):
    """The parts one for the whole machine that don't hold it, to start each in a container of its own: the home repository, its tree and declaration as the machine runs them, the machine's own Python environment, where the machine keeps its parts' data, and the home repository's plan."""

    repository: Name
    root: Path
    """The home repository's tree the machine runs, mounted read-only."""
    declaration: Path
    """Its declaration, relative to the root."""
    environment: Path
    """The Python environment the machine runs in, mounted read-only: a part
    one for the whole machine runs the machine's own code, approved."""
    paths: list[Path] = []
    """Every directory the machine imports its code from beyond the
    environment, mounted read-only at its own path: a source tree an editable
    install points at, as a workspace's environment's do."""
    data: Path
    """Where the machine keeps its parts' data: each part's own directory
    there is mounted at its own path, so it keeps what it kept before."""
    plan: Plan


class Shared(Model):
    """The containers running the parts one for the whole machine that don't hold it, by name; and those waiting for a secret nothing's kept yet."""

    containers: list[str] = []
    waiting: list[str] = []
    failed: dict[str, str] = {}
    """Each part whose container didn't come up listening, by `module.Part`,
    and why."""


class Statusing(Model):
    """Asking what the machine runs, giving nothing."""


class Registered(Done):
    """A project registered with the operator's lup."""

    line: ClassVar[str] = "registered {repository}"
    repository: str


class PartWaiting(Done):
    """A part of a project not started, and what it waits on."""

    line: ClassVar[str] = "{part} waits on {why}"
    part: str
    """The part, `module.Part`."""
    why: str


class ProjectOpened(Done):
    """A project running at the commit approved last, and what of it waits."""

    line: ClassVar[str] = "opened {repository} at {commit:.12}, {containers} containers"
    repository: str
    commit: Commit
    containers: int
    """How many containers it runs."""
    waiting: list[PartWaiting] = []


class Resuming(Model):
    """Asking to open again each project the machine's parts ran before they last stopped, giving nothing."""


class Resumed(Model):
    """Each project opened again, and each refused, with why."""

    opened: list[str] = []
    refused: dict[str, str] = {}


class Base(Model):
    """The image every project's containers start from: Arch Linux's, pinned with the day of its archive its packages come from, with git and uv.

    The archive answers slowly at times, so pacman waits on it as long as it
    takes, rather than giving up past its ten seconds.
    """

    image: str = (
        "docker.io/library/archlinux:base-20260816.0.574111"
        "@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a"
    )
    archive: str = "https://archive.archlinux.org/repos/2026/08/15/$repo/os/$arch"
    packages: list[str] = ["git", "uv"]

    def definition(self, added: list[str] | None = None) -> str:
        """Return its Containerfile, with the packages in `added` beside its own: those the programs of the parts a container runs are in."""
        extra: list[str] = [] if added is None else added
        packages = [
            *self.packages,
            *dict.fromkeys(each for each in extra if each not in self.packages),
        ]
        steps = [
            f"echo 'Server = {self.archive}' > /etc/pacman.d/mirrorlist",
            "pacman -Syu --noconfirm --needed --disable-download-timeout -- "
            + " ".join(packages),
            "rm -rf /var/cache/pacman/pkg/*",
        ]
        return f"FROM {self.image}\nRUN " + " \\\n    && ".join(steps) + "\n"


class Projects(Part, machine=True, shared=True):
    """The machine's part running each project: planning its declaration in a container, and starting the containers its plan says."""

    places: Data
    """Each container's Python environment, uv cache and parts' data, a
    directory each, by the container's name."""
    registry: Data
    """Each project registered or opened, kept so the machine's parts open it
    again as they start."""
    outputs: Runtime
    """What each container prints, a file each, in memory, capped in size."""
    uv: Program = Program(
        name="uv",
        optional=True,
        why="says where the machine keeps Python, which a project's containers run",
        install="https://docs.astral.sh/uv/getting-started/installation/",
    )
    base: Base = Field(default_factory=Base)
    projects: dict[str, Opened] = {}
    """Each project running, by its repository."""
    machinewides: Shared = Field(default_factory=Shared)
    """The containers running the parts one for the whole machine that don't
    hold it."""
    unopened: dict[str, str] = {}
    """Why each project registered isn't open, by its repository, where
    opening it was refused, as the operator's `status` says."""
    ready: timedelta = timedelta(minutes=1)
    """How long a container of a part one for the whole machine may take to
    listen on its socket, past which it's stopped and said to have failed: it
    runs the machine's own environment, with nothing to sync, so it listens
    in seconds."""
    pace: timedelta = timedelta(seconds=0.5)
    """How often such a container is looked at for its socket, as it starts."""
    generation: int = 0
    """How many times a project was opened since the machine's parts started:
    each opening's containers are named with it, so they start beside those
    they replace."""

    def container(self, source: Source, part: PartPlan | None) -> str:
        """Return the name of the container of this opening running `part`, or the project's own for its parts holding nothing."""
        return f"{self.role(source, part)}-{self.generation}"

    def role(self, source: Source, part: PartPlan | None) -> str:
        """Return the name of what a container of the project runs, the same from one opening to the next, which its environment, cache and data are kept under: the project's own container, or one part's."""
        repository = source.opening.repository
        if part is None:
            return f"lup-{repository}-project"
        return f"lup-{repository}-{part.module}-{part.part}"

    def image(self, repository: str, added: list[str] | None = None) -> Image:
        """Return the image a project's containers run, with the packages in `added`, those of the parts one runs: an image of its own for each list, built once."""
        return Image(
            base=self.base.image,
            definition=self.base.definition(added),
            project=repository,
        )

    def spec(self, source: Source, name: str, role: str, sockets: Path | None) -> Spec:
        """Return a container named `name` of the project running the program a container runs, its commit's files read-only, uv's cache and its parts' data kept under `role`, from one opening to the next, and its environment under `role` for the commit it runs, so a container starting never changes what one still running imports."""
        opening = source.opening
        environment = self.places.path / role / "environments" / source.commit
        cache = self.places.path / role / "cache"
        data = self.places.path / role / "data"
        for each in [environment, cache, data]:
            each.mkdir(parents=True, exist_ok=True)
        binds = [
            Bind(source=source.root),
            Bind(source=source.interpreters.resolve(), target=source.interpreters),
            Bind(
                source=environment, target=Path("/var/lup/environment"), read_only=False
            ),
            Bind(source=cache, target=Path("/var/lup/cache"), read_only=False),
            Bind(source=data, target=Path("/var/lup/data"), read_only=False),
            *(
                []
                if sockets is None
                else [Bind(source=sockets, target=Path("/run/lup"), read_only=False)]
            ),
        ]
        return Spec(
            name=name,
            image=self.image(opening.repository),
            command=[
                "uv",
                "run",
                "--frozen",
                "--project",
                str(source.root),
                "python",
                "-m",
                "lup.environment.running",
            ],
            workdir=source.root,
            binds=binds,
            env={
                "UV_PROJECT_ENVIRONMENT": "/var/lup/environment",
                "UV_CACHE_DIR": "/var/lup/cache",
                "UV_PYTHON_DOWNLOADS": "never",
                "UV_PYTHON_INSTALL_DIR": str(source.interpreters),
            },
        )

    @lup.service
    async def machinewide(self, sharing: Sharing, by: Machine) -> Shared:
        """Start each part one for the whole machine that doesn't hold the machine in a container of its own, from the machine's own code, holding only what it declares, in place of those started before: as the machine's parts start.

        A part holding a secret nothing's kept for the home repository waits,
        not started. Raise `RefusedError` where a container doesn't start.
        """
        del by
        for name in self.machinewides.containers:
            await Containers.stopped(Named(name=name))
        parts = [
            each
            for each in sharing.plan.parts
            if each.holds.shared and not each.holds.machine
        ]
        if not parts:
            self.machinewides = Shared()
            await Carrying.sharing(
                Placing(repository=sharing.repository, plan=sharing.plan, placements=[])
            )
            return self.machinewides
        await Containers.built(self.image(sharing.repository))
        found = await self.uv.ran("python", "dir")
        if found.status != 0:
            message = f"uv couldn't say where it keeps Python: {found.said()}"
            raise RefusedError(message)
        interpreters = Path(found.text().strip())
        held = {
            each.named(): await Secrets.held(
                Holding(project=sharing.repository, names=each.holds.secrets)
            )
            for each in parts
        }
        waiting = [name for name, values in held.items() if values.missing]
        self.generation += 1
        placements = [
            await self.shared_at(sharing, each, interpreters, held[each.named()].values)
            for each in parts
            if each.named() not in waiting
        ]
        failed = {
            name: why
            for each in placements
            for name in each.parts
            if (why := await self.unready(each)) is not None
        }
        listening = [
            each
            for each in placements
            if not any(name in failed for name in each.parts)
        ]
        await Carrying.sharing(
            Placing(
                repository=sharing.repository, plan=sharing.plan, placements=listening
            )
        )
        self.machinewides = Shared(
            containers=[each.container for each in listening],
            waiting=waiting,
            failed=failed,
        )
        return self.machinewides

    async def unready(self, placement: Placement) -> str | None:
        """Wait for the container of `placement` to listen on its socket, `ready` at most, and say why it isn't where it doesn't, it stopped then; none where it listens."""
        socket = placement.listening()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(int(self.ready / self.pace)),
                wait=wait_fixed(self.pace.total_seconds()),
                retry=retry_if_exception_type(FileNotFoundError),
                reraise=True,
            ):
                with attempt:
                    socket.lstat()
        except FileNotFoundError:
            alive = (await Containers.alive(Clearing())).names
            state = (
                "is running and doesn't listen"
                if placement.container in alive
                else "ended as it started"
            )
            await Containers.stopped(Named(name=placement.container))
            return (
                f"its container {placement.container} {state} within {self.ready}: "
                f"what it printed is in {self.output(placement.container)}"
            )
        return None

    async def shared_at(
        self,
        sharing: Sharing,
        part: PartPlan,
        interpreters: Path,
        secrets: dict[str, str],
    ) -> Placement:
        """Start the container of the part one for the whole machine `part`, from the machine's own environment, read-only, its data the directory it kept on the machine, and return where it runs."""
        name = f"lup-machine-{part.module}-{part.part}-{self.generation}"
        directory = await Carrying.directory(Naming(container=name))
        start = Start(
            root=sharing.root,
            declaration=sharing.declaration,
            repository=sharing.repository,
            parts=[part.named()],
            listening=Path("/run/lup/listening.sock"),
            calling=Path("/run/lup/calling.sock"),
            secrets=None if not secrets else Path("/run/lup/secrets"),
            data=sharing.data,
            runtime=Path("/run/lup/runtime"),
        )
        if secrets:
            kept = directory.path / "secrets"
            kept.mkdir(mode=0o700, exist_ok=True)
            for each, value in secrets.items():
                file = kept / each
                file.touch(mode=0o600)
                file.write_text(value)
        await Containers.built(self.image(sharing.repository, part.packages))
        spec = self.shared_spec(sharing, part, name, interpreters, directory.path)
        spec = spec.model_copy(
            update={"env": {**spec.env, "LUP_ASKED": start.model_dump_json()}}
        )
        await Containers.started(spec)
        return Placement(
            repository=sharing.repository,
            parts=[part.named()],
            container=name,
            directory=directory.path,
        )

    def shared_spec(
        self,
        sharing: Sharing,
        part: PartPlan,
        name: str,
        interpreters: Path,
        sockets: Path,
    ) -> Spec:
        """Return the container named `name` of the part one for the whole machine `part`: the machine's tree, environment and interpreters read-only at their own paths, its data the directory it kept on the machine, its sockets in memory.

        Its Python runs isolated (`-I`), from `/`, so no tree it starts in,
        the installed `lup`'s `lup/hosting/` among them, is searched for
        modules: there, `secrets.py` would stand in for the standard
        library's, and the part would end as it starts. Every directory the
        machine imports its code from is mounted beside its environment, a
        source tree an editable install points at among them, so `lup` is
        whole there.
        """
        data = sharing.data / part.named()
        data.mkdir(parents=True, exist_ok=True)
        imported = [
            Bind(source=each.resolve(), target=each)
            for each in dict.fromkeys(sharing.paths)
            if each not in [sharing.root, sharing.environment, interpreters]
        ]
        return Spec(
            name=name,
            image=self.image(sharing.repository, part.packages),
            command=[
                str(sharing.environment / "bin" / "python"),
                "-I",
                "-m",
                "lup.environment.running",
            ],
            workdir=Path("/"),
            binds=[
                Bind(source=sharing.root.resolve(), target=sharing.root),
                Bind(source=sharing.environment.resolve(), target=sharing.environment),
                Bind(source=interpreters.resolve(), target=interpreters),
                *imported,
                Bind(source=data.resolve(), target=data, read_only=False),
                Bind(source=sockets, target=Path("/run/lup"), read_only=False),
            ],
            output=self.output(name),
        )

    @lup.service
    async def located(self, locating: Locating, by: Machine) -> Located:
        """Say where a project running is and what it runs, for a session of it to start.

        Raise `RefusedError` where it isn't running.
        """
        del by
        opened = self.projects.get(locating.repository)
        opening = self.kept().get(locating.repository)
        if opened is None or opening is None:
            message = (
                f"{locating.repository} isn't running: open it first, which runs "
                "the commit you approved last (`lup machine open`)"
            )
            raise RefusedError(message)
        return Located(opening=opening, opened=opened)

    @lup.service
    async def guided(self, telling: Telling, by: Machine) -> Guidance:
        """Render what a session of a project running is told at its start, its declaration at the commit it runs loaded in a container, run to its end, which prints it.

        Raise `RefusedError` where it isn't running, or its guidance doesn't
        render.
        """
        located = await self.located(Locating(repository=telling.repository), by)
        found = await self.uv.ran("python", "dir")
        if found.status != 0:
            message = f"uv couldn't say where it keeps Python: {found.said()}"
            raise RefusedError(message)
        source = Source(
            opening=located.opening,
            commit=located.opened.commit,
            root=located.opened.root,
            interpreters=Path(found.text().strip()),
        )
        asked = Rendering(
            root=source.root,
            declaration=located.opening.declaration,
            agent=telling.agent,
        )
        name = f"lup-told-{telling.repository}"
        finished = await Containers.ran(
            Once(
                spec=self.spec(source, name, name, None),
                given=asked.model_dump_json(),
            )
        )
        if finished.status != 0:
            message = (
                f"{telling.repository}'s guidance didn't render: {finished.said()}"
            )
            raise RefusedError(message)
        try:
            return Guidance.model_validate_json(finished.output)
        except ValidationError as wrong:
            message = f"{telling.repository}'s guidance isn't one lup reads: {wrong}"
            raise RefusedError(message) from wrong

    @lup.command
    async def register(self, opening: Opening, by: Operator) -> Registered:
        """Register a project with your lup.

        Your lup lists it, and opens it once you approve a commit of it. Refuse
        a repository's name another project registered already.
        """
        del by
        self.kept_with(opening)
        return Registered(repository=opening.repository)

    def kept_with(self, opening: Opening) -> None:
        """Keep `opening` among the projects opened, in place of what it kept for its repository.

        Raise `RefusedError` where another project, at another git directory,
        holds its repository's name.
        """
        kept = self.kept()
        before = kept.get(opening.repository)
        if before is not None and before.common != opening.common:
            message = (
                f"{opening.repository} is the name of the project at {before.common} "
                "already: lup names each project once"
            )
            raise RefusedError(message)
        kept = {**kept, opening.repository: opening}
        (self.registry.path / "openings.json").write_bytes(OPENINGS.dump_json(kept))

    @lup.command
    async def open(self, opening: Opening, by: Operator) -> ProjectOpened:
        """Run a project, at the commit you approved last.

        Plan its declaration, and start the containers its plan says.
        """
        del by
        opened = await self.opening(opening)
        return ProjectOpened(
            repository=opened.repository,
            commit=opened.commit,
            containers=len(opened.containers),
            waiting=[
                *(PartWaiting(part=name, why="a secret") for name in opened.waiting),
                *(
                    PartWaiting(part=name, why=why)
                    for name, why in opened.unlent.items()
                ),
            ],
        )

    @lup.service
    async def resumed(self, resuming: Resuming, by: Machine) -> Resumed:
        """Open again each project the machine's parts ran before they last stopped, at the commit approved last: as the machine's parts start, once they've stopped every container a machine before them left (`Containers.cleared`).

        A project that can't open is said with why, and the others open.
        """
        del resuming, by
        kept = self.kept()
        if not kept:
            return Resumed()
        opened: list[str] = []
        refused: dict[str, str] = {}
        for repository, opening in kept.items():
            try:
                await self.opening(opening)
            except RefusedError as unopened:
                refused = {**refused, repository: str(unopened)}
            else:
                opened = [*opened, repository]
        self.unopened = {**self.unopened, **refused}
        return Resumed(opened=opened, refused=refused)

    @lup.on(Stopping)
    async def closed(self, stopping: Stopping) -> None:
        """Stop each container of each project running, and of each part one for the whole machine, as the machine's parts stop: nothing would route calls to it.

        Each is asked to stop, whichever another failed to; raise
        `ContainerError` naming each that didn't.
        """
        del stopping
        names = [
            *(name for opened in self.projects.values() for name in opened.containers),
            *self.machinewides.containers,
        ]
        refusals: list[str] = []
        for name in names:
            try:
                await Containers.stopped(Named(name=name))
            except RefusedError as refused:
                refusals = [*refusals, str(refused)]
        self.projects = {}
        self.machinewides = Shared()
        if refusals:
            raise ContainerError("; ".join(refusals))

    @lup.view
    async def status(self, asking: Statusing, by: Operator) -> Blocks:
        """Show what the machine runs, a line each.

        The containers of its parts one for the whole machine, then each
        project open, the commit it runs, each of its containers, whether it's
        running and where what it prints goes, and the parts waiting for a
        secret or what the machine couldn't lend them; and each project
        registered that isn't open, with why where opening it was refused.
        """
        del asking, by
        shared = self.machinewides
        alive = (
            (await Containers.alive(Clearing())).names
            if self.projects or shared.containers
            else []
        )

        def container(name: str) -> Line:
            running = name in alive
            return Line(
                id=name,
                spans=[
                    Span(text=name),
                    Span(
                        text=" running" if running else " ended",
                        tone="up" if running else "down",
                    ),
                    Span(text=f"  {self.output(name)}", tone="muted"),
                ],
            )

        def waits(part: str, why: str) -> Line:
            return Line(
                id=f"waiting-{part}",
                spans=[Span(text=part), Span(text=f" waits on {why}", tone="waiting")],
            )

        machine = (
            [
                Fold(
                    id="machine",
                    kind="project",
                    summary=[Span(text="the machine's own parts", tone="strong")],
                    content=[
                        *(container(name) for name in shared.containers),
                        *(waits(part, "a secret") for part in shared.waiting),
                        *(
                            Line(
                                id=f"failed-{part}",
                                spans=[
                                    Span(text=part),
                                    Span(text=f" didn't come up: {why}", tone="down"),
                                ],
                            )
                            for part, why in shared.failed.items()
                        ),
                    ],
                )
            ]
            if shared.containers or shared.waiting or shared.failed
            else []
        )
        running = [
            Fold(
                id=f"project-{each.repository}",
                kind="project",
                summary=[
                    Span(text=each.repository, tone="strong"),
                    Span(text=f" runs {each.commit}", tone="muted"),
                ],
                content=[
                    *(container(name) for name in each.containers),
                    *(waits(part, "a secret") for part in each.waiting),
                    *(waits(part, why) for part, why in each.unlent.items()),
                ],
            )
            for each in self.projects.values()
        ]
        closed = [
            Line(
                id=f"project-{repository}",
                spans=[
                    Span(text=repository, tone="strong"),
                    Span(text=" registered, not open", tone="muted"),
                    *(
                        [
                            Span(
                                text=f": opening it was refused, {self.unopened[repository]}",
                                tone="down",
                            )
                        ]
                        if repository in self.unopened
                        else []
                    ),
                ],
            )
            for repository in self.kept()
            if repository not in self.projects
        ]
        shown = [*machine, *running, *closed]
        return Blocks.of(
            *(shown or [Line.of("nothing", "nothing is registered or open", "muted")])
        )

    def output(self, container: str) -> Path:
        """Return the file what the container named `container` prints goes to, in memory, which no container mounts."""
        return self.outputs.path / f"{container}.log"

    def kept(self) -> dict[str, Opening]:
        """Return each project opened, by its repository, as kept."""
        file = self.registry.path / "openings.json"
        if not file.exists():
            return {}
        return OPENINGS.validate_json(file.read_bytes())

    @lup.service
    async def registered(self, asking: Asking, by: Machine) -> Opening:
        """Return the project registered under a repository's name: where git keeps it, and its declaration.

        Raise `RefusedError` where no project is registered under it.
        """
        del by
        found = self.kept().get(asking.project)
        if found is None:
            message = f"no project named {asking.project} is registered with lup"
            raise RefusedError(message, about=[asking.project])
        return found

    @lup.service
    async def opened(self, opening: Opening, by: Machine) -> Opened:
        """Run a project at the commit the operator approved last: plan its declaration, and start its containers, in place of those it ran before.

        Raise `RefusedError` where nothing of it is approved yet, its commit
        can't be written out, its declaration doesn't plan, or podman fails.
        """
        del by
        return await self.opening(opening)

    async def opening(self, opening: Opening) -> Opened:
        """Open a project as `opened_at` does, keeping why where it's refused, for the operator's `status` to say.

        Raise `RefusedError` where it's refused.
        """
        try:
            opened = await self.opened_at(opening)
        except RefusedError as unopened:
            self.unopened = {**self.unopened, opening.repository: str(unopened)}
            raise
        self.unopened = {
            repository: why
            for repository, why in self.unopened.items()
            if repository != opening.repository
        }
        return opened

    async def opened_at(self, opening: Opening) -> Opened:
        """Run a project at the commit the operator approved last: plan it, and start one container for its parts holding nothing, and one for each part holding something that isn't the machine's, given only the secrets it holds, unless one isn't kept.

        A restart cuts no call: this opening's containers start beside those
        the project runs, calls are routed to them, and only then are those
        stopped, each finishing the calls it's answering. Where one of this
        opening's containers doesn't start, those that did are stopped, and
        the project runs on as it did. Raise `RefusedError` where nothing of
        it is approved yet, or a container doesn't start.
        """
        # lup: defer(issue=3, why="the opt-out where a project's parts holding nothing follow its running branch unapproved, from a tree of their own, their data apart")
        approved = await Approvals.approval(Asking(project=opening.repository))
        if approved.commit is None:
            message = (
                f"nothing of {opening.repository} is approved to run yet: lup asks "
                "the operator before its first run"
            )
            raise RefusedError(message)
        exported = await Trees.exported(
            Exporting(
                repository=opening.repository,
                common=opening.common,
                commit=approved.commit,
            )
        )
        found = await self.uv.ran("python", "dir")
        if found.status != 0:
            message = f"uv couldn't say where it keeps Python: {found.said()}"
            raise RefusedError(message)
        source = Source(
            opening=opening,
            commit=approved.commit,
            root=exported.path,
            interpreters=Path(found.text().strip()),
        )
        await Containers.built(self.image(opening.repository))
        plan = await self.planned(source)
        apart = [
            each
            for each in plan.apart()
            if not (each.holds.machine or each.holds.shared)
        ]
        held = {
            each.named(): await Secrets.held(
                Holding(project=opening.repository, names=each.holds.secrets)
            )
            for each in apart
        }
        waiting = [name for name, values in held.items() if values.missing]
        lent = {
            each.named(): await self.lent(opening, each, held[each.named()].values)
            for each in apart
            if each.named() not in waiting
        }
        unlent = {
            name: each.unlent for name, each in lent.items() if each.unlent is not None
        }
        together = [each.named() for each in plan.together()]
        running = [
            each
            for each in apart
            if each.named() in lent and each.named() not in unlent
        ]
        self.generation += 1
        named = [
            *([self.container(source, None)] if together else []),
            *(self.container(source, each) for each in running),
        ]
        try:
            placements = [
                *(
                    [await self.placed(source, None, together, plan.together())]
                    if together
                    else []
                ),
                *[
                    await self.placed(
                        source, each, [each.named()], [each], lent[each.named()]
                    )
                    for each in running
                ],
            ]
        except RefusedError:
            for name in named:
                await Containers.stopped(Named(name=name))
            raise
        await Carrying.placed(
            Placing(repository=opening.repository, plan=plan, placements=placements)
        )
        before = self.projects.get(opening.repository)
        for name in [] if before is None else before.containers:
            await Containers.stopped(Named(name=name))
        opened = Opened(
            repository=opening.repository,
            commit=approved.commit,
            plan=plan,
            root=source.root,
            containers=[each.container for each in placements],
            waiting=waiting,
            unlent=unlent,
        )
        self.projects = {**self.projects, opening.repository: opened}
        self.kept_with(opening)
        return opened

    async def planned(self, source: Source) -> Plan:
        """Plan the project's declaration in a container, and read the plan it prints.

        Raise `RefusedError` where it doesn't plan.
        """
        opening = source.opening
        asked = Planning(root=source.root, declaration=opening.declaration)
        name = f"lup-plan-{opening.repository}"
        finished = await Containers.ran(
            Once(
                spec=self.spec(source, name, name, None),
                given=asked.model_dump_json(),
            )
        )
        if finished.status != 0:
            message = (
                f"{opening.repository}'s declaration didn't plan: {finished.said()}"
            )
            raise RefusedError(message)
        try:
            plan = read(finished.output, PLANS)
        except (LupError, ValidationError) as wrong:
            message = f"{opening.repository}'s plan isn't one lup runs: {wrong}"
            raise RefusedError(message) from wrong
        ties = plan.ties()
        if ties:
            message = (
                f"{opening.repository}'s declaration serves {', '.join(ties)} "
                "from two parts each: lup routes a call to one part only"
            )
            raise RefusedError(message)
        shadowed = plan.shadowed()
        if shadowed:
            message = (
                f"{opening.repository}'s declaration names a module "
                f"{', '.join(f'`{each}`' for each in shadowed)}, as the core's tools, "
                "commands and views are typed at `lup`'s top level"
            )
            raise RefusedError(message)
        return plan

    async def lent(
        self, opening: Opening, part: PartPlan, secrets: dict[str, str]
    ) -> Lent:
        """Return what the machine lends `part` of the operator's as its container starts, beside `secrets`, those it holds: the operator's GitHub login, read with `gh auth token`, their SSH agent, as the machine's `SSH_AUTH_SOCK` names it, and the project's git directory; or why it can't, which keeps the part waiting."""
        logins: dict[str, str] = {}
        if part.holds.github:
            try:
                login = await Logins.github(Borrowing())
            except RefusedError as refused:
                return Lent(unlent=f"your GitHub login: {refused}")
            logins = dict.fromkeys(part.holds.github, login.token)
        ssh = None
        if part.holds.ssh:
            socket = Lending().ssh_auth_sock
            if socket is None:
                return Lent(
                    unlent=(
                        "your SSH agent: the machine has no `SSH_AUTH_SOCK`, so start "
                        "your agent and open the project again from a terminal "
                        "where it's set"
                    )
                )
            ssh = SshAgent(socket=socket, home=Path.home())
        return Lent(
            secrets={**secrets, **logins},
            ssh=ssh,
            git=opening.common if part.holds.git else None,
        )

    async def placed(
        self,
        source: Source,
        part: PartPlan | None,
        parts: list[str],
        plans: list[PartPlan],
        lent: Lent | None = None,
        *,
        header: int = 80,
    ) -> Placement:
        """Start one container of the project running `parts`, whose plans are `plans`, its sockets' directory from `Carrying`, in memory, given the secrets `lent` holds as files there, which it reads and removes as it starts, and what else it lends bound in; its image with the packages its parts' programs are in; and return where it runs.

        A file in the operator's `~/.ssh` is taken for a private key by its
        first `header` bytes, the line a key begins with.
        """

        def lending(lent: Lent | None) -> list[Bind]:
            """Return what binds into the container what `lent` lends: the project's git directory, read-write but its `config` and `hooks/`, as a room has it; and the SSH agent's socket, with the operator's `~/.ssh` read-only, each file in it holding a private key hidden behind an empty one, listed after what they hide, as podman mounts them in order."""

            def keyed(path: Path) -> bool:
                """Say whether `path` is a file holding a private key, by its first line alone, as OpenSSH, PEM and PuTTY begin one: the key itself is never read."""
                if path.is_symlink() or not path.is_file():
                    return False
                with path.open("rb") as file:
                    first = file.readline(header)
                return b"PRIVATE KEY-----" in first or first.startswith(
                    b"PuTTY-User-Key-File-"
                )

            binds: list[Bind] = []
            if lent is not None and lent.git is not None:
                hooks = lent.git / "hooks"
                hooks.mkdir(exist_ok=True)
                binds += [
                    Bind(source=lent.git.resolve(), target=lent.git, read_only=False),
                    Bind(
                        source=(lent.git / "config").resolve(),
                        target=lent.git / "config",
                    ),
                    Bind(source=hooks.resolve(), target=hooks),
                ]
            if lent is not None and lent.ssh is not None:
                ssh = lent.ssh.home / ".ssh"
                binds += [
                    Bind(source=lent.ssh.socket.resolve(), target=lent.ssh.socket)
                ]
                if ssh.is_dir():
                    binds += [
                        Bind(source=ssh.resolve(), target=ssh),
                        *(
                            Bind(source=Path(os.devnull), target=each)
                            for each in sorted(ssh.rglob("*"))
                            if keyed(each)
                        ),
                    ]
            return binds

        opening = source.opening
        name = self.container(source, part)
        directory = await Carrying.directory(Naming(container=name))
        secrets = {} if lent is None else lent.secrets
        start = Start(
            root=source.root,
            declaration=opening.declaration,
            repository=opening.repository,
            parts=None if part is None else parts,
            listening=Path("/run/lup/listening.sock"),
            calling=Path("/run/lup/calling.sock"),
            secrets=None if not secrets else Path("/run/lup/secrets"),
            data=Path("/var/lup/data"),
            runtime=Path("/run/lup/runtime"),
            git=None if lent is None else lent.git,
            ssh=None if lent is None else lent.ssh,
        )
        if secrets:
            kept = directory.path / "secrets"
            kept.mkdir(mode=0o700, exist_ok=True)
            for each, value in secrets.items():
                file = kept / each
                file.touch(mode=0o600)
                file.write_text(value)
        image = self.image(
            opening.repository,
            [package for each in plans for package in each.packages],
        )
        await Containers.built(image)
        spec = self.spec(source, name, self.role(source, part), directory.path)
        spec = spec.model_copy(
            update={
                "image": image,
                "binds": [*spec.binds, *lending(lent)],
                "env": {
                    **spec.env,
                    **(
                        {}
                        if lent is None or lent.ssh is None
                        else {"HOME": str(lent.ssh.home)}
                    ),
                    "LUP_ASKED": start.model_dump_json(),
                },
                "output": self.output(name),
            }
        )
        await Containers.started(spec)
        return Placement(
            repository=opening.repository,
            parts=parts,
            container=name,
            directory=directory.path,
        )
