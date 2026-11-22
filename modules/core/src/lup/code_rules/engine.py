"""lup's typed engine, built where it runs from the sources this package carries, and asked to check files.

The package carries the engine's TypeScript (`engine/`), never a build: a build
is pyright's own source at a release, the engine compiled against it and
bundled with esbuild, and the standard library's stubs beside it, which no
wheel should hold. So the engine is built where it first runs, in the
repository's git directory, which every worktree and room of it shares, named
by what its sources and pyright's release make it (`EngineLayout`), and found
there by every check after (`README.md` here, *The engine*).

A check runs the engine once, through `node` (`Engine.checked`): it loads the
project's program, as pyright's command line would, reads the worktree's
environment as files, and answers each file's report.
"""

import fcntl
import hashlib
import importlib.metadata
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, TypeAdapter, ValidationError

from lup import Finished, Model, Program
from lup.code_rules.errors import CodeRulesError
from lup.code_rules.reports import FileReport, RuleInfo

if TYPE_CHECKING:
    from collections.abc import Generator


class EngineLayout(Model):
    """Where the engine is built and pyright's source kept: in the repository's git directory, which every worktree and room of it shares, so a worktree just made, or a room just started, finds the engine built."""

    common: Path
    """The repository's git directory every worktree shares."""

    @property
    def cache(self) -> Path:
        """The directory the code rules keep their builds in."""
        return self.common / "lup" / "code-rules"

    @property
    def outcomes(self) -> Path:
        """The record of what became of each finding told after a write, a JSON object a line, for the next review of the rules."""
        return self.cache / "outcomes.jsonl"

    @property
    def lock(self) -> Path:
        """The lock a build holds, so two checks building at once don't build over each other."""
        return self.cache / "building.lock"

    def source(self, release: str) -> Path:
        """Return where pyright's source at `release` is kept, with its dependencies installed."""
        return self.cache / "pyright" / release

    def installed(self, release: str) -> Path:
        """Return the file saying pyright's source at `release` is there whole."""
        return self.cache / "pyright" / f"{release}.installed"

    def build(self, digest: str) -> Path:
        """Return where the engine whose sources and release `digest` names is built."""
        return self.cache / "engine" / digest

    def bundle(self, digest: str) -> Path:
        """Return the engine's bundle, beside the standard library's stubs it reads."""
        return self.build(digest) / "bundle" / "engine.js"


def installed_pyright(pinned: str) -> str:
    """Return the release of pyright the environment installs, or `pinned` where it installs none.

    The engine is built against it, so it answers as the pyright an editor
    runs there does; a project that installs no pyright gets the release the
    engine was written against.
    """
    try:
        return importlib.metadata.version("pyright")
    except importlib.metadata.PackageNotFoundError:
        return pinned


class Sources(Model):
    """The engine's sources this package carries, and the pyright release they're built against."""

    directory: Path = Path(__file__).parent / "engine"
    release: str = Field(default_factory=lambda: installed_pyright("1.1.414"))
    """pyright's release: the environment's `pyright` package's, else the one
    the engine was written against."""
    repository: str = "https://github.com/microsoft/pyright"
    """Where pyright's source is cloned from, at the release's tag."""

    def digest(self) -> str:
        """Return what names a build of these sources: every file's path and bytes, and the release."""
        hashed = hashlib.blake2b(self.release.encode(), digest_size=8)
        for file in sorted(self.directory.rglob("*")):
            if file.is_file():
                hashed.update(file.relative_to(self.directory).as_posix().encode())
                hashed.update(file.read_bytes())
        return hashed.hexdigest()


