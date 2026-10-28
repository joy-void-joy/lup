"""A runtime's configuration as a room gets it: layers merged, and what credentials it holds left out (`docs/launch.md`, *A home of the rooms' own*).

Each runtime's adapter reads its settings file from each layer, the operator's
own and a profile's over it, merges them (`merged`), and leaves out what would
hand a room's code a credential (`withheld`): the keys its adapter names, a
credential helper's command among them, and any key at any depth named like a
credential (`Credentials.named`). A wrong cut breaks a room, never the host:
the host only copies what's left, and never runs it.
"""

import stat
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue

from lup.rooms.container import Mount
from lup.sessions.terminal import Copy, Syntax, TerminalError, parsed, read
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from collections.abc import Callable


class Pair(Model):
    """Two words in a row naming a credential together, where neither does alone."""

    first: str
    second: str


def words(key: str) -> list[str]:
    """Return the words of a key, however it's spelled: camel case, snake case, kebab case, or a variable's capitals.

    >>> words("apiKeyHelper"), words("experimental_bearer_token"), words("X-Api-Key")
    (['api', 'key', 'helper'], ['experimental', 'bearer', 'token'], ['x', 'api', 'key'])
    >>> words("OPENAI_API_KEY"), words("includeCoAuthoredBy")
    (['openai', 'api', 'key'], ['include', 'co', 'authored', 'by'])
    """
    found: list[str] = []
    current = ""
    for at, char in enumerate(key):
        if not char.isalnum():
            found = [*found, current] if current else found
            current = ""
            continue
        before = key[at - 1] if at else ""
        after = key[at + 1] if at + 1 < len(key) else ""
        starts = char.isupper() and (
            before.islower() or (before.isupper() and after.islower())
        )
        if starts and current:
            found = [*found, current]
            current = ""
        current += char.lower()
    return [*found, current] if current else found


class Credentials(Model):
    """What names a credential in a key: a word of its own, or two in a row."""

    words: list[str] = [
        "auth",
        "oauth",
        "authorization",
        "token",
        "tokens",
        "secret",
        "secrets",
        "password",
        "passwords",
        "passwd",
        "passphrase",
        "credential",
        "credentials",
        "bearer",
        "cookie",
        "cookies",
        "apikey",
    ]
    pairs: list[Pair] = [
        Pair(first="api", second="key"),
        Pair(first="private", second="key"),
        Pair(first="access", second="key"),
        Pair(first="session", second="key"),
    ]

    def named(self, key: str) -> bool:
        """Say whether `key` is named like a credential.

        >>> [Credentials().named(key) for key in ["apiKeyHelper", "awsAuthRefresh", "includeCoAuthoredBy", "forceLoginMethod"]]
        [True, True, False, False]
        """
        said = words(key)
        return any(each in self.words for each in said) or any(
            Pair(first=first, second=second) in self.pairs
            for first, second in pairwise(said)
        )


def merged(lower: JsonObject, upper: JsonObject) -> JsonObject:
    """Return `upper` laid over `lower`: tables merged key by key, at every depth, and any other value of `upper`'s, a list among them, in place of `lower`'s.

    >>> merged({"a": {"b": 1, "c": [1]}, "d": 1}, {"a": {"c": [2]}})
    {'a': {'b': 1, 'c': [2]}, 'd': 1}
    """
    both = {**lower, **upper}
    return {
        key: merged(below, above)
        if isinstance(below := lower.get(key), dict)
        and isinstance(above := upper.get(key), dict)
        else value
        for key, value in both.items()
    }


class Withheld(Model):
    """A runtime's configuration with what would hand a room a credential left out, and what was."""

    kept: JsonValue
    left: list[str] = []
    """Each key left out, dotted from the top, a list's entry by its place."""


def withheld(
    value: JsonValue,
    blocked: Callable[[list[str]], bool],
    path: list[str] | None = None,
    credentials: Credentials | None = None,
) -> Withheld:
    """Leave out of `value` each key `blocked` says of its path, and each named like a credential, at every depth, tables in lists among it.

    >>> def blocked(path: list[str]) -> bool:
    ...     return path == ["env"]
    >>> withheld({"env": {"A": "1"}, "hooks": [{"token": "x", "type": "c"}], "model": "opus"}, blocked)
    Withheld(kept={'hooks': [{'type': 'c'}], 'model': 'opus'}, left=['env', 'hooks.0.token'])
    """
    at = path or []
    naming = credentials or Credentials()
    match value:
        case dict():
            cut = {
                key: [*at, key]
                for key in value
                if blocked([*at, key]) or naming.named(key)
            }
            inner = {
                key: withheld(each, blocked, [*at, key], naming)
                for key, each in value.items()
                if key not in cut
            }
            return Withheld(
                kept={key: each.kept for key, each in inner.items()},
                left=[
                    *(".".join(each) for each in cut.values()),
                    *(left for each in inner.values() for left in each.left),
                ],
            )
        case list():
            inner_list = [
                withheld(each, blocked, [*at, str(place)], naming)
                for place, each in enumerate(value)
            ]
            return Withheld(
                kept=[each.kept for each in inner_list],
                left=[left for each in inner_list for left in each.left],
            )
        case _:
            return Withheld(kept=value)


