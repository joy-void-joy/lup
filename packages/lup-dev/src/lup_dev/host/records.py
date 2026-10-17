"""Where a runtime keeps each session's record on this machine, as lup finds the ones of a repository.

Each runtime keeps its sessions' records in its own home, laid out its own way,
so only its adapter knows where they are and which session ran where. Given the
directories a repository's sessions run in, `Records.kept` answers which of the
runtime's records are theirs: each a file or a directory, and where it goes in a
copy, so a copy keeps the runtime's own layout. A record's session is read off
the record itself, the directory it says it ran in, never guessed from where the
runtime filed it.
"""

from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

from lup.types import Model


class Record(Model):
    """One of a runtime's records: a file or a directory it keeps, and where it goes in a copy."""

    source: Path
    place: PurePosixPath
    """Where it goes, under the copy of the runtime's records: its path in the
    runtime's own home."""


class Records(ABC):
    """A runtime's records of its sessions on this machine."""

    @abstractmethod
    def kept(self, under: list[Path]) -> list[Record]:
        """Return each record of a session the runtime ran in one of `under`, or in a directory inside one."""


def within(directory: Path, under: list[Path]) -> bool:
    """Say whether `directory` is one of `under`, or inside one.

    >>> within(Path("/w/lup.git/tree/dev"), [Path("/w/lup.git")])
    True
    >>> within(Path("/w/other"), [Path("/w/lup.git")])
    False
    """
    return any(directory.is_relative_to(each) for each in under)
