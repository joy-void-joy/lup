"""Read the model lineup a Claude Code CLI ships inside its own program.

Claude Code publishes no command that lists its models; ``claude --help``
names three aliases by way of example. What it does ship is the catalog it
resolves every ``--model`` against, baked into the program as the object
literal its bundler emitted from ``model-catalog.json``: every model id, the
aliases and where each routes, each model's context suffix and the effort
capabilities it advertises. That literal is what this module reads, so the
lineup lup types its models against is the one the CLI itself accepts rather
than a list somebody kept by hand.

The literal is JavaScript, not JSON — keys unquoted, booleans spelled ``!0``
and ``!1`` — so it is read by :func:`script_literal`, a reader for exactly
that subset which refuses any token outside it rather than guessing.
"""

import json

# lup: ignore[import-re] — the lexical grammar of a JavaScript object literal,
# which no dependency this library locks can parse
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel

from lup.providers.catalog import CatalogAlias, CatalogModel, ModelCatalog
from lup.types import JsonValue, StringMap

# lup: ignore[constant-declaration] — the CLI's own bytes, spelled the way its
# bundler emits them rather than chosen here
BAKED_CATALOG_MARKER = b'{"//":"Hand-maintained baked-in model catalog'
"""Where the baked catalog's object literal opens inside the CLI program.

The catalog's own comment key, which the bundler carries through verbatim,
so it survives every renaming a minifier does to the code around it.
"""

type ScriptTokenKind = Literal[
    "open_object",
    "close_object",
    "open_array",
    "close_array",
    "colon",
    "comma",
    "string",
    "number",
    "boolean",
    "undefined",
    "word",
    "space",
    "other",
]

# lup: ignore[re-call] — a lexer for JavaScript literal syntax, the one format
# here with no parser to reach for; each token is decoded by json after it
SCRIPT_TOKEN = re.compile(
    rb"""(?P<open_object>\{)|(?P<close_object>\})|(?P<open_array>\[)"""
    rb"""|(?P<close_array>\])|(?P<colon>:)|(?P<comma>,)"""
    rb"""|(?P<string>"(?:[^"\\]|\\.)*")"""
    rb"""|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"""
    rb"""|(?P<boolean>![01])|(?P<undefined>void 0)"""
    rb"""|(?P<word>[A-Za-z_$][\w$]*)|(?P<space>\s+)|(?P<other>.)""",
    re.DOTALL,
)
"""The lexical grammar of a minified JSON-shaped object literal."""


class ScriptToken(BaseModel, frozen=True):
    """One lexeme of the literal, and where in the program it sits."""

    kind: ScriptTokenKind
    text: str
    offset: int

    def refused(self, expected: str) -> ValueError:
        """The error naming this token where ``expected`` was due."""
        return ValueError(
            f"the baked model catalog holds {self.text!r} at byte {self.offset} "
            f"where {expected} was expected; this reader knows only the "
            "JSON-shaped subset a bundler emits for a data file"
        )


class ScriptMember(BaseModel, frozen=True):
    """One key of an object literal and the value written beside it."""

    name: str
    value: JsonValue


def script_tokens(program: bytes, start: int) -> Iterator[ScriptToken]:
    """Every lexeme from ``start`` on, whitespace dropped."""
    for match in SCRIPT_TOKEN.finditer(program, start):
        kind = match.lastgroup
        match kind:
            case "space":
                continue
            case (
                "open_object"
                | "close_object"
                | "open_array"
                | "close_array"
                | "colon"
                | "comma"
                | "string"
                | "number"
                | "boolean"
                | "undefined"
                | "word"
                | "other"
            ):
                yield ScriptToken(
                    kind=kind,
                    text=match.group().decode("utf-8", errors="replace"),
                    offset=match.start(),
                )
            case _:
                raise AssertionError(f"lexical group {kind!r} is not in the grammar")


def script_literal(program: bytes, start: int) -> JsonValue:
    """The data value whose literal opens at byte ``start`` of ``program``.

    Recursive descent over :func:`script_tokens`, consuming only as far as
    the value's own closing bracket — the literal sits inside a program
    megabytes long, and nothing after it is read.
    """
    tokens = script_tokens(program, start)

    def following(expected: str) -> ScriptToken:
        token = next(tokens, None)
        if token is None:
            raise ValueError(
                f"the baked model catalog ended where {expected} was expected"
            )
        return token

    def value(token: ScriptToken) -> JsonValue:
        match token.kind:
            case "open_object":
                return {member.name: member.value for member in members()}
            case "open_array":
                return list(elements())
            case "string":
                decoded: str = json.loads(token.text)
                return decoded
            case "number":
                number = float(token.text)
                return int(number) if number.is_integer() else number
            case "boolean":
                return token.text == "!0"
            case "undefined":
                return None
            case "word" if token.text in {"true", "false", "null"}:
                constant: JsonValue = json.loads(token.text)
                return constant
            case _:
                raise token.refused("a value")

    def key(token: ScriptToken) -> str:
        match token.kind:
            case "word":
                return token.text
            case "string":
                name: str = json.loads(token.text)
                return name
            case _:
                raise token.refused("a key")

    def members() -> Iterator[ScriptMember]:
        for token in tokens:
            match token.kind:
                case "close_object":
                    return
                case "comma":
                    continue
                case _:
                    name = key(token)
                    if (separator := following("':'")).kind != "colon":
                        raise separator.refused("':'")
                    yield ScriptMember(name=name, value=value(following("a value")))
        raise ValueError("the baked model catalog's object never closed")

    def elements() -> Iterator[JsonValue]:
        for token in tokens:
            match token.kind:
                case "close_array":
                    return
                case "comma":
                    continue
                case _:
                    yield value(token)
        raise ValueError("the baked model catalog's array never closed")

    return value(following("a value"))


