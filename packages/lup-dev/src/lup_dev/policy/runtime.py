"""What the judge needs to know about the runtime a session runs on.

The judge never names a runtime: each adapter (`lup_dev.adapters`) turns its
runtime's hooks into lup's own events and implements this interface, and only the
command line (`lup_dev.cli`) lists the adapters.
"""

from abc import ABC, abstractmethod


class Runtime(ABC):
    """One agent runtime, as the judge sees it."""

    @abstractmethod
    def name(self) -> str:
        """Return the runtime's name, as the verdict log and the store record it."""

    @abstractmethod
    def inside(self) -> bool:
        """Say whether this process runs inside one of the runtime's sessions.

        It reads the variables the runtime sets in the commands it runs, so that an
        agent can't answer its own hold by mistake.
        """
