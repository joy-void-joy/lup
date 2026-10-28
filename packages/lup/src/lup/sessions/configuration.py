"""A runtime's configuration as a room gets it: layers merged, and what credentials and commands it holds left out (`docs/launch.md`, *A home of the rooms' own*).

Each runtime's adapter reads its settings file from each layer, the operator's
own and a profile's over it, merges them (`merged`), and leaves out what would
hand a room's code a credential or run a command in the room (`withheld`): the
keys its adapter names, any key at any depth named like a credential
(`Credentials.named`), any table holding a `command`, and any value or list
entry holding a token by its shape, whatever its key (`Credentials.carries`),
such as a permission rule's command with a login in it; and a URL's user and
password are taken out of it, as is each parameter of its query named like a
credential or holding one. Rooms run lup's own hooks, and a command the
operator set up for the host, a hook or a status line, would run in the room
with what it reads there. A wrong cut breaks a room, never the host: the host
only copies what's left, and never runs it. A secret with no shape of its own
under a key named otherwise, a key of 32 hex digits in a header called
`X-Key`, still reaches the room.
"""

import base64
import stat
from itertools import groupby, pairwise
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

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


class Shape(Model):
    """The shape a vendor gives its tokens so they can be found in text: the opening each starts with, the least a token holds after it, and whose tokens they are, with where the shape is documented."""

    opening: str
    rest: int = 16
    """The fewest characters after the opening: what tells a token from a word
    that starts the same way."""
    whose: str

    def fits(self, word: str) -> bool:
        """Say whether `word` is a token of this shape: its opening, then at least `rest` characters.

        >>> shape = Shape(opening="ghp_", rest=4, whose="GitHub's")
        >>> shape.fits("ghp_a1b2"), shape.fits("ghp_a1"), shape.fits("xghp_a1b2")
        (True, False, False)
        """
        return word.startswith(self.opening) and len(word) - len(self.opening) >= (
            self.rest
        )


def written_in_token(char: str) -> bool:
    """Say whether `char` is one a token is written in: an ASCII letter or digit, `-` or `_`, base64url's, or `.`, which joins a JSON Web Token's parts.

    Not base64's `/`, so a token written after one, as in
    `https://ghp_…@github.com` inside a command, starts a word of its own.
    """
    return char.isascii() and (char.isalnum() or char in "-_.")


def tokens(text: str) -> list[str]:
    """Return the words of `text` a token could be: each run of the characters tokens are written in (`written_in_token`), in order.

    >>> tokens('Bash(export TOKEN=ghp_x1 && curl -H "Authorization: Bearer a.b-c")')
    ['Bash', 'export', 'TOKEN', 'ghp_x1', 'curl', '-H', 'Authorization', 'Bearer', 'a.b-c']
    """
    return [
        "".join(run) for written, run in groupby(text, key=written_in_token) if written
    ]


class JoseHeader(Model, extra="ignore"):
    """What lup reads of a JSON Web Token's first part, its header: the algorithm it's signed or encrypted with, which every one names (RFC 7515, *"alg" Header Parameter*)."""

    alg: str


def signed(word: str) -> bool:
    """Say whether `word` is a JSON Web Token: three parts joined by `.`, the first a JSON object naming its algorithm, in base64url without its padding (RFC 7515, *JWS Compact Serialization*).

    >>> header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode()
    >>> signed(f"{header}.e30.c2ln"), signed("eyJhhhh.payload.sig"), signed("v1.2.3")
    (True, False, False)
    """
    # lup: ignore("string-split", why="a JSON Web Token's compact form is defined as its base64url parts joined by `.` (RFC 7515), which the standard library has no reader for; each part is then read with `base64` and pydantic")
    parts = word.split(".")
    if len(parts) != 3:
        return False
    header = parts[0]
    try:
        decoded = base64.urlsafe_b64decode(header + "=" * (-len(header) % 4))
        JoseHeader.model_validate_json(decoded)
    except ValueError:
        return False
    return True


SHAPES = [
    Shape(opening="sk-ant-", rest=32, whose="Anthropic's API keys and OAuth tokens"),
    Shape(
        opening="sk-",
        rest=20,
        whose="OpenAI's API keys, `sk-proj-` and `sk-svcacct-` among them, and those keyed like theirs, OpenRouter's `sk-or-` (gitleaks' rules)",
    ),
    *(
        Shape(
            opening=opening,
            rest=30,
            whose="GitHub's tokens (GitHub's blog, *Behind GitHub's new authentication token formats*, 2021)",
        )
        for opening in ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"]
    ),
    *(
        Shape(
            opening=opening,
            rest=20,
            whose="GitLab's tokens (GitLab's docs, *Token prefixes*)",
        )
        for opening in ["glpat-", "gldt-", "glrt-", "glptt-", "glft-", "glsoat-"]
    ),
    *(
        Shape(opening=opening, whose="Slack's tokens (Slack's docs, *Token types*)")
        for opening in ["xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxe-", "xapp-"]
    ),
    *(
        Shape(
            opening=opening,
            whose="AWS's access key ids, long-term and temporary (AWS's IAM docs, *Unique identifier prefixes*)",
        )
        for opening in ["AKIA", "ASIA"]
    ),
    Shape(opening="AIza", rest=30, whose="Google's API keys (gitleaks' rules)"),
    Shape(
        opening="hf_",
        rest=30,
        whose="Hugging Face's access tokens (its docs, *User access tokens*)",
    ),
    Shape(
        opening="npm_",
        rest=30,
        whose="npm's access tokens (npm's docs, *About access tokens*)",
    ),
    Shape(
        opening="pypi-", rest=30, whose="PyPI's API tokens (PyPI's help, *API tokens*)"
    ),
    *(
        Shape(
            opening=opening,
            whose="Stripe's secret and restricted keys (Stripe's docs, *API keys*)",
        )
        for opening in ["sk_live_", "sk_test_", "rk_live_", "rk_test_"]
    ),
    Shape(opening="gsk_", rest=30, whose="Groq's API keys (gitleaks' rules)"),
    Shape(opening="xai-", rest=30, whose="xAI's API keys (gitleaks' rules)"),
    Shape(opening="lin_api_", rest=30, whose="Linear's API keys (gitleaks' rules)"),
    Shape(
        opening="ntn_", rest=30, whose="Notion's integration tokens (gitleaks' rules)"
    ),
    Shape(opening="dop_v1_", rest=30, whose="DigitalOcean's tokens (gitleaks' rules)"),
    Shape(
        opening="glsa_",
        rest=30,
        whose="Grafana's service account tokens (gitleaks' rules)",
    ),
    Shape(opening="sntrys_", rest=30, whose="Sentry's tokens (gitleaks' rules)"),
    Shape(opening="tskey-", rest=20, whose="Tailscale's keys (gitleaks' rules)"),
    *(
        Shape(opening=opening, rest=20, whose="Shopify's tokens (gitleaks' rules)")
        for opening in ["shpat_", "shpca_", "shppa_", "shpss_"]
    ),
    Shape(opening="PMAK-", rest=30, whose="Postman's API keys (gitleaks' rules)"),
]
"""The token shapes `Credentials.carries` finds, one place for all: each
vendor's own opening, as it or gitleaks' rules document it. Adding one is
adding its line."""


