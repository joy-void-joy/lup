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
from typing import TYPE_CHECKING

from pydantic import Field, TypeAdapter, ValidationError

from lup import Finished, Model, Program
from lup_code_rules.errors import LupCodeRulesError
from lup_code_rules.reports import FileReport, RuleInfo

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


class Sources(Model):
    """The engine's sources this package carries, and the pyright release they're built against."""

    directory: Path = Path(__file__).parent / "engine"
    release: str = Field(default_factory=lambda: importlib.metadata.version("pyright"))
    """pyright's release: the one the environment's `pyright` package is, so
    the engine answers as the pyright an editor runs there does."""
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
    """Return `finished` where its program succeeded; raise `LupCodeRulesError`, saying `what` failed and what it said, otherwise."""
    if finished.status == 0:
        return finished
    said = finished.said() or finished.text().strip()
    message = f"{what} failed, ending with status {finished.status}: {said}"
    raise LupCodeRulesError(message)


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

        Raise `LupCodeRulesError` where fetching pyright's source or building
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


class Source(Model):
    """A file to check: its path from the worktree's root, and its content where it isn't the disk's."""

    path: str
    content: str | None = None


class Asked(Model):
    """What a check asks of the engine: the rules to run, and the files."""

    rules: list[str]
    sources: list[Source]


def answered[T](finished: Finished, kind: type[T]) -> T:
    """Read what the engine printed as `kind`; raise `LupCodeRulesError` where it isn't, the engine being from another build than this package expects."""
    try:
        return TypeAdapter(kind).validate_json(finished.output)
    except ValidationError as unread:
        message = f"the engine answered what this package can't read: {unread}"
        raise LupCodeRulesError(message) from unread
