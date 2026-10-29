"""What the judge needs to know about the runtime a session runs on.

The judge never names a runtime: each adapter (`lup_dev.adapters`) turns its
runtime's hooks into lup's own events and implements this interface, and only the
command line (`lup_dev.cli`) lists the adapters.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import PurePosixPath


# lup: ignore("interface-shape", why="the judge's one view of a runtime: four facts it reads of it, each a line; split, one runtime would fill two seams")
class Runtime(ABC):
    """One agent runtime, as the judge sees it."""

    @abstractmethod
    def name(self) -> str:
        """Return the runtime's name, as the verdict log and the store record it."""

    @abstractmethod
    def inside(self) -> bool:
        """Say whether this process runs inside one of the runtime's sessions.

        It reads the variables the runtime sets in the commands it runs, so that an
        agent can't answer their own hold by mistake.
        """

    @abstractmethod
    def fits(self) -> int:
        """Return the most a hook's answer tells the model whole, in bytes of UTF-8: past it, the runtime keeps the text in a file the model isn't asked to read."""

    @abstractmethod
    def settings(self) -> PurePosixPath:
        """Return the directory, from a worktree's root, holding the runtime's own settings for the project.

        What's there runs outside the agent's reach, so lup's default protected
        paths list it (`CorePaths.protected`), a project's declaration free to
        take it off; a test keeps that list in step with each adapter.
        """
