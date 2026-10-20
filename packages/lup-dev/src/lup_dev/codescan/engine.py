"""The typed engine's client: one warm engine per worktree, found or started on demand.

The engine (`packages/lup-dev/checker/`, `docs/judging-writes.md`, *The engine: one typed tree*) is a
long-lived Node process holding pyright's program for one worktree. Hooks are short
processes, so each finds the worktree's engine on its socket, starts it if none
answers, asks one question, and leaves it running for the next. An engine stops on
its own once unasked for a while, and stops at once for a client that expects
another build, so a rebuilt engine replaces the old one at the next request.

An engine is started with the project's runner's command for Python, which it runs
to name the worktree's interpreter, and the files deciding the environment, which
it watches (`EngineEnvironment`). Every request carries them too, so an engine
started with another runner is replaced as one from another build is.
"""

import json
import socket
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, override

from filelock import FileLock
from pydantic import TypeAdapter
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from lup.programs import ProgramError, run
from lup.types import Model
from lup_dev.codescan.contract import Checker, FileReport, Parser, Rule, Source
from lup_dev.declaration.resolve import Selected
from lup_dev.errors import LupDevError
from lup_dev.layout import Bundle, Layout

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.declaration.runner import Runner
    from lup_dev.settings import LupDevSettings


class EngineError(LupDevError):
    """The engine refused a request, or failed answering it."""


class EngineMissingError(EngineError):
    """The engine isn't built beside this `lup_dev`."""


class EngineGoneError(EngineError):
    """The engine stopped before it answered: idle, or from another build or runner."""


class EngineEnvironment(Model):
    """How the engine finds the worktree's environment, from the project's runner."""

    interpreter: list[str]
    """The command running the environment's Python, `Runner.judging(["python"])`:
    the engine runs it to name the interpreter."""
    files: list[str]
    """The files, from the root, whose change means another environment: the
    engine stamps them with pyright's own configuration, and builds another
    program when one changes."""

    @classmethod
    def of(cls, runner: Runner) -> EngineEnvironment:
        """Return the environment `runner` gives the engine."""
        return cls(interpreter=runner.judging(["python"]), files=runner.environment())


class EngineSource(Model):
    """A file to check, as the engine reads it."""

    path: str
    content: str | None


class CheckRequest(Model):
    """Check files with the selected rules."""

    op: Literal["check"] = "check"
    build: str
    environment: EngineEnvironment
    root: str
    rules: list[Selected]
    """Each module's rule selection, as the declaration records it: the engine
    resolves each against its table, refusing a name it doesn't hold, and runs
    their union."""
    sources: list[EngineSource]


class ImportersRequest(Model):
    """Re-check the files importing changed ones, for type errors."""

    op: Literal["importers"] = "importers"
    build: str
    environment: EngineEnvironment
    root: str
    changed: list[str]


class PlainRequest(Model):
    """A request asking `status` or `stop`, with what every request carries."""

    op: Literal["status", "stop"]
    build: str
    environment: EngineEnvironment


class EngineStatus(Model):
    """What a running engine says of itself."""

    root: str
    pid: int
    idle_seconds: float
    """How long it waits unasked before it stops."""
    files: int
    rss_bytes: int
    peak_rss_bytes: int


class Answer(Model):
    """The engine's answer to one request."""

    build: str
    stale: bool
    """The engine is from another build than asked for, and is stopping."""
    error: str | None
    """Why the engine refused the request, or how it failed."""
    reports: list[FileReport] | None
    rules: list[Rule] | None
    status: EngineStatus | None


