"""The typed engine's client: one warm engine per worktree, found or started on demand.

The engine (`packages/lup-dev/checker/`, `docs/judging-writes.md`, *The engine*) is a
long-lived Node process holding pyright's program for one worktree. Hooks are short
processes, so each finds the worktree's engine on its socket, starts it if none
answers, asks one question, and leaves it running for the next. An engine stops on
its own once unasked for a while, and stops at once for a client that expects
another build, so a rebuilt engine replaces the old one at the next request.
"""

import json
import socket
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import sh
from filelock import FileLock
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from lup.types import Model
from lup_dev.codescan.contract import Checker, FileReport, Rule, Source
from lup_dev.errors import LupDevError
from lup_dev.layout import Bundle, Layout

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.settings import LupDevSettings


class EngineError(LupDevError):
    """The engine refused a request, or failed answering it."""


class EngineMissingError(EngineError):
    """The engine isn't built beside this `lup_dev`."""


class EngineGoneError(EngineError):
    """The engine stopped before it answered: idle, or from another build."""


class EngineSource(Model):
    """A file to check, as the engine reads it."""

    path: str
    content: str | None


class CheckRequest(Model):
    """Check files with the selected rules."""

    op: Literal["check"] = "check"
    build: str
    root: str
    rules: list[str] | None
    """The rules to run, by id; none runs every rule the engine has."""
    sources: list[EngineSource]


class ImportersRequest(Model):
    """Re-check the files importing changed ones, for type errors."""

    op: Literal["importers"] = "importers"
    build: str
    root: str
    changed: list[str]


class PlainRequest(Model):
    """A request carrying nothing but what it asks: `status` or `stop`."""

    op: Literal["status", "stop"]
    build: str


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
    selected: list[str] | None = None
    """The rules to run, by id; none runs every rule the engine has."""
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
        if not self.bundle.script.is_file():
            message = (
                f"the engine isn't built at {self.bundle.directory}: "
                "build it with `uv run packages/lup-dev/checker/build.py` "
                "from a checkout of lup"
            )
            raise EngineMissingError(message)
        return self.bundle.script

    @property
    def build(self) -> str:
        """Identify the built engine by its script's size and modification time.

        The engine reads the same file the same way, so an engine left running from
        an older build is told apart and replaced.
        """
        stat = self.script().stat()
        return f"{stat.st_size}-{stat.st_mtime_ns}"

    def rules(self) -> list[Rule]:
        """List the engine's rules, read from its table without loading a project."""
        listed = self.run_engine("rules")
        return [Rule.model_validate(rule) for rule in json.loads(listed)]

    def check(self, root: Path, sources: list[Source]) -> list[FileReport]:
        """Check files with the selected rules; the engine refuses one it lacks."""
        request = CheckRequest(
            build=self.build,
            root=str(root),
            rules=self.selected,
            sources=[
                EngineSource(path=str(source.path), content=source.content)
                for source in sources
            ],
        )
        return self.reports(self.ask(root, request))

    def importers(self, root: Path, changed: list[Path]) -> list[FileReport]:
        """Re-check, for type errors, the files importing any of `changed`."""
        request = ImportersRequest(
            build=self.build, root=str(root), changed=[str(path) for path in changed]
        )
        return self.reports(self.ask(root, request))

    def status(self, root: Path) -> EngineStatus:
        """Ask the worktree's engine about itself, starting it if none runs."""
        answer = self.ask(root, PlainRequest(op="status", build=self.build))
        if answer.status is None:
            message = "the engine answered `status` without one"
            raise EngineError(message)
        return answer.status

    def stop(self, root: Path) -> None:
        """Stop the worktree's engine, if one runs."""
        path = self.layout.engine_socket(root)
        try:
            self.exchange(path, PlainRequest(op="stop", build=self.build))
        except FileNotFoundError, ConnectionRefusedError, EngineGoneError:
            return

    def reports(self, answer: Answer) -> list[FileReport]:
        """Return an answer's reports, or say why there are none."""
        if answer.reports is None:
            message = "the engine answered without reports"
            raise EngineError(message)
        return answer.reports

    def ask(self, root: Path, request: Model) -> Answer:
        """Ask the worktree's engine, starting it first if none answers.

        An engine that stops while asked (idle, or from another build) is started
        again, and asked once more.
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
                    self.start(root)
                    answer = self.exchange(path, request)
                if answer.error is not None:
                    raise EngineError(answer.error)
                return answer
        message = "the engine kept stopping before it answered"
        raise EngineError(message)

    def start(self, root: Path) -> None:
        """Start the worktree's engine, unless another client just did.

        Starting is done under a lock, so hooks running at once start one engine.
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
                "--log",
                str(store.engine_log),
            )

    def run_engine(self, *arguments: str) -> str:
        """Run the engine's command line, and return what it printed."""
        try:
            return str(sh.Command(self.node)(str(self.script()), *arguments))
        except sh.ErrorReturnCode as failure:
            message = f"the engine's `{arguments[0]}` failed: {failure.stderr.decode()}"
            raise EngineError(message) from failure

    def exchange(self, path: Path, request: Model) -> Answer:
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
            message = f"the engine is from another build than {self.build}"
            raise EngineGoneError(message)
        return answer


def answers(path: Path) -> bool:
    """Say whether an engine listens on the socket at `path`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.connect(str(path))
        except FileNotFoundError, ConnectionRefusedError:
            return False
    return True
