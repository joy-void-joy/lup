"""Build lup's typed engine: `uv run packages/lup-dev/checker/build.py`, in lup.

1. Read the pyright release the gate pins, from `uv.lock`, so the engine and the gate
   answer alike.
2. Fetch pyright's source at that release into `$XDG_CACHE_HOME/lup/pyright/`, once,
   and install its dependencies with the pnpm release pyright's own manifest names.
3. Link that source beside the engine as `pyright`, and install the engine's bundler.
4. Type-check the engine and the rule table (`lup_dev/catalog/rules.ts`).
5. Bundle them into `lup_dev/codescan/bundle/engine.js`, with the standard-library
   stubs at the same release beside it.

The bundle is built, never committed: git ignores it, and the package carries it when
installed from a checkout that built it.
"""

import logging
import shutil
import tomllib
from pathlib import Path

import sh
from pydantic import Field

from lup.types import Model, Settings
from lup_dev.layout import Bundle

log = logging.getLogger("build")


class BuildSettings(Settings):
    """The environment variables the build reads."""

    xdg_cache_home: Path | None = None
    """`XDG_CACHE_HOME`, where pyright's source is kept between builds."""


class Locked(Model):
    """One package `uv.lock` pins."""

    name: str
    version: str | None = None


class Lock(Model):
    """The part of `uv.lock` the build reads."""

    package: list[Locked]


class Manifest(Model):
    """The part of pyright's `package.json` the build reads."""

    package_manager: str = Field(alias="packageManager")
    """The pnpm release pyright installs with, as `pnpm@<version>`."""


class Places(Model):
    """Where the build reads and writes."""

    checker: Path = Path(__file__).resolve().parent
    bundle: Bundle = Bundle()
    repository: str = "https://github.com/microsoft/pyright"
    """Where pyright's source is fetched from."""

    @property
    def root(self) -> Path:
        """The checkout of lup the build runs in."""
        return self.checker.parents[2]

    @property
    def link(self) -> Path:
        """The engine's link to pyright's source, which its `tsconfig.json` reads."""
        return self.checker / "pyright"

    @property
    def tools(self) -> Path:
        """The engine's own Node tools, its bundler among them."""
        return self.checker / "node_modules" / ".bin"

    def cache(self, settings: BuildSettings) -> Path:
        """Return where pyright's sources are kept, one directory per release."""
        home = settings.xdg_cache_home or Path.home() / ".cache"
        return home / "lup" / "pyright"


def pinned(places: Places) -> str:
    """Return the pyright release `uv.lock` pins, which the gate runs."""
    lock = Lock.model_validate(tomllib.loads((places.root / "uv.lock").read_text()))
    releases = [p.version for p in lock.package if p.name == "pyright" and p.version]
    if len(releases) != 1:
        message = f"`uv.lock` pins pyright {len(releases)} times, not once"
        raise SystemExit(message)
    return releases[0]


def fetch(release: str, cache: Path, repository: str) -> Path:
    """Fetch pyright's source at `release`, with its dependencies, unless kept."""
    source = cache / release
    installed = source / ".lup-installed"
    if installed.is_file():
        return source
    if not source.is_dir():
        log.info("fetching pyright %s", release)
        cache.mkdir(parents=True, exist_ok=True)
        partial = cache / f"{release}.partial"
        shutil.rmtree(partial, ignore_errors=True)
        sh.git(
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            release,
            repository,
            str(partial),
        )
        partial.rename(source)
    manifest = Manifest.model_validate_json((source / "package.json").read_text())
    log.info("installing pyright's dependencies with %s", manifest.package_manager)
    sh.npm(
        "exec",
        "--yes",
        manifest.package_manager,
        "--",
        "install",
        "--frozen-lockfile",
        "--filter",
        "pyright-internal",
        _cwd=str(source),
    )
    installed.write_text(release + "\n")
    return source


def link(places: Places, source: Path) -> None:
    """Point the engine's `pyright` link at `source`."""
    if places.link.is_symlink() and places.link.resolve() == source.resolve():
        return
    places.link.unlink(missing_ok=True)
    places.link.symlink_to(source, target_is_directory=True)


def install_bundler(places: Places) -> None:
    """Install the engine's own tools from its lockfile, when they're missing or old."""
    lock = places.checker / "package-lock.json"
    installed = places.checker / "node_modules" / ".package-lock.json"
    if installed.is_file() and installed.stat().st_mtime >= lock.stat().st_mtime:
        return
    log.info("installing the engine's bundler")
    sh.npm("ci", "--no-audit", "--no-fund", _cwd=str(places.checker))


def bundle(places: Places, source: Path) -> None:
    """Type-check the engine and its table, bundle them, and place the stubs beside."""
    log.info("type-checking the engine")
    sh.Command(str(source / "node_modules" / ".bin" / "tsc"))(
        "-p", str(places.checker / "tsconfig.json")
    )
    target = places.bundle.script
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    log.info("bundling the engine into %s", target)
    sh.Command(str(places.tools / "esbuild"))(
        "src/main.ts",
        "--bundle",
        "--platform=node",
        "--target=node20",
        "--main-fields=module,main",
        "--tsconfig=tsconfig.json",
        f"--outfile={partial}",
        "--log-level=warning",
        _cwd=str(places.checker),
    )
    stubs = source / "packages" / "pyright-internal" / "typeshed-fallback"
    shutil.rmtree(places.bundle.stubs, ignore_errors=True)
    stubs.copy(places.bundle.stubs)
    # Replaced last and at once, so a running engine sees the rebuilt bundle only whole.
    partial.replace(target)


def main() -> None:
    """Build the engine, or say what failed."""
    logging.basicConfig(level=logging.WARNING, format="build: %(message)s")
    log.setLevel(logging.INFO)
    places = Places()
    try:
        source = fetch(pinned(places), places.cache(BuildSettings()), places.repository)
        link(places, source)
        install_bundler(places)
        bundle(places, source)
    except sh.ErrorReturnCode as failure:
        output = failure.stdout.decode() + failure.stderr.decode()
        message = f"build: {failure.full_cmd} failed:\n{output}"
        raise SystemExit(message) from failure
    log.info("built %s", places.bundle.script)


if __name__ == "__main__":
    main()
