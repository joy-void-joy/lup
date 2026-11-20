"""`Rooms`: the machine's part making each session's room, the container its runtime runs in.

A room is the standard machine and the packages the project's modules declare
(`Packages`), built once per definition; the repository it works in, read-write,
its git `config` and `hooks/` read-only; the session's own files lup writes,
read-only, and its runtime's own directory and home, on disk; the history its
project's rooms share and its account's login, kept where the second lup keeps
them; the newest CLI of every runtime lup holds sessions on, so a session on
one can run the other; the machine's own lup, read-only, which the room's
first program, hooks and tool server run from; and the room's directory of
sockets, the machine's and its holder's (`README.md` here).
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import Field

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Machine
from lup.doors.parts import Data, Part, Program
from lup.hosting.carrying import Carrying, Naming
from lup.hosting.containers import Bind, Containers, Image, Named, Spec
from lup.rooms.layout import InRoom, Kept, digest
from lup.rooms.packages import Package
from lup.runtimes.known import known, named
from lup.runtimes.runtime import Begin, Bridge, Fetched, Placed, Runtime
from lup.types import Model


class RoomFor(Model):
    """A session's room to start: the project it works on, the session, its runtime and how it begins, its worktree, its guidance and its account."""

    repository: str
    """The project, as lup names it."""
    common: Path
    """Its common git directory on the machine."""
    session: str
    runtime: str
    begin: Begin
    worktree: Path
    guidance: str
    """What the session is told at its start, at system level."""
    account: str = "default"
    packages: list[Package] = []
    """What the project's modules add to the standard machine."""
    held: bool = True
    """Whether lup holds it over its input and output; a terminal's otherwise."""


class Roomed(Model):
    """A session's room as it started: its container, its directory of sockets on the machine, and the command its terminal would run."""

    container: str
    sockets: Path
    """Its directory of sockets on the machine, mounted at `/run/lup` in it."""


class Base(Model):
    """The image every room starts from: Arch Linux's, pinned with the day of its archive its packages come from, as a project's containers' is."""

    image: str = (
        "docker.io/library/archlinux:base-20260816.0.574111"
        "@sha256:4bf33b21a715aac0b48ce6e9eaed4782a898eae96f88f5da3635572129c2584a"
    )
    archive: str = "https://archive.archlinux.org/repos/2026/08/15/$repo/os/$arch"
    locale: str = "en_US.UTF-8"

    def definition(self, packages: list[Package]) -> str:
        """Return the Containerfile of a room holding `packages`, each named once, in order."""
        names = list(dict.fromkeys(each.name for each in packages))
        steps = [
            f"echo 'Server = {self.archive}' > /etc/pacman.d/mirrorlist",
            "pacman -Syu --noconfirm --needed -- " + " ".join(names),
            f"echo '{self.locale} UTF-8' >> /etc/locale.gen",
            "locale-gen",
            "rm -rf /var/cache/pacman/pkg/*",
        ]
        return f"FROM {self.image}\nRUN " + " \\\n    && ".join(steps) + "\n"


class Fresh(Model):
    """A runtime's CLI as last fetched: its version, and when its vendor was last asked for the newest."""

    fetched: Fetched
    asked: datetime