class EngineChecker(Model, Checker):
    """lup's typed engine, one warm process per worktree, reached over its socket."""

    layout: Layout
    idle: timedelta
    """How long an engine this client starts waits unasked before it stops."""
    bundle: Bundle = Bundle()
    node: str = "node"
    """The Node executable that runs the engine."""
    timeout: timedelta = timedelta(minutes=10)
    """How long to wait for one answer, a whole project's first check included."""

    @classmethod
    def configured(cls, settings: LupDevSettings) -> EngineChecker:
        """Return the engine as this machine's settings place it."""
        return cls(layout=Layout.of(settings), idle=settings.lup_engine_idle)

    def script(self) -> Path:
        """Return the built engine's script, or say how to build it."""
        return built(self.bundle)

    @property
    def build(self) -> str:
        """Identify the built engine by its script's size and modification time.

        The engine reads the same file the same way, so an engine left running from
        an older build is told apart and replaced.
        """
        stat = self.script().stat()
        return f"{stat.st_size}-{stat.st_mtime_ns}"

    def rules(self, selected: list[Selected] | None = None) -> list[Rule]:
        """List the engine's rules, those `selected` chooses or its whole table, read from its table without loading a project.

        A selection goes to the engine's `rules` command on its input, a process
        of its own, as `parse`'s files do, so it costs Node's start whatever the
        worktree's engine is doing.
        """
        given = None if selected is None else SELECTIONS.dump_json(selected)
        return LISTED.validate_json(
            printed(self.node, self.bundle, "rules", stdin=given)
        )

    def check(
        self,
        root: Path,
        sources: list[Source],
        selected: list[Selected],
        runner: Runner,
    ) -> list[FileReport]:
        """Check files with the rules `selected` chooses, which the engine resolves.

        The engine refuses a selection naming a rule it doesn't hold, or dropping
        one that isn't there, naming those that are. It reads types in the
        environment `runner` gives the worktree.
        """
        request = CheckRequest(
            build=self.build,
            environment=EngineEnvironment.of(runner),
            root=str(root),
            rules=selected,
            sources=[
                EngineSource(path=str(source.path), content=source.content)
                for source in sources
            ],
        )
        return self.reports(self.ask(root, request))

    def importers(
        self, root: Path, changed: list[Path], runner: Runner
    ) -> list[FileReport]:
        """Re-check, for type errors, the files importing any of `changed`."""
        request = ImportersRequest(
            build=self.build,
            environment=EngineEnvironment.of(runner),
            root=str(root),
            changed=[str(path) for path in changed],
        )
        return self.reports(self.ask(root, request))

    def plain(self, op: Literal["status", "stop"], runner: Runner) -> PlainRequest:
        """Return a request asking `op` and nothing more, with `runner`'s environment.

        An engine started with another runner is told apart and replaced, as one
        from another build is.
        """
        return PlainRequest(
            op=op, build=self.build, environment=EngineEnvironment.of(runner)
        )

    def status(self, root: Path, runner: Runner) -> EngineStatus:
        """Ask the worktree's engine about itself, starting it if none runs."""
        answer = self.ask(root, self.plain("status", runner))
        if answer.status is None:
            message = "the engine answered `status` without one"
            raise EngineError(message)
        return answer.status

    def stop(self, root: Path, runner: Runner) -> None:
        """Stop the worktree's engine, if one runs.

        One started with a runner other than `runner` stops all the same, as
        stale.
        """
        path = self.layout.engine_socket(root)
        try:
            self.exchange(path, self.plain("stop", runner))
        except FileNotFoundError, ConnectionRefusedError, EngineGoneError:
            return

    def reports(self, answer: Answer) -> list[FileReport]:
        """Return an answer's reports, or say why there are none."""
        if answer.reports is None:
            message = "the engine answered without reports"
            raise EngineError(message)
        return answer.reports

    def ask(
        self, root: Path, request: CheckRequest | ImportersRequest | PlainRequest
    ) -> Answer:
        """Ask the worktree's engine, starting it first if none answers.

        An engine that stops while asked (idle, or from another build or runner)
        is started again, with the environment the request carries, and asked once
        more.
        """
        path = self.layout.engine_socket(root)
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            retry=retry_if_exception_type(EngineGoneError),
            reraise=True,
        ):
            with attempt:
                try:
                    answer = self.exchange(path, request)
                except FileNotFoundError, ConnectionRefusedError:
                    self.start(root, request.environment)
                    answer = self.exchange(path, request)
                if answer.error is not None:
                    raise EngineError(answer.error)
                return answer
        message = "the engine kept stopping before it answered"
        raise EngineError(message)

    def start(self, root: Path, environment: EngineEnvironment) -> None:
        """Start the worktree's engine, unless another client just did.

        Starting is done under a lock, so hooks running at once start one engine.
        The runner's command for Python and its environment's files go as JSON
        lists.
        """
        path = self.layout.engine_socket(root)
        store = self.layout.store(root)
        store.home.mkdir(parents=True, exist_ok=True)
        with FileLock(store.engine_lock):
            if answers(path):
                return
            self.run_engine(
                "start",
                "--root",
                str(root),
                "--socket",
                str(path),
                "--idle-seconds",
                str(self.idle.total_seconds()),
                "--interpreter",
                json.dumps(environment.interpreter),
                "--environment-files",
                json.dumps(environment.files),
                "--log",
                str(store.engine_log),
            )

    def run_engine(self, *arguments: str) -> str:
        """Run the engine's command line, and return what it printed."""
        return printed(self.node, self.bundle, *arguments).decode()

    def exchange(
        self, path: Path, request: CheckRequest | ImportersRequest | PlainRequest
    ) -> Answer:
        """Send one request on the engine's socket, and read its answer.

        An engine stopping as the request arrives closes the connection unanswered,
        which is the engine gone, to be started again: every request is safe to ask
        twice.
        """
        message = "the engine closed the connection without answering"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout.total_seconds())
            connection.connect(str(path))
            try:
                connection.sendall(request.model_dump_json().encode() + b"\n")
                line = connection.makefile("rb").readline()
            except (ConnectionResetError, BrokenPipeError) as gone:
                raise EngineGoneError(message) from gone
        if not line:
            raise EngineGoneError(message)
        answer = Answer.model_validate_json(line)
        if answer.stale:
            message = (
                f"the engine is from another build than {self.build}, or was "
                "started with another runner"
            )
            raise EngineGoneError(message)
        return answer


