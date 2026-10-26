"""Each package manager a room may hold, as lup knows it: the only code that spells one.

Each module spells one package manager (`PackageManager`, `manager.py`): the
package that brings it into a room's image, and the user-level settings keeping
the package age there. uv's is beside `Uv`, lup's default runner, so everything
lup knows of uv is in one file. A launch writes the settings of each one its
room's image holds (`docs/launch.md`, *The package age gate*).
"""

from typing import TYPE_CHECKING

from lup_dev.declaration.package_managers.npm import NpmManager
from lup_dev.declaration.package_managers.pnpm import PnpmManager
from lup_dev.declaration.package_managers.uv import UvManager

if TYPE_CHECKING:
    from lup_dev.declaration.package_managers.manager import PackageManager

PACKAGE_MANAGERS: list[PackageManager] = [NpmManager(), PnpmManager(), UvManager()]
"""The package managers lup knows, which a launch asks for their settings."""