class Rooms(Part, machine=True, shared=True):
    """The machine's part making each session's room: its image, its CLIs, its files and homes, and the container it runs in."""

    sessions: Data
    """Each session's own, a directory each: lup's files for it, its runtime's
    own directory, and its room's home."""
    clis: Data
    """Each runtime's CLIs as fetched, a directory per version."""
    rooms: Data
    """Each project's rooms' own: uv's cache and each session's environment,
    one directory a project, so an environment's files are links into the
    cache."""
    uv: Program = Program(
        name="uv",
        optional=True,
        why="says where the machine keeps Python, which the room's lup runs on",
        install="https://docs.astral.sh/uv/getting-started/installation/",
    )
    base: Base = Field(default_factory=Base)
    kept: Kept = Field(default_factory=Kept)
    inside: InRoom = Field(default_factory=InRoom)
    fresh: dict[str, Fresh] = {}
    """Each runtime's CLI as last fetched, by the runtime's name."""
    asking: timedelta = timedelta(hours=1)
    """How long a CLI fetched stays the newest before its vendor is asked
    again: CLIs release daily, and a session's start shouldn't wait on the
    network each time."""

    @lup.service
    async def readied(self, room: RoomFor, by: Machine) -> Roomed:
        """Start a session's room, its runtime held over the room's socket or run in a terminal, and say where it is.

        Raise `RefusedError` where its runtime isn't one lup holds, or its CLI
        can't be fetched and none was before.
        """
        del by
        runtime = self.runtime(room.runtime)
        image = Image(
            base=self.base.image,
            definition=self.base.definition(room.packages),
            project=room.repository,
        )
        await Containers.built(image)
        clis = {each.name: self.cli(each.name) for each in known()}
        own = self.sessions.path / room.session
        files, home, directory = own / "files", own / "home", own / "runtime"
        for each in [files, home, directory]:
            each.mkdir(parents=True, exist_ok=True)
        placed = Placed(
            worktree=room.worktree, home=home, runtime=directory, session=files
        )
        python = Path(sys.executable)
        bridge = Bridge(
            hook=[str(python), "-I", "-m", "lup.environment.sessions.hook"],
            tools=[str(python), "-I", "-m", "lup.environment.sessions.tools"],
        )
        prepared = runtime.rooming.prepared(
            room.begin, placed, bridge, room.guidance, held=room.held
        )
        for name, text in prepared.files.items():
            (files / name).write_text(text)
        for name, text in prepared.homed.items():
            (directory / name).write_text(text)
        history = self.kept.history(room.common, runtime.name)
        for name in runtime.rooming.kept():
            self.linked(directory / name, history / name)
        container = f"lup-{room.repository}-{room.session}"
        sockets = (await Carrying.directory(Naming(container=container))).path
        interpreters = await self.interpreters()
        spec = self.spec(
            room,
            container=container,
            placed=placed,
            env=prepared.env,
            clis=clis,
            sockets=sockets,
            interpreters=interpreters,
        )
        command = [
            str(python),
            "-I",
            "-m",
            "lup.environment.sessions.connected",
            "--sync",
            str(home / "sync.log"),
            str(self.inside.holder()),
            "--",
            *prepared.command,
        ]
        login = self.kept.login(room.account, runtime.name, runtime.rooming.login())
        binds = [
            *spec.binds,
            *[
                Bind(source=files / each.name, target=each.at)
                for each in prepared.placed
            ],
            *(
                [Bind(source=login, target=directory / login.name, read_only=False)]
                if login.is_file() and login.stat().st_size > 0
                else []
            ),
            Bind(source=history, read_only=False),
        ]
        started = spec.model_copy(
            update={
                "command": command if room.held else prepared.command,
                "binds": binds,
            }
        )
        await Containers.started(started)
        return Roomed(container=container, sockets=sockets)

    @lup.service
    async def closed(self, named: Named, by: Machine) -> None:
        """Stop a session's room: its runtime made to end, where it hasn't."""
        del by
        await Containers.stopped(named)

    def runtime(self, name: str) -> Runtime:
        """Return the runtime lup names `name`.

        Raise `RefusedError` where it holds none so named.
        """
        try:
            return named(name)
        except ValueError as unknown:
            raise RefusedError(str(unknown)) from unknown

    def cli(self, runtime: str) -> Fetched:
        """Return runtime `runtime`'s newest CLI, fetched where its vendor has a newer one than the one fetched last, asking it at most every `asking`.

        Raise `RefusedError` where it can't be fetched and none was before.
        """
        now = datetime.now(UTC)
        fresh = self.fresh.get(runtime)
        if fresh is not None and now - fresh.asked < self.asking:
            return fresh.fetched
        channel = named(runtime).channel
        try:
            version = channel.latest()
            into = self.clis.path / runtime / version
            record = into / "fetched.json"
            fetched = (
                Fetched.model_validate_json(record.read_text())
                if record.is_file()
                else channel.fetched(version, into / "cli")
            )
            record.write_text(fetched.model_dump_json())
        except (OSError, ValueError) as failed:
            if fresh is not None:
                return fresh.fetched
            message = f"{runtime}'s newest CLI can't be fetched, and none was before: {failed}"
            raise RefusedError(message) from failed
        self.fresh = {**self.fresh, runtime: Fresh(fetched=fetched, asked=now)}
        return fetched

    def linked(self, place: Path, history: Path) -> None:
        """Make `place`, in a runtime's own directory, a link to `history`, in the history its project's rooms share: made where it isn't, a directory where its name has no suffix, a file otherwise."""
        if not history.exists():
            if history.suffix:
                history.parent.mkdir(parents=True, exist_ok=True)
                history.touch()
            else:
                history.mkdir(parents=True, exist_ok=True)
        if place.is_symlink() or place.exists():
            return
        place.symlink_to(history)

    def spec(
        self,
        room: RoomFor,
        *,
        container: str,
        placed: Placed,
        env: dict[str, str],
        clis: dict[str, Fetched],
        sockets: Path,
        interpreters: Path,
    ) -> Spec:
        """Return a session's room, its runtime's command to come: the repository read-write, its git `config` and `hooks/` read-only, lup's own files, homes and CLIs, its variables."""
        tree = room.common.parent if room.common.name == ".git" else room.common
        hooks = room.common / "hooks"
        hooks.mkdir(exist_ok=True)
        rooms = self.rooms.path / digest(room.common)
        environment = rooms / "environments" / room.session
        cache = rooms / "cache"
        for each in [environment, cache]:
            each.mkdir(parents=True, exist_ok=True)
        lup_environment = Path(sys.prefix)
        binds = [
            Bind(source=tree, read_only=False),
            Bind(source=room.common / "config"),
            Bind(source=hooks),
            Bind(source=rooms, read_only=False),
            Bind(source=lup_environment.resolve(), target=lup_environment),
            Bind(source=interpreters.resolve(), target=interpreters),
            Bind(source=placed.session),
            Bind(source=placed.runtime, read_only=False),
            Bind(source=placed.home, read_only=False),
            Bind(source=sockets, target=self.inside.sockets, read_only=False),
            *[
                Bind(source=each.directory, target=self.inside.cli(name))
                for name, each in clis.items()
            ],
        ]
        path = ":".join(
            [
                *[
                    str(self.inside.cli(name) / each.program.parent)
                    for name, each in clis.items()
                ],
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
            ]
        )
        return Spec(
            name=container,
            image=Image(
                base=self.base.image,
                definition=self.base.definition(room.packages),
                project=room.repository,
            ),
            command=[],
            workdir=room.worktree,
            binds=binds,
            hidden=[room.worktree / ".venv"],
            env={
                "HOME": str(placed.home),
                "PATH": path,
                "LANG": self.base.locale,
                "LUP_CALLING": str(self.inside.calling()),
                "LUP_SESSION": room.session,
                "UV_CACHE_DIR": str(cache),
                "UV_PROJECT_ENVIRONMENT": str(environment),
                "UV_PYTHON_DOWNLOADS": "never",
                "UV_PYTHON_INSTALL_DIR": str(interpreters),
                **env,
            },
        )

    async def interpreters(self) -> Path:
        """Return where the machine's uv keeps its Python interpreters, which the machine's lup and every room's environment run on, mounted read-only at their own path.

        Raise `RefusedError` where uv can't say.
        """
        found = await self.uv.ran("python", "dir")
        if found.status != 0:
            message = f"uv can't say where it keeps Python: {found.said()}"
            raise RefusedError(message)
        return Path(found.text().strip())