class ParsedSource(Model):
    """A file the engine's `parse` command reads: its path from the root, and its content."""

    path: str
    content: str


class EngineParser(Model, Parser):
    """lup's engine reading files from their parse alone: its `parse` command, a process of its own.

    It loads no project and reads no environment, so it costs Node's start and
    a parse, whichever worktree it's for and whatever its engine is doing,
    where a check pays the program's load and a type check (`docs/field-notes.md`,
    *Judging writes*).
    """

    bundle: Bundle = Bundle()
    node: str = "node"
    """The Node executable that runs the engine."""

    @override
    def parsed(self, root: Path, sources: list[Source]) -> list[FileReport]:
        given = [
            ParsedSource(
                path=str(source.path),
                content=(
                    (root / source.path).read_text()
                    if source.content is None
                    else source.content
                ),
            )
            for source in sources
        ]
        output = printed(self.node, self.bundle, "parse", stdin=PARSED.dump_json(given))
        reports = REPORTS.validate_json(output)
        if len(reports) != len(sources):
            message = (
                f"the engine's `parse` read {len(reports)} files of the "
                f"{len(sources)} it was given"
            )
            raise EngineError(message)
        return reports


PARSED = TypeAdapter(list[ParsedSource])
"""What the engine's `parse` command reads on its input."""

REPORTS = TypeAdapter(list[FileReport])
"""What it prints."""

SELECTIONS = TypeAdapter(list[Selected])
"""What the engine's `rules` command reads on its input, given a selection."""

LISTED = TypeAdapter(list[Rule])
"""What it prints: the rules chosen, or its whole table."""


def built(bundle: Bundle) -> Path:
    """Return the built engine's script, or say how to build it."""
    if not bundle.script.is_file():
        message = (
            f"the engine isn't built at {bundle.directory}: "
            "build it with `uv run packages/lup-dev/checker/build.py` "
            "from a checkout of lup"
        )
        raise EngineMissingError(message)
    return bundle.script


def printed(
    node: str, bundle: Bundle, *arguments: str, stdin: bytes | None = None
) -> bytes:
    """Run the engine's command line with `arguments`, `stdin` on its input, and return what it printed."""
    try:
        return run(node, str(built(bundle)), *arguments, stdin=stdin).output
    except ProgramError as failure:
        message = f"the engine's `{arguments[0]}` failed: {failure}"
        raise EngineError(message) from failure


def answers(path: Path) -> bool:
    """Say whether an engine listens on the socket at `path`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.connect(str(path))
        except FileNotFoundError, ConnectionRefusedError:
            return False
    return True
