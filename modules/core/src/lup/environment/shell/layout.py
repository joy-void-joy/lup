"""Where the shell's environment side finds what it serves."""

from pathlib import Path

from lup.types import Model


class ShellLayout(Model):
    """Where the dashboard's page is: built beside this package by the page's build (`modules/core/page/vite.config.ts`), which git ignores."""

    page: Path = Path(__file__).resolve().parent.parent / "page"
    """The built page: `index.html` and its assets."""
