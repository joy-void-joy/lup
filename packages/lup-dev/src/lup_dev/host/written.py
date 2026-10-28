"""What a host session of a runtime acts on in the operator's own directory, which every room could write before rooms had homes of their own: checked as it stands, for the operator to clean up (`docs/launch.md`, *Moving over*).

lup can't tell what a room wrote there from what the operator did: both write
as the operator's user, at times either could have chosen. So each runtime's
adapter says, item by item, what the directory holds that a host session runs,
loads, or acts on without asking, quoted for the operator to recognize as
theirs. It flags only what reads as planted whoever wrote it: a command naming
a directory rooms write, which runs what a room can change, and a link where
the runtime makes none. What it can't check, it says how to clear. Nothing is
followed through a link, nothing waited on, nothing changed.
"""

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from lup.rooms.homes import regular
from lup.types import Model

if TYPE_CHECKING:
    from pydantic import JsonValue


class Places(Model):
    """What a check of the operator's own directories needs: their home, to say each path from, and every directory rooms write."""

    home: Path
    written: list[Path]
    """The directories rooms write, or wrote: what a command running from one
    runs, a room could change."""

    def shown(self, path: Path) -> str:
        """Say `path` from the operator's home, as `~/…`, where it's in it.

        >>> from pathlib import Path
        >>> Places(home=Path("/h"), written=[]).shown(Path("/h/.agent/skills"))
        '~/.agent/skills'
        """
        if path.is_relative_to(self.home):
            return f"~/{path.relative_to(self.home)}"
        return str(path)

    def forms(self, place: Path) -> list[str]:
        """Return the ways a command may name `place`: its path, and from the home as `~/` and `$HOME/` spell it.

        >>> from pathlib import Path
        >>> Places(home=Path("/h"), written=[]).forms(Path("/h/.agent"))
        ['/h/.agent', '~/.agent', '$HOME/.agent', '${HOME}/.agent']
        """
        if not place.is_relative_to(self.home):
            return [str(place)]
        inside = place.relative_to(self.home)
        return [str(place), f"~/{inside}", f"$HOME/{inside}", f"${{HOME}}/{inside}"]

    def runs(self, command: str) -> bool:
        """Say whether `command` names a directory rooms write, so what it runs a room could change.

        >>> from pathlib import Path
        >>> places = Places(home=Path("/h"), written=[Path("/h/.agent"), Path("/w/lup.git")])
        >>> places.runs("bash ~/.agent/hooks/start.sh"), places.runs("notify-send done")
        (True, False)
        """
        return any(
            form in command for place in self.written for form in self.forms(place)
        )

    def aims(self, link: Path, aimed: str) -> bool:
        """Say whether the link at `link`, aimed at `aimed`, lands in a directory rooms write, read without following any link.

        >>> from pathlib import Path
        >>> places = Places(home=Path("/h"), written=[Path("/w/lup.git")])
        >>> places.aims(Path("/h/.agent/skills/x"), "/w/lup.git/tree/dev/skill")
        True
        """
        # lup: ignore("os-path", why="where a link aims, read without following any link on the way, which `Path.resolve` would")
        reached = os.path.normpath(link.parent / aimed)
        return any(
            reached == str(place) or reached.startswith(f"{place}/")
            for place in self.written
        )


class Checked(Model):
    """What a check of one runtime's directory found, a line each: what to check or clear, what needs nothing done, and how to replace the host login, said apart since a launch says it once."""

    found: list[str] = []
    """Each thing to check or clear, saying what to do."""
    fine: list[str] = []
    """Each thing looked at that needs nothing done as it stands."""
    login: str | None = None
    """How to replace the host login every room could read, where there's one."""

    def said(self) -> list[str]:
        """Say every line of it, what to act on first and the login last.

        >>> Checked(found=["`memory.md`: check it"], fine=["`plugins/`: none on"], login="log in again").said()
        ['`memory.md`: check it', '`plugins/`: none on', 'log in again']
        """
        return [*self.found, *self.fine, *([] if self.login is None else [self.login])]

    @classmethod
    def of(cls, parts: list[Checked], login: str | None = None) -> Checked:
        """Join what each part of a check found, in order, with the login's line.

        >>> Checked.of([Checked(found=["a"]), Checked(fine=["b"]), Checked(found=["c"])]).found
        ['a', 'c']
        """
        return cls(
            found=[line for each in parts for line in each.found],
            fine=[line for each in parts for line in each.fine],
            login=login,
        )


class Linked(Model):
    """A link found in the operator's directory, and where it's aimed, never followed."""

    path: Path
    aimed: str


class Listed(Model):
    """What a directory holds, walked without following a link: its files, and each link in it."""

    files: list[Path] = []
    links: list[Linked] = []


def listed(directory: Path) -> Listed:
    """Walk `directory`, never following a link, and return its files and each link in it; nothing where it isn't there, and itself where it's a link."""
    if directory.is_symlink():
        return Listed(links=[Linked(path=directory, aimed=str(directory.readlink()))])
    if not directory.is_dir():
        return Listed()
    entries = [
        root / name
        for root, folders, names in directory.walk()
        for name in [*folders, *names]
    ]
    return Listed(
        files=[each for each in entries if not each.is_symlink() and each.is_file()],
        links=[
            Linked(path=each, aimed=str(each.readlink()))
            for each in entries
            if each.is_symlink()
        ],
    )


def read(path: Path, largest: int = 4 << 20) -> bytes | None:
    """Read the file at `path` where it's a regular file of at most `largest` bytes, never through a link, never waiting on a pipe; none where it isn't one."""
    descriptor = regular(path)
    if descriptor is None:
        return None
    with open(descriptor, "rb") as file:
        if os.fstat(file.fileno()).st_size > largest:
            return None
        return file.read()


def held(path: Path) -> bool:
    """Say whether `path` is a regular file holding something, its link never followed: a login there."""
    try:
        seen = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(seen.st_mode) and seen.st_size > 0


def commands(value: JsonValue) -> list[str]:
    """Return every command `value` holds at any depth: each string under a key named `command`.

    >>> commands({"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]})
    ['say done']
    """
    match value:
        case {"command": str() as command, **rest}:
            return [
                command,
                *(each for item in rest.values() for each in commands(item)),
            ]
        case dict():
            return [each for item in value.values() for each in commands(item)]
        case list():
            return [each for item in value for each in commands(item)]
        case _:
            return []


def quoted(command: str, places: Places) -> str:
    """Quote a command a host session runs, flagged where it names a directory rooms write."""
    if places.runs(command):
        return (
            f"`{command}` (it names a directory rooms write: a room could change "
            "what it runs)"
        )
    return f"`{command}`"


def counted(count: int, one: str, many: str) -> str:
    """Say a count of things, `one` or `many` by it.

    >>> counted(1, "file", "files"), counted(3, "file", "files")
    ('1 file', '3 files')
    """
    return f"1 {one}" if count == 1 else f"{count} {many}"
