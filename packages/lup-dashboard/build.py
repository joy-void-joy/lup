"""Build the dashboard's page: `uv run packages/lup-dashboard/build.py`, in lup.

1. Install the page's packages from its lockfile, where they're missing or older.
2. Describe the API from the server itself (`lup_dashboard.server`), and generate
   the page's types from that description, so the page and the host's models
   can't disagree.
3. Type-check the page and run its tests.
4. Build it into the dashboard's package (`lup_dashboard/page`), replacing the
   last build only once this one is whole.

The page is built, never committed: git ignores it, and the package carries it when
installed from a checkout that built it. The gate runs this step where one of its
sources is newer than the page (`LupDevelopment`, in `lup_project.py`).
"""

import json
import logging
import shutil
from pathlib import Path

from lup.programs import ProgramFailedError, run
from lup.types import Model
from lup_dashboard.host import Sockets
from lup_dashboard.layout import DashboardLayout
from lup_dashboard.server import Access, application
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings

log = logging.getLogger("build")


class Places(Model):
    """Where the build reads and writes."""

    project: Path = Path(__file__).resolve().parent / "page"
    """The page's own project: its sources, packages and configuration."""
    layout: DashboardLayout = DashboardLayout()

    @property
    def tools(self) -> Path:
        """The page's own Node tools."""
        return self.project / "node_modules" / ".bin"

    @property
    def described(self) -> Path:
        """The API's description, which the page's types are generated from."""
        return self.project / "openapi.json"

    @property
    def partial(self) -> Path:
        """Where the page is built before it replaces the last build."""
        return self.layout.page.with_name("page.partial")


def install(places: Places) -> None:
    """Install the page's packages from its lockfile, where they're missing or older than it."""
    lock = places.project / "package-lock.json"
    installed = places.project / "node_modules" / ".package-lock.json"
    if installed.is_file() and installed.stat().st_mtime >= lock.stat().st_mtime:
        return
    log.info("installing the page's packages")
    run("npm", "ci", "--no-audit", "--no-fund", cwd=places.project)


def describe(places: Places) -> None:
    """Write the API's description, as the server itself gives it."""
    described = application(
        Sockets(layout=Layout.of(LupDevSettings()).host), Access(token="", port=0), None
    )
    places.described.write_text(json.dumps(described.openapi(), indent=2) + "\n")


def build(places: Places) -> None:
    """Generate the page's types, type-check it, test it, and build it into the package."""
    log.info("generating the page's types from the API's description")
    run(
        places.tools / "openapi-typescript",
        str(places.described),
        "--output",
        "src/generated/api.ts",
        cwd=places.project,
    )
    log.info("type-checking the page")
    run(places.tools / "tsc", "--noEmit", cwd=places.project)
    log.info("testing the page")
    run(places.tools / "vitest", "run", cwd=places.project)
    log.info("building the page into %s", places.layout.page)
    shutil.rmtree(places.partial, ignore_errors=True)
    run(
        places.tools / "vite",
        "build",
        "--outDir",
        str(places.partial),
        "--emptyOutDir",
        "--logLevel",
        "warn",
        cwd=places.project,
    )
    shutil.rmtree(places.layout.page, ignore_errors=True)
    places.partial.rename(places.layout.page)


def main() -> None:
    """Build the page, or say what failed."""
    logging.basicConfig(level=logging.WARNING, format="build: %(message)s")
    log.setLevel(logging.INFO)
    places = Places()
    try:
        install(places)
        describe(places)
        build(places)
    except ProgramFailedError as failure:
        ran = failure.ran
        output = ran.output.decode(errors="replace") + ran.error.decode(
            errors="replace"
        )
        message = f"build: `{' '.join(ran.command)}` failed:\n{output}"
        raise SystemExit(message) from failure
    log.info("built %s", places.layout.page)


if __name__ == "__main__":
    main()
