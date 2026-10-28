"""A runtime's configuration as a room gets it: layers merged, and what credentials and commands it holds left out (`docs/launch.md`, *A home of the rooms' own*).

Each runtime's adapter reads its settings file from each layer, the operator's
own and a profile's over it, merges them (`merged`), and leaves out what would
hand a room's code a credential or run a command in the room (`withheld`): the
keys its adapter names, any key at any depth named like a credential
(`Credentials.named`), and any table holding a `command`; and a URL's user
and password are taken out of it. Rooms run lup's own hooks, and a command the
operator set up for the host, a hook or a status line, would run in the room
with what it reads there. A wrong cut breaks a room, never the host: the host
only copies what's left, and never runs it.
"""

import stat
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import JsonValue

from lup.rooms.container import Mount
from lup.sessions.terminal import (
    Copy,
    Left,
    Shared,
    Syntax,
    TerminalError,
    Why,
    parsed,
    read,
)
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


class Cut(Model):
    """A key left out of a runtime's configuration, dotted from the top, a list's entry by its place, and why."""

    key: str
    why: Why


class Withheld(Model):
    """A runtime's configuration with what would hand a room a credential or run a command left out, and what was."""

    kept: JsonValue
    left: list[Cut] = []


def unlogged(text: str) -> str | None:
    """Return the URL `text` without the user and password it carries; none where it isn't a URL, or carries neither.

    >>> unlogged("https://u:p@git.example:8443/x?y=1"), unlogged("https://git.example/x")
    ('https://git.example:8443/x?y=1', None)
    """
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    if parts.username is None and parts.password is None:
        return None
    host = parts.hostname or ""
    bracketed = f"[{host}]" if ":" in host else host
    netloc = bracketed if port is None else f"{bracketed}:{port}"
    return urlunsplit(
        SplitResult(
            scheme=parts.scheme,
            netloc=netloc,
            path=parts.path,
            query=parts.query,
            fragment=parts.fragment,
        )
    )


