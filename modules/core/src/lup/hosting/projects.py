"""`Projects`: the machine's part running each project, from planning its declaration to starting the containers its plan says.

Opening a project plans its declaration in a container, which prints the plan,
then starts its containers from the plan: one for every part holding nothing,
and one for each part holding something that isn't the whole machine's, given
only the secrets it holds. Each container's directory of sockets comes from
`Carrying`, which is told where each part runs (`README.md` here, *Projects*).

A project's Python environment is made in its container, as rooms make theirs:
the machine's own uv-managed interpreters mounted read-only at their own paths,
nothing fetched, and the environment and uv's cache kept in directories of the
project's own under this part's data, so a container starts on what it synced
before.
"""

from pathlib import Path

from pydantic import Field, TypeAdapter

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine, Operator
from lup.doors.parts import Data, Part
from lup.hosting.carrying import Carrying, Naming, Placement, Placing
from lup.hosting.containers import Bind, Containers, Image, Once, Spec
from lup.hosting.secrets import Holding, Secrets
from lup.running.plan import PartPlan, Plan
from lup.running.wire import Planning, Start, read
from lup.types import Model

PLANS = TypeAdapter[Plan](Plan)


class Opening(Model):
    """A project to run: its repository, as lup names it, its tree at the commit it runs, and its declaration."""

    repository: str
    root: Path
    """Its tree on the machine, at the commit it runs, mounted read-only."""
    declaration: Path = Path("lup_project.py")
    """Its declaration, relative to the root."""
    interpreters: Path
    """Where the machine's uv keeps its Python interpreters, mounted read-only
    at the same path, so a container runs the Python the project asks for
    without fetching one."""


class Opened(Model):
    """A project running: its plan, and the containers started for it."""

    repository: str
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
    """Each project's Python environment and uv cache, a directory each."""
    base: Base = Field(default_factory=Base)
    projects: dict[str, Opened] = {}
    """Each project running, by its repository."""

    def image(self, repository: str) -> Image:
        """Return the image a project's containers run."""
        return Image(definition=self.base.definition(), project=repository)

    def spec(self, opening: Opening, name: str, sockets: Path | None) -> Spec:
        """Return a container of the project running the program a container runs, its tree read-only, its environment and cache its own."""
        environment = self.places.path / opening.repository / "environment"
        cache = self.places.path / opening.repository / "cache"
        environment.mkdir(parents=True, exist_ok=True)
        cache.mkdir(parents=True, exist_ok=True)
        binds = [
            Bind(source=opening.root),
            Bind(source=opening.interpreters),
            Bind(
                source=environment, target=Path("/var/lup/environment"), read_only=False
            ),
            Bind(source=cache, target=Path("/var/lup/cache"), read_only=False),
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
                str(opening.root),
                "python",
                "-m",
                "lup.environment.running",
            ],
            workdir=opening.root,
            binds=binds,
            env={
                "UV_PROJECT_ENVIRONMENT": "/var/lup/environment",
                "UV_CACHE_DIR": "/var/lup/cache",
                "UV_PYTHON_DOWNLOADS": "never",
            },
        )

    @lup.command
    async def open(self, opening: Opening, by: Operator) -> str:
        """Run a project: plan its declaration, and start the containers its plan says."""
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
        """Plan a project and start its containers, in place of those it ran before.

        Raise `RefusedError` where its declaration doesn't plan, or podman
        fails.
        """
        del by
        return await self.opening(opening)

    async def opening(self, opening: Opening) -> Opened:
        """Plan a project and start its containers, in place of those it ran before: one for its parts holding nothing, and one for each part holding something that isn't the machine's, given only the secrets it holds, unless one isn't kept."""
        await Containers.built(self.image(opening.repository))
        plan = await self.planned(opening)
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
        placements = [
            *([await self.placed(opening, None, together)] if together else []),
            *[
                await self.placed(
                    opening, each, [each.named()], held[each.named()].values
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
            plan=plan,
            containers=[each.container for each in placements],
            waiting=waiting,
        )
        self.projects = {**self.projects, opening.repository: opened}
        return opened

    async def planned(self, opening: Opening) -> Plan:
        """Plan the project's declaration in a container, and read the plan it prints.

        Raise `RefusedError` where it doesn't plan.
        """
        asked = Planning(root=opening.root, declaration=opening.declaration)
        name = f"lup-plan-{opening.repository}"
        finished = await Containers.ran(
            Once(spec=self.spec(opening, name, None), given=asked.model_dump_json())
        )
        if finished.status != 0:
            message = f"{opening.repository}'s declaration didn't plan: {finished.error.strip()}"
            raise RefusedError(message)
        return read(finished.output, PLANS)

    async def placed(
        self,
        opening: Opening,
        part: PartPlan | None,
        parts: list[str],
        secrets: dict[str, str] | None = None,
    ) -> Placement:
        """Start one container of the project running `parts`, its sockets' directory from `Carrying`, given the secrets in `secrets` as files, and return where it runs."""
        name = (
            f"lup-{opening.repository}-project"
            if part is None
            else f"lup-{opening.repository}-{part.module}-{part.part}"
        )
        directory = await Carrying.directory(Naming(container=name))
        start = Start(
            root=opening.root,
            declaration=opening.declaration,
            repository=opening.repository,
            parts=None if part is None else parts,
            listening=Path("/run/lup/listening.sock"),
            calling=Path("/run/lup/calling.sock"),
            secrets=None if not secrets else Path("/run/lup/secrets"),
        )
        if secrets:
            kept = directory.path / "secrets"
            kept.mkdir(mode=0o700, exist_ok=True)
            for each, value in secrets.items():
                file = kept / each
                file.touch(mode=0o600)
                file.write_text(value)
        spec = self.spec(opening, name, directory.path)
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