@contextmanager
def held(lock: Path) -> Generator[None]:
    """Hold `lock`, a file, for as long as the block runs, waiting for whoever holds it."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def succeeded(finished: Finished, what: str) -> Finished:
    """Return `finished` where its program succeeded; raise `CodeRulesError`, saying `what` failed and what it said, otherwise."""
    if finished.status == 0:
        return finished
    said = finished.said() or finished.text().strip()
    message = f"{what} failed, ending with status {finished.status}: {said}"
    raise CodeRulesError(message)


class Engine(Model):
    """The engine, built where it isn't yet, run through `node`, and its build through `git` and `pnpm`."""

    node: Program
    git: Program
    pnpm: Program
    layout: EngineLayout
    sources: Sources = Field(default_factory=Sources)
    environment_files: list[str] = [
        "pyproject.toml",
        "uv.lock",
        "uv.toml",
        ".python-version",
    ]
    """The files of a worktree whose change means another environment, which
    pyright's program is set up again for."""

    async def built(self) -> Path:
        """Return the engine's bundle, building it where it isn't there yet.

        Raise `CodeRulesError` where fetching pyright's source or building
        fails, saying which step and what it said.
        """
        digest = self.sources.digest()
        bundle = self.layout.bundle(digest)
        if bundle.is_file():
            return bundle
        with held(self.layout.lock):
            if bundle.is_file():
                return bundle
            source = await self.fetched()
            await self.compiled(digest, source)
        return bundle

    async def fetched(self) -> Path:
        """Return pyright's source at the release, with its dependencies, fetching it where it isn't there whole."""
        release = self.sources.release
        source = self.layout.source(release)
        if self.layout.installed(release).is_file():
            return source
        shutil.rmtree(source, ignore_errors=True)
        source.parent.mkdir(parents=True, exist_ok=True)
        succeeded(
            await self.git.ran(
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--branch",
                release,
                self.sources.repository,
                str(source),
            ),
            f"cloning pyright {release}",
        )
        succeeded(
            await self.pnpm.ran(
                "install",
                "--frozen-lockfile",
                "--filter",
                "pyright-internal",
                cwd=source,
            ),
            f"installing pyright {release}'s dependencies",
        )
        self.layout.installed(release).write_text(release + "\n")
        return source

    async def compiled(self, digest: str, source: Path) -> None:
        """Build the engine named `digest` from its sources against pyright's `source`: type-checked, bundled, and the stubs beside it."""
        build = self.layout.build(digest)
        shutil.rmtree(build, ignore_errors=True)
        build.parent.mkdir(parents=True, exist_ok=True)
        self.sources.directory.copy(build)
        (build / "pyright").symlink_to(source, target_is_directory=True)
        succeeded(
            await self.pnpm.ran("install", "--frozen-lockfile", cwd=build),
            "installing the engine's bundler",
        )
        compiler = source / "node_modules" / "typescript" / "lib" / "tsc.js"
        succeeded(
            await self.node.ran(str(compiler), "-p", "tsconfig.json", cwd=build),
            "type-checking the engine",
        )
        bundle = self.layout.bundle(digest)
        bundle.parent.mkdir(parents=True, exist_ok=True)
        partial = bundle.with_name("partial.js")
        succeeded(
            await self.node.ran(
                str(build / "node_modules" / "esbuild" / "bin" / "esbuild"),
                "src/main.ts",
                "--bundle",
                "--platform=node",
                "--target=node22",
                "--main-fields=module,main",
                "--tsconfig=tsconfig.json",
                f"--outfile={partial}",
                "--log-level=warning",
                cwd=build,
            ),
            "bundling the engine",
        )
        stubs = source / "packages" / "pyright-internal" / "typeshed-fallback"
        stubs.copy(bundle.parent / "typeshed-fallback")
        # Moved into place last, so a bundle that's there is whole.
        partial.replace(bundle)

    async def rules(self) -> list[RuleInfo]:
        """Return every rule of the engine's table, in its order."""
        bundle = await self.built()
        listed = succeeded(
            await self.node.ran(str(bundle), "rules"), "listing the engine's rules"
        )
        return answered(listed, list[RuleInfo])

    async def comments(self, written: list[Written]) -> list[list[LupComment]]:
        """Return each TypeScript file's `// lup:` comments, in the order given, found with TypeScript's own parser, so a `//` in a string or a regular expression is never one."""
        bundle = await self.built()
        found = succeeded(
            await self.node.ran(
                str(bundle),
                "comments",
                given=TypeAdapter(list[Written]).dump_json(written).decode(),
            ),
            "reading TypeScript's `// lup:` comments",
        )
        return answered(found, list[list[LupComment]])

    async def checked(
        self, root: Path, venv: Path, rules: list[str], sources: list[Source]
    ) -> list[FileReport]:
        """Check `sources` in the worktree at `root`, its environment at `venv`, with lup's `rules` by name: each file's report, in the order given.

        Each file is read as it stands on disk, or as its `content` where
        that's given, a write not landed yet.
        """
        bundle = await self.built()
        asked = Asked(rules=rules, sources=sources)
        checked = succeeded(
            await self.node.ran(
                str(bundle),
                "check",
                "--root",
                str(root),
                "--venv",
                TypeAdapter(str).dump_json(str(venv)).decode(),
                "--environment-files",
                TypeAdapter(list[str]).dump_json(self.environment_files).decode(),
                given=asked.model_dump_json(),
                cwd=root,
            ),
            "checking with the engine",
        )
        return answered(checked, list[FileReport])


class Written(Model):
    """A file's text, by its path: what the engine reads with no project loaded."""

    path: str
    content: str


class LupComment(Model):
    """A TypeScript file's `// lup:` comment, as the engine finds it with TypeScript's own parser: where it is, what it says after `lup:`, and the line an `ignore` there keeps."""

    line: int
    column: int
    body: str
    covers: int


class Source(Model):
    """A file to check: its path from the worktree's root, and its content where it isn't the disk's."""

    path: str
    content: str | None = None


class Asked(Model):
    """What a check asks of the engine: the rules to run, and the files."""

    rules: list[str]
    sources: list[Source]


