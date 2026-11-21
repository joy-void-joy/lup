"""The loader: what the installed `lup` runs to bring the machine's parts up, the one thing of lup's that isn't a module.

`lup` calls through the machine's socket, and where nothing answers there it
starts the machine, detached, so it outlives the command (`Loader.ensured`). The
machine's parts run from the home repository the machine's layer names
(`Core.home`), at the commit the operator approved; with none named, from the
installed `lup` itself, installing being the approval. Where the home
repository's running branch moved since the commit approved, the operator is
asked at the terminal, as adlib asked: a summary of what changed first, read
from each object's own bytes, then whether to show the whole diff, then whether
to approve, each no by default. Declined, the commit approved before runs.

To ask, the loader starts `Trees` and `Approvals` in its own process, from the
installed `lup`'s code, never the home repository's, which is what's asked
about. The commit approved is written out from git's objects, its environment
synced, and the machine started from it; where its socket doesn't answer in
time, it's stopped, and the last commit that came up starts again, saying why
(`lup/hosting/README.md`, *The loader*).
"""

import operator
import os
import signal
import sys
from datetime import timedelta
from pathlib import Path

import platformdirs
import typer
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
)

import lup.hosting.installed
from lup.core import Core
from lup.declaration.grammar import applied, set_fields
from lup.declaration.layout import MachineLayout, Pyproject, RepositoryLayout
from lup.declaration.project import Project
from lup.doors.door import Accepted, RefusedError
from lup.doors.parties import Machine, Operator
from lup.environment.declaration import load, resolve
from lup.environment.running.calling import Calling
from lup.environment.running.programs import Local
from lup.errors import LupError
from lup.hosting.approvals import Approved, Question
from lup.hosting.projects import Opening
from lup.hosting.trees import Diffed, Exported
from lup.programs import awaited, detached
from lup.programs.git import Git
from lup.running.wire import Answered, CommandCalled, Declined, Host
from lup.types import Model
lazy from lup.environment.doors import Running
lazy from lup.programs import Apart


class LoaderError(LupError):
    """The machine's parts can't be brought up: nothing of the home repository is approved, or neither the commit approved nor the last that came up answers."""


class Places(Model):
    """Where the machine keeps what it keeps, in the platform's own places: its parts' data, the environments of the commits it runs, and what lasts while it runs."""

    state: Path
    """Its parts' data and what the loader keeps: `$XDG_STATE_HOME/lup`."""
    data: Path
    """Each machine commit's Python environment: `$XDG_DATA_HOME/lup`."""
    runtime: Path
    """Its sockets, and what it hands over to be read once:
    `$XDG_RUNTIME_DIR/lup`, a short path, in memory."""

    @classmethod
    def found(cls) -> Places:
        """Return the places on this machine, as `platformdirs` says them."""
        return cls(
            state=platformdirs.user_state_path("lup"),
            data=platformdirs.user_data_path("lup"),
            runtime=platformdirs.user_runtime_path("lup"),
        )

    def socket(self) -> Path:
        """Return the operator's socket, which `Carrying` makes in its directory of sockets, under the machine's runtime place."""
        return (
            self.runtime / "hosting.Carrying" / "sockets" / "operator" / "calling.sock"
        )

    def log(self) -> Path:
        """Return where the machine's output goes, appended."""
        return self.state / "machine.log"

    def record(self) -> Path:
        """Return where the loader keeps what came up last."""
        return self.state / "machine.json"


class Came(Model):
    """A machine that came up: the commit of the home repository it runs, none for the installed `lup`, and its process."""

    commit: str | None = None
    pid: int


class Hosted(Model):
    """A machine to start: the commit of the home repository it runs, none for the installed `lup`, and how it's hosted."""

    commit: str | None = None
    host: Host


class Repository(Model):
    """The home repository, as the loader reads it: its name, its common git directory, and its running branch's tip."""

    name: str
    common: Path
    tip: str

    @classmethod
    async def located(cls, home: Path) -> Repository:
        """Read the repository holding `home`, git pinned to its own git directory where it reads the tip, since a room writes it.

        Raise `LoaderError` where `home` is in no worktree, or
        `lup.programs.git.GitError` where it has no `dev`.
        """
        worktree = await Git.located(home)
        if worktree is None:
            message = f"{home} is in no git worktree, so lup has no repository to run"
            raise LoaderError(message)
        # lup: defer(issue=10, why="the running commit computed from `dev` and the branches the operator picked to run, rather than `dev`'s tip")
        tip = await Git.pinned(worktree.common).branch("dev")
        return cls(name=worktree.main.name, common=worktree.common, tip=tip)


async def answering(socket: Path) -> bool:
    """Say whether the machine answers on `socket`."""
    try:
        await Calling(socket=socket).offered()
    except RefusedError:
        return False
    return True