class Credentials(Model):
    """What names a credential in a key, a word of its own or two in a row; and what shows one in a value, a token's shape, whatever its key."""

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

    shapes: list[Shape] = SHAPES
    schemes: list[str] = ["bearer", "basic"]
    """HTTP's schemes for a credential in an `Authorization` header, in any
    case: the word after one, where it's long, is its credential."""
    after_scheme: int = 16
    """The fewest characters of the word after a scheme for it to be read as
    the scheme's credential: `Bearer of good news` holds none. A `Basic`
    credential is base64, whose `+` and `/` end a word (`written_in_token`),
    so one is found where its first such run is this long."""

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

    def carries(self, text: str) -> bool:
        """Say whether `text` holds a credential by its shape, whatever it's in: a word of it that's a token of a vendor's (`shapes`) or a JSON Web Token (`signed`), or one long enough after a scheme of HTTP's (`schemes`).

        >>> token = "ghp_" + "a1" * 18
        >>> [Credentials().carries(text) for text in [f"Bash(gh api -H 'Authorization: token {token}')", f"Bash(git clone https://{token}@github.com/o/r)", "Bearer of good news", "sk-learn", "task-runner"]]
        [True, True, False, False, False]
        """
        said = tokens(text)
        shaped = any(
            signed(word) or any(shape.fits(word) for shape in self.shapes)
            for word in said
        )
        schemed = any(
            before.casefold() in self.schemes and len(word) >= self.after_scheme
            for before, word in pairwise(said)
        )
        return shaped or schemed


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


def unlogged(text: str, credentials: Credentials | None = None) -> str | None:
    """Return the URL `text` without the user and password it carries, and without each parameter of its query named like a credential or holding one (`Credentials`); none where it isn't a URL, or carries none of them.

    >>> unlogged("https://u:p@git.example:8443/x?y=1"), unlogged("https://git.example/x")
    ('https://git.example:8443/x?y=1', None)
    >>> unlogged("https://git.example/m.git?private_token=x&ref=main")
    'https://git.example/m.git?ref=main'
    """
    naming = credentials or Credentials()
    try:
        parts = urlsplit(text)
        port = parts.port
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    asked = [
        pair
        for pair in query
        if not naming.named(pair[0]) and not naming.carries(pair[1])
    ]
    logged = parts.username is not None or parts.password is not None
    if not logged and len(asked) == len(query):
        return None
    host = parts.hostname or ""
    bracketed = f"[{host}]" if ":" in host else host
    netloc = bracketed if port is None else f"{bracketed}:{port}"
    return urlunsplit(
        SplitResult(
            scheme=parts.scheme,
            netloc=netloc if logged else parts.netloc,
            path=parts.path,
            query=parts.query if len(asked) == len(query) else urlencode(asked),
            fragment=parts.fragment,
        )
    )


def held(text: str, credentials: Credentials) -> bool:
    """Say whether `text` would hand a room a credential once a URL's login and its credentials' parameters are taken out of it (`unlogged`), by a token's shape (`Credentials.carries`)."""
    return credentials.carries(unlogged(text, credentials) or text)


def withheld(
    value: JsonValue,
    blocked: Callable[[list[str]], Why | None],
    path: list[str] | None = None,
    credentials: Credentials | None = None,
) -> Withheld:
    """Leave out of `value`, at every depth, tables in lists among it: each key `blocked` gives a reason for by its path; each named like a credential; each whose value is a table holding a `command`, which would run in the room; and each value or list entry that's text holding a credential by its shape (`held`). A URL carrying a user or a password, or a parameter named like a credential or holding one, is kept without them, and said.

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
            case str() as text if held(text, naming):
                return "credential"
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
            entries = [
                Cut(key=".".join([*at, str(place)]), why="credential")
                if isinstance(each, str) and held(each, naming)
                else withheld(each, blocked, [*at, str(place)], naming)
                for place, each in enumerate(value)
            ]
            inner_list = [each for each in entries if isinstance(each, Withheld)]
            return Withheld(
                kept=[each.kept for each in inner_list],
                left=[
                    *(each for each in entries if isinstance(each, Cut)),
                    *(left for each in inner_list for left in each.left),
                ],
            )
        case str() as text if (bare := unlogged(text, naming)) is not None:
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
