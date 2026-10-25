"""What lup needs of a package manager a room may hold: whether the room's image holds it, and the user-level settings keeping the package age.

A user-level setting rather than a variable: npm and uv each rank a variable
above a project's own setting and a user-level one below it, so a project with
its own, stricter or laxer, keeps it (measured with npm 12.0.2 and uv 0.12.5,
`docs/field-notes.md`, *User-level package age settings*). The launch writes
each into its own directory and mounts it read-only where the package manager
reads it in the room's home (`docs/launch.md`, *The package age gate*).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from lup.types import Model

if TYPE_CHECKING:
    from datetime import timedelta


class HomeSettings(Model):
    """A package manager's user-level settings for a room: where in the room's home it reads them, and their text."""

    path: Path
    """From the room's home."""
    text: str


class Ungated(Model):
    """Why a package manager gets no package age in a room, which the launch says."""

    why: str


class PackageManager(Model, ABC):
    """A package manager a room may hold, as lup knows it: its package, and how its user-level settings keep the package age."""

    package: ClassVar[str]
    """Its package in Arch Linux's repositories: a room holds it where its image
    does."""

    @abstractmethod
    def aged(self, root: Path, age: timedelta) -> HomeSettings | Ungated:
        """Return its user-level settings refusing what was published within `age`, for the project at `root`, or why it gets none there."""