def kept(table: JsonObject, blocked: Callable[[list[str]], bool]) -> Layered:
    """Leave out of the table `table` what `withheld` does, returning a table.

    >>> kept({"apiKeyHelper": "x", "model": "opus"}, lambda path: False).table
    {'model': 'opus'}
    """
    cut = withheld(table, blocked)
    match cut.kept:
        case dict() as remaining:
            return Layered(table=remaining, left=cut.left)
        case _:
            return Layered(left=cut.left)


class Item(Model):
    """One item of a runtime's configuration in its home, read-only there: a file or a directory by its name in the home."""

    name: str
    directory: bool = True
    leaving: list[str] = []
    """Names directly inside a directory left out of its copy: what isn't
    configuration, such as plugins' own data."""


class HomeLaunch(Model):
    """What a launch keeps of its own for a runtime's home, under its directory: the copies, the empty files and directories mounted where nothing is copied, and what the runtime writes for this launch alone."""

    directory: Path

    def copied(self, name: str) -> Path:
        """Say where item `name` of the configuration is copied."""
        return self.directory / "configuration" / name

    def own(self, name: str) -> Path:
        """Say where `name`, a file or a directory the runtime writes for this launch alone, is kept."""
        return self.directory / "launch" / name

    @property
    def empty_directory(self) -> Path:
        """An empty directory, mounted read-only where no layer holds a directory of configuration."""
        return self.directory / "empty" / "directory"

    @property
    def empty_file(self) -> Path:
        """An empty file, mounted read-only where no layer holds a file of configuration."""
        return self.directory / "empty" / "file"


class Layered(Model):
    """A settings file read from each layer, what would hand a room a credential left out of each, and merged; with what was left out."""

    table: JsonObject = {}
    left: list[str] = []
    """Each key left out, with the file it was in, and each layer's file that
    couldn't be read as one."""


def layered(
    layers: list[Path],
    name: str,
    syntax: Syntax,
    blocked: Callable[[list[str]], bool],
) -> Layered:
    """Read the settings file `name` in each of `layers`, lowest first, leave out of each what `kept` does with `blocked`, and merge them.

    One that isn't there is no layer; one that's a link, or isn't a file, is
    left out and said, never followed. Raise `TerminalError` where one
    doesn't parse.
    """
    found = Layered()
    for layer in layers:
        path = layer / name
        try:
            seen = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(seen.st_mode):
            found = found.model_copy(
                update={"left": [*found.left, f"{path}, which isn't a file"]}
            )
            continue
        try:
            table = parsed(read(path), syntax)
        except ValueError as failed:
            message = f"{path} doesn't read as {syntax}: {failed}"
            raise TerminalError(message) from failed
        cut = kept(table, blocked)
        found = Layered(
            table=merged(found.table, cut.table),
            left=[*found.left, *(f"`{key}` in {path}" for key in cut.left)],
        )
    return found


class Homed(Model):
    """What a terminal compile adds for a runtime's home of the rooms' own: the copies and directories to make first, and the mounts."""

    copies: list[Copy] = []
    directories: list[Path] = []
    files: dict[Path, str] = {}
    mounts: list[Mount] = []
    left: list[str] = []


def configured(
    items: list[Item], layers: list[Path], home: Path, launch: HomeLaunch
) -> Homed:
    """Return how each of `items` reaches the home at `home`, read-only: the launch's copy of each layer holding it, lowest first, or the launch's empty file or directory where none does.

    A layer's item that's a link, or isn't of its kind, is left out and said,
    never followed: a room that once wrote the layer could have left one
    aimed at the operator's keys.
    """

    def holding(item: Item) -> list[Path]:
        return [
            layer / item.name
            for layer in layers
            if fits(layer / item.name, directory=item.directory)
        ]

    def odd(item: Item) -> list[str]:
        return [
            f"{layer / item.name}, which is a link lup doesn't follow"
            if (layer / item.name).is_symlink()
            else f"{layer / item.name}, which isn't a {'directory' if item.directory else 'file'}"
            for layer in layers
            if (layer / item.name).is_symlink()
            or (
                (layer / item.name).exists()
                and not fits(layer / item.name, directory=item.directory)
            )
        ]

    copies = [
        Copy(source=source, destination=launch.copied(item.name), leaving=item.leaving)
        for item in items
        for source in holding(item)
    ]
    mounts = [
        Mount(
            source=launch.copied(item.name)
            if holding(item)
            else launch.empty_directory
            if item.directory
            else launch.empty_file,
            target=home / item.name,
            read_only=True,
        )
        for item in items
    ]
    return Homed(
        copies=copies,
        directories=[launch.empty_directory],
        files={launch.empty_file: ""},
        mounts=mounts,
        left=[said for item in items for said in odd(item)],
    )


def fits(path: Path, *, directory: bool) -> bool:
    """Say whether `path` is a directory, or a file where not `directory`, as itself rather than through a link."""
    try:
        seen = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(seen.st_mode) if directory else stat.S_ISREG(seen.st_mode)