def withheld(
    value: JsonValue,
    blocked: Callable[[list[str]], Why | None],
    path: list[str] | None = None,
    credentials: Credentials | None = None,
) -> Withheld:
    """Leave out of `value`, at every depth, tables in lists among it: each key `blocked` gives a reason for by its path; each named like a credential; and each whose value is a table holding a `command`, which would run in the room. A URL carrying a user or a password is kept without them, and said.

    >>> def blocked(path: list[str]) -> Why | None:
    ...     return "credential" if path == ["env"] else None
    >>> cut = withheld({"env": {"A": "1"}, "line": {"command": "x"}, "hooks": [{"token": "x"}], "url": "https://a:b@h/"}, blocked)
    >>> cut.kept, [(each.key, each.why) for each in cut.left]
    ({'hooks': [{}], 'url': 'https://h/'}, [('env', 'credential'), ('line', 'command'), ('hooks.0.token', 'credential'), ('url', 'credential')])
    """
    at = path or []
    naming = credentials or Credentials()
    dotted = ".".join(at)

    def why(key: str, each: JsonValue) -> Why | None:
        given = blocked([*at, key])
        if given is not None:
            return given
        match each:
            case {"command": _}:
                return "command"
            case _:
                return "credential" if naming.named(key) else None

    match value:
        case dict():
            cut: dict[str, Why] = {
                key: reason
                for key, each in value.items()
                if (reason := why(key, each)) is not None
            }
            inner = {
                key: withheld(each, blocked, [*at, key], naming)
                for key, each in value.items()
                if key not in cut
            }
            return Withheld(
                kept={key: each.kept for key, each in inner.items()},
                left=[
                    *(
                        Cut(key=".".join([*at, key]), why=reason)
                        for key, reason in cut.items()
                    ),
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
        case str() as text if (bare := unlogged(text)) is not None:
            return Withheld(kept=bare, left=[Cut(key=dotted, why="credential")])
        case _:
            return Withheld(kept=value)


def kept(table: JsonObject, blocked: Callable[[list[str]], Why | None]) -> Kept:
    """Leave out of the table `table` what `withheld` does, returning a table.

    >>> kept({"apiKeyHelper": "x", "model": "opus"}, lambda path: None).table
    {'model': 'opus'}
    """
    cut = withheld(table, blocked)
    match cut.kept:
        case dict() as remaining:
            return Kept(table=remaining, left=cut.left)
        case _:
            return Kept(left=cut.left)


class Kept(Model):
    """A table of configuration with what was left out of it."""

    table: JsonObject = {}
    left: list[Cut] = []


class Item(Model):
    """One item of a runtime's configuration or history in its directory: a file or a directory, by its name there."""

    name: str
    directory: bool = True
    leaving: list[str] = []
    """Names directly inside a directory left out of its copy: what isn't
    configuration, such as plugins' own data."""


class Layered(Model):
    """A settings file read from each layer, what would hand a room a credential or run a command left out of each, and merged; with what was left out."""

    table: JsonObject = {}
    left: list[Left] = []
    """Each key left out, with the file it was in, and each layer's file that
    couldn't be read as one."""


def layered(
    layers: list[Path],
    name: str,
    syntax: Syntax,
    blocked: Callable[[list[str]], Why | None],
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
            unread = Left(said=f"{path}, which isn't a file", why="unread")
            found = found.model_copy(update={"left": [*found.left, unread]})
            continue
        try:
            table = parsed(read(path), syntax)
        except ValueError as failed:
            message = f"{path} doesn't read as {syntax}: {failed}"
            raise TerminalError(message) from failed
        cut = kept(table, blocked)
        found = Layered(
            table=merged(found.table, cut.table),
            left=[
                *found.left,
                *(
                    Left(said=f"`{each.key}` in {path}", why=each.why)
                    for each in cut.left
                ),
            ],
        )
    return found


class Homed(Model):
    """What a terminal compile adds for a runtime's own directory and the history it links into."""

    copies: list[Copy] = []
    files: dict[Path, str] = {}
    links: dict[Path, Path] = {}
    mounts: list[Mount] = []
    shared: Shared | None = None
    left: list[Left] = []


def configured(items: list[Item], layers: list[Path], directory: Path) -> Homed:
    """Return the copies of each of `items` the layers hold into the runtime's own `directory`, lowest first, a later layer's over an earlier's.

    A layer's item that's a link, or isn't of its kind, is left out and said,
    never followed: a room that once wrote the layer could have left one
    aimed at the operator's keys.
    """

    def odd(item: Item) -> list[Left]:
        return [
            Left(
                said=f"{layer / item.name}, which is a link lup doesn't follow"
                if (layer / item.name).is_symlink()
                else f"{layer / item.name}, which isn't a "
                f"{'directory' if item.directory else 'file'}",
                why="unread",
            )
            for layer in layers
            if (layer / item.name).is_symlink()
            or (
                (layer / item.name).exists()
                and not fits(layer / item.name, directory=item.directory)
            )
        ]

    return Homed(
        copies=[
            Copy(
                source=layer / item.name,
                destination=directory / item.name,
                leaving=item.leaving,
            )
            for item in items
            for layer in layers
            if fits(layer / item.name, directory=item.directory)
        ],
        left=[said for item in items for said in odd(item)],
    )


def linked(items: list[Item], directory: Path, shared: Path) -> Homed:
    """Return a link from the runtime's own `directory` to each of `items` in the history `shared`, where each is made where it isn't."""
    return Homed(
        links={directory / item.name: shared / item.name for item in items},
        shared=Shared(
            home=shared,
            items={shared / item.name: item.directory for item in items},
        ),
    )


def fits(path: Path, *, directory: bool) -> bool:
    """Say whether `path` is a directory, or a file where not `directory`, as itself rather than through a link."""
    try:
        seen = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(seen.st_mode) if directory else stat.S_ISREG(seen.st_mode)
