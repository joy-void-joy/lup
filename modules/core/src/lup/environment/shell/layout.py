"""Where the shell's environment side finds what it serves, and where the machine keeps the dashboard's."""

from pathlib import Path

from lup.types import Model


class ShellLayout(Model):
    """Where the dashboard's page is: its source in the core's directory, and the page built beside this package by the page's build (`modules/core/page/vite.config.ts`), which git ignores."""

    page: Path = Path(__file__).resolve().parent.parent / "page"
    """The built page: `index.html` and its assets."""
    source: Path = Path(__file__).resolve().parents[4] / "page"
    """The page's source, as git holds it: there where lup runs from a
    repository's files, as the machine runs the commit approved, and not in
    the installed `lup`, which ships none."""


class DashboardPlaces(Model):
    """Where the machine keeps the dashboard's: its token and draft, kept across restarts, and its address while it serves."""

    state: Path
    """Kept across restarts: `<state>/dashboard`."""
    runtime: Path
    """Kept while the machine runs, in memory: `<runtime>/dashboard`."""

    @classmethod
    def of(cls, state: Path, runtime: Path) -> DashboardPlaces:
        """Return the dashboard's places among the machine's `state` and `runtime`."""
        return cls(state=state / "dashboard", runtime=runtime / "dashboard")

    def token(self) -> Path:
        """Return the file holding the token a page says before anything is answered, readable by the operator alone."""
        return self.state / "token"

    def draft(self) -> Path:
        """Return the file the draft is kept in."""
        return self.state / "draft.json"

    def address(self) -> Path:
        """Return the file holding the dashboard's address with its token while it serves, which `lup` alone opens, readable by the operator alone."""
        return self.runtime / "address"
