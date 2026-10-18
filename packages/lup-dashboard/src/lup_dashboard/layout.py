"""Where the dashboard's own files are."""

from pathlib import Path

from pydantic import Field

from lup.types import Model


class DashboardLayout(Model):
    """Where the dashboard's own files are: the built page, inside its package."""

    package: Path = Field(default_factory=lambda: Path(__file__).parent)
    """The package's directory, where it's installed."""

    @property
    def page(self) -> Path:
        """The built page, which the page's build writes (`packages/lup-dashboard/build.py`) and git ignores."""
        return self.package / "page"
