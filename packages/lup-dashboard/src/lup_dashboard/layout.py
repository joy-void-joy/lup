"""Where the dashboard's own files are, and where its demo keeps a copy of the operator's dashboard state."""

from pathlib import Path

from pydantic import Field

from lup.types import Model
from lup_dev.layout import Layout


class DashboardLayout(Model):
    """Where the dashboard's own files are: the built page, inside its package."""

    package: Path = Field(default_factory=lambda: Path(__file__).parent)
    """The package's directory, where it's installed."""

    @property
    def page(self) -> Path:
        """The built page, which the page's build writes (`packages/lup-dashboard/build.py`) and git ignores."""
        return self.package / "page"


class CopyLayout(Model):
    """Where the demo keeps a copy of the operator's dashboard state (`lup_dashboard/copied.py`): a directory of its own, everything the copy's handlers write inside it."""

    home: Path

    @property
    def lup(self) -> Layout:
        """The places of lup's in the copy, each inside it, none left at its default on the machine: the host's state and runtime directory, laid out as the host keeps them, and the data, configuration and cache a handler or a module would write."""
        return Layout(
            state=self.home / "state",
            runtime=self.home / "run",
            data=self.home / "data",
            config=self.home / "config",
            cache=self.home / "cache",
        )

    def records(self, runtime: str) -> Path:
        """Say where the records of runtime `runtime` copied as they're read are kept, laid out as the home they're kept in on the host."""
        return self.home / "records" / runtime


def checkout(start: Path) -> Path | None:
    """Return the root of the checkout holding `start`, the nearest directory at or above it with a `.git` in it, a worktree's file or a clone's directory; none where there's none.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as scratch:
    ...     root = Path(scratch)
    ...     (root / ".git").touch()
    ...     (root / "packages").mkdir()
    ...     checkout(root / "packages") == root
    True
    """
    return next(
        (each for each in [start, *start.parents] if (each / ".git").exists()), None
    )