def home_of(machine: MachineLayout) -> Path | None:
    """Return the home repository the machine's layer names, `Core.home`; none where it names none, or there's no layer."""
    if not machine.layer.is_file():
        return None
    layer = load(machine.layer)
    resolved = resolve(applied(layer, Project(), set_fields(layer)))
    core = next((each for each in resolved.modules if isinstance(each, Core)), None)
    return None if core is None else core.home


def asked(question: Question, diff: Diffed | None) -> bool:
    """Ask the operator at the terminal whether to approve the commit `question` is about: a summary first, what a part holding something runs and the dependencies called out, the whole diff where they ask for it; no by default."""
    before = question.before or "nothing yet"
    typer.echo(
        f"lup's machine runs {question.project} at the commit you approved: {before}."
    )
    typer.echo(
        f"Its running branch is at {question.tip}, "
        f"{len(question.changes)} files changed since."
    )
    if question.holding:
        typer.echo("Changed where a part holding something runs:")
        typer.echo("".join(f"  {each.how} {each.path}\n" for each in question.holding))
    if question.dependencies:
        typer.echo("Every part's dependencies changed.")
    typer.echo("".join(f"  {each.how} {each.path}\n" for each in question.changes))
    if diff is not None and typer.confirm("Show the whole diff?", default=False):
        typer.echo(diff.text)
    return typer.confirm(f"Approve {question.tip} to run?", default=False)