class BakedProviderIds(BaseModel, frozen=True, extra="ignore"):
    """The id each route spells a model as; only the first-party one is read."""

    first_party: str


class BakedContext(BaseModel, frozen=True, extra="ignore"):
    """What a model's context window admits."""

    supports_1m_suffix: bool = False


class BakedModel(BaseModel, frozen=True, extra="ignore"):
    """One entry of the CLI's ``models`` table, in its own words."""

    id: str
    provider_ids: BakedProviderIds
    context: BakedContext = BakedContext()
    capabilities: list[str] = []

    def efforts(self) -> list[str]:
        """The effort rungs this model's capabilities advertise, lowest first.

        ``ultra`` is lup's name for the CLI's ultracode — ``xhigh`` plus
        standing workflow orchestration — which the CLI refuses for a model
        without ``xhigh``, so it rides that capability.
        """
        return [
            *(["low", "medium", "high"] if "effort" in self.capabilities else []),
            *(["xhigh"] if "xhigh_effort" in self.capabilities else []),
            *(["max"] if "max_effort" in self.capabilities else []),
            *(["ultra"] if "xhigh_effort" in self.capabilities else []),
        ]


class BakedAlias(BaseModel, frozen=True, extra="ignore"):
    """Where one alias routes: a default, and any route answering otherwise."""

    default: str
    per_provider: StringMap = {}
    """The model each route resolves this alias to, keyed by the CLI's own
    route names, which it may add to between releases."""

    def targets(self) -> list[str]:
        """Every model id this alias can resolve to, the default first."""
        return list(dict.fromkeys([self.default, *self.per_provider.values()]))


class BakedCatalog(BaseModel, frozen=True, extra="ignore"):
    """The CLI's baked model catalog, as far as a model selection reads it."""

    models: list[BakedModel]
    aliases: dict[str, BakedAlias]
    best: str | None = None
    """The alias the CLI's own ``best`` names."""

    def lineup(self, observed: str) -> ModelCatalog:
        """Every name the CLI accepts for a model, and the efforts each takes.

        Four kinds of name, each a spelling the CLI resolves: an alias with
        every route it can take, ``best`` as whichever alias the catalog calls
        best, a model's dated first-party id, and any of those or a bare id
        with the ``[1m]`` window suffix where the model it reaches admits one.
        """
        suffixed = {
            model.id for model in self.models if model.context.supports_1m_suffix
        }
        routes = {name: alias.targets() for name, alias in self.aliases.items()}
        if self.best is not None:
            routes["best"] = routes[self.best]
        spellings = {
            model.provider_ids.first_party: [model.id]
            for model in self.models
            if model.provider_ids.first_party != model.id
        }
        bare = {model.id: [model.id] for model in self.models}
        windows = {
            f"{name}[1m]": targets
            for name, targets in {**routes, **bare}.items()
            if any(target in suffixed for target in targets)
        }
        return ModelCatalog(
            runtime="claude",
            observed=observed,
            models=[
                CatalogModel(id=model.id, efforts=model.efforts())
                for model in self.models
            ],
            aliases=[
                CatalogAlias(name=name, targets=targets)
                for name, targets in {**routes, **spellings, **windows}.items()
            ],
        )


def claude_program() -> Path:
    """The Claude Code program on ``PATH``, symlinks followed to the file itself."""
    found = shutil.which("claude")
    if found is None:
        raise FileNotFoundError(
            "no `claude` on PATH; install Claude Code to read its model catalog"
        )
    return Path(found).resolve()


def baked_catalog(program: Path) -> BakedCatalog:
    """The catalog baked into one Claude Code program."""
    content = program.read_bytes()
    start = content.find(BAKED_CATALOG_MARKER)
    if start < 0:
        raise ValueError(
            f"{program} carries no baked model catalog where lup reads it "
            f"(the literal opening {BAKED_CATALOG_MARKER.decode()!r}); the CLI "
            "has changed how it ships its lineup, and this reader has to follow"
        )
    return BakedCatalog.model_validate(script_literal(content, start))


def claude_catalog(program: Path | None = None) -> ModelCatalog:
    """The lineup the installed Claude Code CLI accepts, read from the CLI."""
    selected = program or claude_program()
    version = str(sh.Command(str(selected))("--version")).strip()
    return baked_catalog(selected).lineup(version)
