"""npm, as lup knows it: Node's package manager, which a module's requirement brings into a room."""

from datetime import timedelta
from pathlib import Path
from typing import ClassVar, override

from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)


class NpmManager(PackageManager):
    """npm, keeping the package age in `~/.npmrc` as `min-release-age`.

    >>> NpmManager().aged(Path("/work"), timedelta(hours=36)).text.splitlines()[-1]
    'min-release-age=1.5'
    """

    package = "npm"
    settings: ClassVar[Path] = Path(".npmrc")
    """Where npm reads its user-level settings, from the home."""

    @override
    def aged(self, root: Path, age: timedelta) -> HomeSettings | Ungated:
        """Return `~/.npmrc` holding `age` in days, a fraction among them, whatever the project.

        npm takes a fraction of a day, and keeps installing what a lock pins:
        `npm ci`, and `npm install` with the lock there, left a project's lock
        as it was (`docs/field-notes.md`, *User-level package age settings*).
        """
        days = age / timedelta(days=1)
        return HomeSettings(
            path=self.settings,
            text=(
                "; lup's package age, from the declaration's `Core.package_age`: "
                "a project's own `.npmrc` outranks it.\n"
                f"min-release-age={days}\n"
            ),
        )