def answered[T](finished: Finished, kind: type[T]) -> T:
    """Read what the engine printed as `kind`; raise `CodeRulesError` where it isn't, the engine being from another build than this package expects."""
    try:
        return TypeAdapter(kind).validate_json(finished.output)
    except ValidationError as unread:
        message = f"the engine answered what this package can't read: {unread}"
        raise CodeRulesError(message) from unread


class Environment(Model):
    """The environment a warm engine reads, as each request names it: its directory, and the files whose change means another."""

    venv: str
    files: list[str]


class Asking(Model):
    """A check asked of a warm engine, as its socket takes it."""

    op: Literal["check"] = "check"
    build: str
    environment: Environment
    root: str
    rules: list[str]
    sources: list[Source]


class Passing(Model):
    """An importers pass asked of a warm engine: the files importing those changed, re-checked for type errors, a step at a time between checks."""

    op: Literal["importers"] = "importers"
    build: str
    environment: Environment
    root: str
    changed: list[str]


class Answer(Model):
    """A warm engine's answer: the reports, or that it's from another build or another environment and stopped, or why it refused."""

    build: str
    stale: bool = False
    error: str | None = None
    reports: list[FileReport] | None = None


class WarmEngine(Model):
    """The engine kept running for one worktree, on a socket, so each check after the first costs what pyright's re-check of the files does rather than a load of the project: what's told after each write asks.

    Each request goes through the engine's client, a small script `node` runs
    (`engine/client.mjs`), so the socket is reached through a program, which a
    promise stands in for, as every program a part runs.
    """

    engine: Engine
    root: Path
    venv: Path
    socket: Path
    """Where it listens: a path short enough for a socket's, 108 bytes."""
    log: Path
    """Where it says what it does, which nothing else shows."""
    idle: int = 1800
    """How long, in seconds, it waits with nothing asked before it stops."""

    async def checked(
        self, rules: list[str], sources: list[Source]
    ) -> list[FileReport]:
        """Check `sources` with lup's `rules` by name, starting the engine where none answers, and again where one from another build or environment stopped.

        Raise `CodeRulesError` where it can't start, or refuses.
        """
        bundle = await self.engine.built()
        build = stamped(bundle)
        for _ in range(2):
            await self.started(bundle)
            asking = Asking(
                build=build,
                environment=self.environment(),
                root=str(self.root),
                rules=rules,
                sources=sources,
            )
            answer = await self.asked(asking)
            if answer.error is not None:
                message = f"the engine refused a check: {answer.error}"
                raise CodeRulesError(message)
            if not answer.stale:
                return answer.reports or []
        message = "the engine kept answering from another build or environment"
        raise CodeRulesError(message)

    async def started(self, bundle: Path) -> None:
        """Make sure an engine answers on the socket, starting one detached where none does."""
        self.socket.parent.mkdir(parents=True, exist_ok=True)
        environment = self.environment()
        succeeded(
            await self.engine.node.ran(
                str(bundle),
                "start",
                "--root",
                str(self.root),
                "--socket",
                str(self.socket),
                "--idle-seconds",
                str(self.idle),
                "--venv",
                TypeAdapter(str).dump_json(environment.venv).decode(),
                "--environment-files",
                TypeAdapter(list[str]).dump_json(environment.files).decode(),
                "--log",
                str(self.log),
            ),
            "starting the engine",
        )

    def environment(self) -> Environment:
        """Return the environment the engine reads, as a request names it."""
        return Environment(venv=str(self.venv), files=self.engine.environment_files)

    async def importers(self, changed: list[str]) -> list[FileReport]:
        """Re-check, for type errors, the worktree's files importing those `changed`, directly or through others, and return each one's report.

        Raise `CodeRulesError` where the engine can't start, or refuses.
        """
        bundle = await self.engine.built()
        build = stamped(bundle)
        await self.started(bundle)
        passing = Passing(
            build=build,
            environment=self.environment(),
            root=str(self.root),
            changed=changed,
        )
        answer = await self.asked(passing)
        if answer.error is not None or answer.stale:
            message = f"the engine refused an importers pass: {answer.error or 'it was from another build'}"
            raise CodeRulesError(message)
        return answer.reports or []

    async def asked(self, asking: Asking | Passing) -> Answer:
        """Ask the engine on the socket what `asking` asks, through the engine's client run by `node`, and return its answer."""
        client = self.engine.sources.directory / "client.mjs"
        said = succeeded(
            await self.engine.node.ran(
                str(client), str(self.socket), given=asking.model_dump_json()
            ),
            "asking the engine",
        )
        try:
            return Answer.model_validate_json(said.output)
        except ValidationError as unread:
            message = f"the engine answered what this package can't read: {unread}"
            raise CodeRulesError(message) from unread


def stamped(bundle: Path) -> str:
    """Return what names the engine's build its bundle is, as the engine names its own: the bundle's size and when it was written, which a check names, so an engine from another build stops rather than answering."""
    stat = bundle.stat()
    return f"{stat.st_size}-{stat.st_mtime_ns}"