class Loader(Model):
    """What brings the machine's parts up: where it keeps what it keeps, how long a machine may take to answer, and whether the operator is there to ask."""

    places: Places
    machine: MachineLayout
    within: timedelta = timedelta(minutes=1)
    """How long a machine started may take to answer on its socket, past
    which it's stopped and the last that came up starts again."""
    interactive: bool = True
    """Whether the operator can be asked at this terminal; where not, the
    commit approved last runs, and none approved refuses."""

    async def ensured(self) -> Path:
        """Return the machine's socket, the machine started first where nothing answers there.

        Raise `LoaderError` where nothing of the home repository is approved,
        or neither the commit approved nor the last that came up answers.
        """
        socket = self.places.socket()
        if await answering(socket):
            return socket
        home = home_of(self.machine)
        hosted = self.installed() if home is None else await self.approved(home)
        return await self.started(hosted)

    def installed(self) -> Hosted:
        """Return the installed `lup`'s own machine parts, hosted from the declaration it ships."""
        declaration = Path(lup.hosting.installed.__file__)
        return Hosted(
            host=Host(
                root=declaration.parent,
                declaration=Path(declaration.name),
                repository="lup",
                state=self.places.state,
                runtime=self.places.runtime,
            )
        )

    async def approved(self, home: Path) -> Hosted:
        """Return the commit of `home` approved to run, asking the operator where its running branch moved since, hosted from that commit written out.

        Raise `LoaderError` where nothing of it is approved.
        """
        repository = await Repository.located(home)
        running = await self.asking()
        try:
            commit = await self.answered(running, repository)
            exported = await running.serve(
                "exported",
                {
                    "repository": repository.name,
                    "common": str(repository.common),
                    "commit": commit,
                },
                Machine(),
            )
        finally:
            await running.stopped()
        if not isinstance(exported, Accepted):
            raise LoaderError(exported.rejection.reason)
        root = Exported.model_validate(exported.output).path
        declaration = Pyproject.read(root / "pyproject.toml").tool.lup.declaration
        return Hosted(
            commit=commit,
            host=Host(
                root=root,
                declaration=Path(declaration),
                repository=repository.name,
                state=self.places.state,
                runtime=self.places.runtime,
            ),
        )

    async def reviewed(self, socket: Path, layout: RepositoryLayout) -> str | None:
        """Ask the operator, where the project whose worktree `lup` runs in moved since the commit they approved, whether to approve its tip, and open it again at that commit where they do: the question at start, for a project as for the home repository; say what happened, none where nothing needed asking.

        Asks nothing where `lup` can't ask here, or the worktree holds no
        declaration: its project isn't one lup runs.
        """
        if not self.interactive or not layout.declaration.is_file():
            return None
        repository = await Repository.located(layout.root)
        running = await self.asking()
        try:
            approval = await running.serve(
                "approval", {"project": repository.name}, Machine()
            )
            before = (
                Approved.model_validate(approval.output).commit
                if isinstance(approval, Accepted)
                else None
            )
            if before == repository.tip:
                return None
            try:
                commit = await self.answered(running, repository)
            except LoaderError as unapproved:
                return str(unapproved)
        finally:
            await running.stopped()
        if commit == before:
            return f"{repository.name} runs {commit}, as you approved before"
        opening = Opening(
            repository=repository.name,
            common=repository.common,
            declaration=layout.declaration.relative_to(layout.root),
        )
        reply = await Calling(socket=socket).answered(
            CommandCalled(
                module="hosting",
                command="open",
                given=opening.model_dump(mode="json"),
            )
        )
        match reply:
            case Answered(output=str() as said):
                return said
            case Answered():
                return f"{repository.name} opened at {commit}"
            case Declined(rejection=rejection):
                return f"{repository.name} is approved at {commit}, and didn't open: {rejection.reason}"

    async def answered(self, running: Running, repository: Repository) -> str:
        """Return the commit of `repository` approved to run: the one approved last, or its tip where the operator, asked here, approves it.

        Raise `LoaderError` where none is approved.
        """
        approval = await running.serve(
            "approval", {"project": repository.name}, Machine()
        )
        if not isinstance(approval, Accepted):
            raise LoaderError(approval.rejection.reason)
        commit = Approved.model_validate(approval.output).commit
        if commit != repository.tip and self.interactive:
            question = await running.serve(
                "question",
                {
                    "project": repository.name,
                    "common": str(repository.common),
                    "tip": repository.tip,
                },
                Machine(),
            )
            diffed = await running.serve(
                "diffed",
                {
                    "repository": repository.name,
                    "common": str(repository.common),
                    "before": commit,
                    "after": repository.tip,
                },
                Machine(),
            )
            if not isinstance(question, Accepted):
                raise LoaderError(question.rejection.reason)
            diff = (
                Diffed.model_validate(diffed.output)
                if isinstance(diffed, Accepted)
                else None
            )
            if asked(Question.model_validate(question.output), diff):
                await running.run(
                    "hosting",
                    "approve",
                    {"project": repository.name, "commit": repository.tip},
                    Operator(),
                )
                commit = repository.tip
        if commit is None:
            message = (
                f"nothing of {repository.name} is approved to run: approve a commit "
                "of it at a terminal, where `lup` asks"
            )
            raise LoaderError(message)
        return commit

    async def asking(self) -> Running:
        """Start `Trees` and `Approvals` in this process, from the installed `lup`'s code, over the machine's own data, to ask with."""
        resolved = resolve(load(Path(lup.hosting.installed.__file__)))
        return await resolved.doors.started(
            "lup",
            {},
            only=["hosting.Trees", "hosting.Approvals"],
            data=self.places.state / "data",
            runtime=self.places.runtime,
            runs=Local(),
            machine=True,
        )

    async def started(self, hosted: Hosted) -> Path:
        """Start the machine `hosted` says, detached, and return its socket once it answers; where it doesn't within `within`, stop it and start the last that came up again.

        Raise `LoaderError` where neither answers.
        """
        apart = await self.spawned(hosted)
        socket = self.places.socket()
        if await self.up(socket):
            came = Came(commit=hosted.commit, pid=apart.process.pid)
            self.places.record().write_bytes(came.model_dump_json().encode())
            return socket
        apart.end(timedelta(seconds=10))
        before = self.last()
        if before is None or before.commit == hosted.commit:
            message = (
                f"lup's machine didn't answer within {self.within}: what it said "
                f"is in {self.places.log()}"
            )
            raise LoaderError(message)
        sys.stderr.write(
            f"lup: the machine at {hosted.commit} didn't answer within "
            f"{self.within}, so the one at {before.commit} runs again; what it "
            f"said is in {self.places.log()}\n"
        )
        if before.commit is None:
            return await self.started(self.installed())
        again = hosted.host.model_copy(
            update={"root": hosted.host.root.with_name(before.commit)}
        )
        return await self.started(Hosted(commit=before.commit, host=again))

    def last(self) -> Came | None:
        """Return what came up last; none where nothing has."""
        record = self.places.record()
        if not record.is_file():
            return None
        return Came.model_validate_json(record.read_bytes())

    async def spawned(self, hosted: Hosted) -> Apart:
        """Start the program hosting the machine, detached: the installed `lup`'s own where `hosted` names no commit, else the commit's, in an environment of its own, synced first."""
        asked_for = f"LUP_ASKED={hosted.host.model_dump_json()}"
        if hosted.commit is None:
            return detached(
                "env",
                asked_for,
                sys.executable,
                "-m",
                "lup.environment.running",
                log=self.places.log(),
            )
        environment = self.places.data / "environments" / hosted.commit
        project = str(hosted.host.root)
        uses = f"UV_PROJECT_ENVIRONMENT={environment}"
        await awaited("env", uses, "uv", "sync", "--frozen", "--project", project)
        return detached(
            "env",
            uses,
            asked_for,
            "uv",
            "run",
            "--frozen",
            "--no-sync",
            "--project",
            project,
            "python",
            "-m",
            "lup.environment.running",
            log=self.places.log(),
        )

    async def up(self, socket: Path) -> bool:
        """Wait for the machine to answer on `socket`, asking every half second for `within` at most, and say whether it did."""

        def gave_up(state: RetryCallState) -> bool:
            del state
            return False

        waiting = AsyncRetrying(
            stop=stop_after_delay(self.within.total_seconds()),
            wait=wait_fixed(0.5),
            retry=retry_if_result(operator.not_),
            retry_error_callback=gave_up,
        )
        return await waiting(answering, socket)

    def stop(self) -> bool:
        """Stop the machine that came up last, asked to end, and say whether one was running."""
        came = self.last()
        if came is None:
            return False
        try:
            os.kill(came.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        return True
