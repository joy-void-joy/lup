"""pnpm, as lup knows it: a Node package manager installing a workspace from its own lockfile, which a module's requirement brings into a room."""

import math
from datetime import timedelta
from pathlib import Path
from typing import ClassVar, override

from lup_dev.declaration.package_managers.manager import (
    HomeSettings,
    PackageManager,
    Ungated,
)


class PnpmManager(PackageManager):
    """pnpm, keeping the package age in `~/.config/pnpm/config.yaml` as `minimumReleaseAge`, in minutes.

    pnpm 11 reads no package age from `~/.npmrc`, npm's or its own spelling,
    and checks even a frozen lockfile's entries against its own: a five-year age
    refused 777 of pyright's, installing nothing. A project's own
    `pnpm-workspace.yaml` outranks it (`docs/field-notes.md`, *pyright's source
    in the room's image*).

    >>> PnpmManager().aged(Path("/work"), timedelta(hours=36)).text.splitlines()[-1]
    'minimumReleaseAge: 2160'
    """

    package = "pnpm"
    settings: ClassVar[Path] = Path(".config/pnpm/config.yaml")
    """Where pnpm reads its user-level settings, from the home, where no
    `XDG_CONFIG_HOME` says otherwise."""
    lockfile: ClassVar[Path] = Path("pnpm-lock.yaml")
    """A workspace's lockfile, from its root."""
    workspace: ClassVar[Path] = Path("pnpm-workspace.yaml")
    """A workspace's own settings, from its root: its package age, which
    outranks the user's, among them."""
    modules: ClassVar[Path] = Path("node_modules")
    """Where a workspace's packages are installed, from its root."""
    installed: ClassVar[Path] = modules / ".pnpm" / "lock.yaml"
    """pnpm's copy of the lockfile a workspace's packages were installed from,
    from its root: written by an install that changes them, and left as it was
    by one finding them up to date."""

    @override
    def aged(self, root: Path, age: timedelta) -> HomeSettings | Ungated:
        """Return `~/.config/pnpm/config.yaml` holding `age` in minutes, rounded up so it's never laxer, whatever the project."""
        minutes = math.ceil(age / timedelta(minutes=1))
        return HomeSettings(
            path=self.settings,
            text=(
                "# lup's package age, from the declaration's `Core.package_age`: "
                "a project's own `pnpm-workspace.yaml` outranks it.\n"
                f"minimumReleaseAge: {minutes}\n"
            ),
        )

    def install(self, *arguments: str) -> list[str]:
        """Return the command installing the workspace it runs in from its lockfile as it stands, refusing to change it, with `arguments` after.

        pnpm runs the release the workspace's manifest names in its
        `packageManager`, fetching it, so a workspace installs with its own.

        >>> PnpmManager().install("--filter", "core")
        ['pnpm', 'install', '--frozen-lockfile', '--filter', 'core']
        """
        return ["pnpm", "install", "--frozen-lockfile", *arguments]

    def stale(self, root: Path) -> bool:
        """Say whether the workspace at `root` needs installing: its packages missing, or installed before its lockfile or its settings last changed.

        An install finding the packages up to date leaves pnpm's copy of the
        lockfile as it was, so a build reinstalls from scratch, its packages
        removed first, for the copy to be newer than both.
        """
        installed = root / self.installed
        if not installed.is_file():
            return True
        since = installed.stat().st_mtime
        return any(
            each.stat().st_mtime > since
            for each in [root / self.lockfile, root / self.workspace]
            if each.is_file()
        )
