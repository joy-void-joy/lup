"""Build lup's typed engine: `uv run packages/lup-dev/checker/build.py`, in lup.

1. Read the pyright release the gate pins, from `uv.lock`, so the engine and the gate
   answer alike.
2. Find pyright's source at that release, with its dependencies installed, where
   this build reads it (`lup_dev/pyright_source.py`): on the host, lup's cache
   (`Layout.pyright_source`: `$XDG_CACHE_HOME/lup/pyright/`), which no room mounts;
   in a room, its image's copy, read-only, else its project's rooms' own
   directory. Where none holds it, fetch it there, once: clone the release and
   install its dependencies with pnpm, from its lockfile, held to the package age
   pnpm's own settings keep.
3. Link that source beside the engine as `pyright`, and install the engine's bundler
   with pnpm, from its own lockfile.
4. Type-check the engine and the rule table (`lup_dev/catalog/rules.ts`).
5. Bundle them into `lup_dev/codescan/bundle/engine.js`, with the standard-library
   stubs at the same release beside it.

The bundle is built, never committed: git ignores it, and the package carries it when
installed from a checkout that built it.
"""

import logging
import shutil
from pathlib import Path

from filelock import FileLock

from lup.programs import ProgramFailedError, ProgramMissingError, run
from lup.types import Model
from lup_dev.declaration.package_managers.pnpm import PnpmManager
from lup_dev.layout import Bundle, CheckoutLayout, Layout
from lup_dev.pyright_source import Fetching, PyrightSourceError, Sources, pinned
from lup_dev.settings import LupDevSettings

log = logging.getLogger("build")


class Places(Model):
    """Where the build reads and writes."""

    checker: Path = Path(__file__).resolve().parent
    bundle: Bundle = Bundle()

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

    @property
    def lock(self) -> Path:
        """The `uv.lock` pinning pyright's release."""
        return CheckoutLayout(root=self.root).lock


def fetch(sources: Sources, release: str) -> Path:
    """Fetch pyright's source at `release`, with its dependencies, where `sources` fetch, unless it's there whole.

    The fetch holds the place's lock, so two builds fetching at once, a room's
    two worktrees or two rooms of the project, don't clone over each other: the
    second finds the first's.
    """
    place = sources.fetched
    source = place.release(release)
    place.home.mkdir(parents=True, exist_ok=True)
    with FileLock(place.lock):
        if place.installed(release).is_file():
            return source
        log.info("%s", sources.why(release))
        fetching = Fetching(release=release)
        if not source.is_dir():
            partial = place.partial(release)
            shutil.rmtree(partial, ignore_errors=True)
            run(*fetching.clone(partial))
            partial.rename(source)
        log.info("installing pyright's dependencies with pnpm")
        downloads = place.downloads(release)
        try:
            run(*fetching.install(downloads), cwd=source)
        finally:
            shutil.rmtree(downloads.home, ignore_errors=True)
        place.installed(release).write_text(release + "\n")
    return source


def link(places: Places, source: Path) -> None:
    """Point the engine's `pyright` link at `source`."""
    if places.link.is_symlink() and places.link.resolve() == source.resolve():
        return
    places.link.unlink(missing_ok=True)
    places.link.symlink_to(source, target_is_directory=True)


def install_bundler(places: Places) -> None:
    """Install the engine's own tools from its lockfile, where they're missing or older than it or its settings.

    From scratch, its packages removed first (`PnpmManager.stale`): pnpm leaves
    in place what it didn't install, another package manager's say, which would
    resolve an import its lockfile doesn't hold.
    """
    pnpm = PnpmManager()
    if not pnpm.stale(places.checker):
        return
    log.info("installing the engine's bundler")
    shutil.rmtree(places.checker / pnpm.modules, ignore_errors=True)
    run(*pnpm.install(), cwd=places.checker)


def bundle(places: Places, source: Path) -> None:
    """Type-check the engine and its table, bundle them, and place the stubs beside."""
    log.info("type-checking the engine")
    run(
        source / "node_modules" / ".bin" / "tsc",
        "-p",
        str(places.checker / "tsconfig.json"),
    )
    target = places.bundle.script
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    log.info("bundling the engine into %s", target)
    run(
        places.tools / "esbuild",
        "src/main.ts",
        "--bundle",
        "--platform=node",
        "--target=node20",
        "--main-fields=module,main",
        "--tsconfig=tsconfig.json",
        f"--outfile={partial}",
        "--log-level=warning",
        cwd=places.checker,
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
    settings = LupDevSettings()
    sources = Sources.of(settings, Layout.of(settings))
    try:
        release = pinned(places.lock)
        source = sources.found(release) or fetch(sources, release)
        link(places, source)
        install_bundler(places)
        bundle(places, source)
    except (PyrightSourceError, ProgramMissingError) as failure:
        message = f"build: {failure}"
        raise SystemExit(message) from failure
    except ProgramFailedError as failure:
        ran = failure.ran
        output = ran.output.decode(errors="replace") + ran.error.decode(
            errors="replace"
        )
        message = f"build: `{' '.join(ran.command)}` failed:\n{output}"
        raise SystemExit(message) from failure
    log.info("built %s", places.bundle.script)


if __name__ == "__main__":
    main()
