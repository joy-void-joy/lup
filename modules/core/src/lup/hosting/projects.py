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

from pathlib import Path

from pydantic import Field, TypeAdapter, ValidationError

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine, Operator
from lup.doors.parts import Data, Part
from lup.errors import LupError
from lup.hosting.approvals import Approvals, Asking
from lup.hosting.carrying import Carrying, Naming, Placement, Placing
from lup.hosting.containers import Bind, Containers, Image, Named, Once, Spec
from lup.hosting.secrets import Holding, Secrets
from lup.hosting.trees import Commit, Exporting, Trees
from lup.running.plan import Name, PartPlan, Plan
from lup.running.wire import Planning, Start, read
from lup.types import Model

PLANS = TypeAdapter[Plan](Plan)


class Opening(Model):
    """A project to run: its repository, as lup names it, where git keeps it, and its declaration."""

    repository: Name
    common: Path
    """Its common git directory on the machine, which the commit approved is
    written out from."""
    declaration: Path = Path("lup_project.py")
    """Its declaration, relative to its root."""
    interpreters: Path
    """Where the machine's uv keeps its Python interpreters, mounted read-only
    at this path, which an environment's links name, so a container runs the
    Python the project asks for without fetching one."""


class Source(Model):
    """A project's commit as its containers run it: written out on the machine, mounted read-only at the same path."""

    opening: Opening
    commit: Commit
    root: Path
    """The commit's files, written out."""


class Opened(Model):
    """A project running: the commit it runs, its plan, and the containers started for it."""

    repository: str
    commit: Commit
    plan: Plan
    containers: list[str] = []
    waiting: list[str] = []
    """Parts holding a secret nothing's kept yet, by `module.Part`, not
    started until the operator gives it."""


class Base(Model):
    """The image every project's containers start from: Arch Linux's, pinned with the day of its archive its packages come from, with git and uv."""

    image: str = (
        "docker.io/library/archlinux:base-20260816.0.574111"
        "@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a"
    )
    archive: str = "https://archive.archlinux.org/repos/2026/08/15/$repo/os/$arch"
    packages: list[str] = ["git", "uv"]

    def definition(self) -> str:
        """Return its Containerfile."""
        steps = [
            f"echo 'Server = {self.archive}' > /etc/pacman.d/mirrorlist",
            "pacman -Syu --noconfirm --needed -- " + " ".join(self.packages),
            "rm -rf /var/cache/pacman/pkg/*",
        ]
        return f"FROM {self.image}\nRUN " + " \\\n    && ".join(steps) + "\n"


class Projects(Part, machine=True, shared=True):
    """The machine's part running each project: planning its declaration in a container, and starting the containers its plan says."""

    places: Data
    """Each container's Python environment, uv cache and parts' data, a
    directory each, by the container's name."""
    base: Base = Field(default_factory=Base)
    projects: dict[str, Opened] = {}
    """Each project running, by its repository."""

    def image(self, repository: str) -> Image:
        """Return the image a project's containers run."""
        return Image(
            base=self.base.image, definition=self.base.definition(), project=repository
        )

    def spec(self, source: Source, name: str, sockets: Path | None) -> Spec:
        """Return a container of the project running the program a container runs, its commit's files read-only, its environment, uv's cache and its parts' data the container's own."""
        opening = source.opening
        environment = self.places.path / name / "environment"
        cache = self.places.path / name / "cache"
        data = self.places.path / name / "data"
        for each in [environment, cache, data]:
            each.mkdir(parents=True, exist_ok=True)
        binds = [
            Bind(source=source.root),
            Bind(source=opening.interpreters.resolve(), target=opening.interpreters),
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
            },
        )

    @lup.command
    async def open(self, opening: Opening, by: Operator) -> str:
        """Run a project, at the commit you approved last: plan its declaration, and start the containers its plan says."""
        del by
        opened = await self.opening(opening)
        waiting = (
            ""
            if not opened.waiting
            else f"; waiting on secrets for {', '.join(opened.waiting)}"
        )
        return f"{opened.repository}: {len(opened.containers)} containers{waiting}"

    @lup.service
    async def opened(self, opening: Opening, by: Machine) -> Opened:
        """Run a project at the commit the operator approved last: plan its declaration, and start its containers, in place of those it ran before.

        Raise `RefusedError` where nothing of it is approved yet, its commit
        can't be written out, its declaration doesn't plan, or podman fails.
        """
        del by
        return await self.opening(opening)

    async def opening(self, opening: Opening) -> Opened:
        """Run a project at the commit the operator approved last: plan it, stop the containers it ran before, and start one for its parts holding nothing, and one for each part holding something that isn't the machine's, given only the secrets it holds, unless one isn't kept.

        Raise `RefusedError` where nothing of it is approved yet.
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
        source = Source(opening=opening, commit=approved.commit, root=exported.path)
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
        together = [each.named() for each in plan.together()]
        before = self.projects.get(opening.repository)
        for name in [] if before is None else before.containers:
            await Containers.stopped(Named(name=name))
        placements = [
            *([await self.placed(source, None, together)] if together else []),
            *[
                await self.placed(
                    source, each, [each.named()], held[each.named()].values
                )
                for each in apart
                if each.named() not in waiting
            ],
        ]
        await Carrying.placed(
            Placing(repository=opening.repository, plan=plan, placements=placements)
        )
        opened = Opened(
            repository=opening.repository,
            commit=approved.commit,
            plan=plan,
            containers=[each.container for each in placements],
            waiting=waiting,
        )
        self.projects = {**self.projects, opening.repository: opened}
        return opened

    async def planned(self, source: Source) -> Plan:
        """Plan the project's declaration in a container, and read the plan it prints.

        Raise `RefusedError` where it doesn't plan.
        """
        opening = source.opening
        asked = Planning(root=source.root, declaration=opening.declaration)
        name = f"lup-plan-{opening.repository}"
        finished = await Containers.ran(
            Once(spec=self.spec(source, name, None), given=asked.model_dump_json())
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
        return plan

    async def placed(
        self,
        source: Source,
        part: PartPlan | None,
        parts: list[str],
        secrets: dict[str, str] | None = None,
    ) -> Placement:
        """Start one container of the project running `parts`, its sockets' directory from `Carrying`, in memory, given the secrets in `secrets` as files there, which it reads and removes as it starts, and return where it runs."""
        opening = source.opening
        name = (
            f"lup-{opening.repository}-project"
            if part is None
            else f"lup-{opening.repository}-{part.module}-{part.part}"
        )
        directory = await Carrying.directory(Naming(container=name))
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
        )
        if secrets:
            kept = directory.path / "secrets"
            kept.mkdir(mode=0o700, exist_ok=True)
            for each, value in secrets.items():
                file = kept / each
                file.touch(mode=0o600)
                file.write_text(value)
        spec = self.spec(source, name, directory.path)
        spec = spec.model_copy(
            update={"env": {**spec.env, "LUP_ASKED": start.model_dump_json()}}
        )
        await Containers.started(spec)
        return Placement(
            repository=opening.repository,
            parts=parts,
            container=name,
            directory=directory.path,
        )
