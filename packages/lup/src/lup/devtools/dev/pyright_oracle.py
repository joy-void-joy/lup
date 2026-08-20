"""Pyright's language server, implementing the codescan definition oracle.

`lup.codescan.grammar` judges a site by where its subject is declared, and
this is the only thing in the repository that can answer that. Pyright is
already the project's single type checker, but its CLI only reports
diagnostics — a declaration query needs the language-server protocol, so this
module speaks LSP to `pyright-langserver --stdio`: one server for a whole
sweep, every queried document opened once, one `textDocument/definition` per
site.

Nothing here decides anything about a rule. The client returns declaration
locations and the library reads the declaring class out of them, which keeps
the checker replaceable and the grammar testable against a fake. Every way
this can fail — the server is not installed, it will not start, it stops
answering — resolves to "no declarations", the same answer as a genuinely
unresolvable symbol, so the audit falls back to its broad regex verdict
rather than reporting a refutation it cannot support.
"""

import asyncio
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer
from pydantic import BaseModel, ValidationError

from lup.codeintel.client import Call, lsp_session
from lup.codeintel.replies import LOCATIONS
from lup.codescan.oracle import (
    DefinitionOracle,
    DefinitionSite,
    SourceBuffer,
    SourcePosition,
)
from lup.types import JsonValue
from lup.workspace.paths import project_root

# lup: ignore[constant-declaration] — the binary pyright installs under
SERVER_NAME = "pyright-langserver"

RESOLVE_TIMEOUT_SECONDS = 600.0
"""Budget for a whole sweep. Exhausting it degrades to the broad rule."""

RESOLVE_WORKERS = 4
"""Language servers a sweep drives at once, as a default a caller may raise.

Pyright answers one question at a time in one process, so a sweep pinned to a
single server is one core busy on a host that has many. Servers are what
parallelize it, and each one costs a process holding its own picture of the
workspace — memory rather than time, which is why this is a small number and
not the core count.
"""


def langserver_path() -> Path | None:
    """The language server shipped beside this interpreter, or on PATH."""
    beside = Path(sys.executable).parent / SERVER_NAME
    if beside.is_file():
        return beside
    located = shutil.which(SERVER_NAME)
    return Path(located) if located is not None else None


def locations_of(result: JsonValue) -> list[DefinitionSite]:
    """Decode one `textDocument/definition` result into declaration sites."""
    try:
        decoded = LOCATIONS.validate_python(result)
    except ValidationError:
        return []  # an unspecified result shape is no evidence, not an error
    if decoded is None:
        return []
    found = decoded if isinstance(decoded, list) else [decoded]
    return [
        DefinitionSite(
            path=Path(unquote(urlparse(location.uri).path)),
            line=location.range.start.line + 1,
        )
        for location in found
    ]


async def resolve(
    server: Path,
    root: Path,
    positions: list[SourcePosition],
    buffers: list[SourceBuffer] | None = None,
) -> list[list[DefinitionSite]]:
    """Run one language-server session and answer every queried position.

    Every document opens before the first question is asked, and the whole
    sweep goes out before the first answer is read. Asking one position at a
    time leaves the server idle for a round trip per site, and a sweep is
    hundreds of sites: the questions are independent, so nothing is owed the
    ordering that costs bought.
    """
    held = {buffer.path.as_posix(): buffer.text for buffer in buffers or []}
    async with lsp_session(server, root, name=SERVER_NAME) as session:
        asked = [
            Call(
                method="textDocument/definition",
                params=await session.position_in(
                    position.path,
                    position.line,
                    position.column,
                    held[position.path.as_posix()]
                    if position.path.as_posix() in held
                    else None,
                ),
            )
            for position in positions
        ]
        return [locations_of(answer) for answer in await session.requests(asked)]


class Shard(BaseModel, frozen=True):
    """One server's share of a sweep, and where in the sweep each answer goes."""

    offsets: list[int]
    positions: list[SourcePosition]


def sharded(positions: list[SourcePosition], workers: int) -> list[Shard]:
    """Split a sweep across servers, keeping every file whole in one share.

    A server pays to open a document and to follow what it imports, so the
    same file asked about from two servers is that cost paid twice. Files are
    the unit the split is made of, dealt largest first so the heaviest one
    cannot land on a share that is already the fullest.
    """
    grouped = {
        path: [
            offset
            for offset, position in enumerate(positions)
            if position.path.as_posix() == path
        ]
        for path in {position.path.as_posix() for position in positions}
    }
    ranked = sorted(grouped.values(), key=len, reverse=True)
    shares = [
        [offset for group in ranked[worker::workers] for offset in group]
        for worker in range(min(workers, len(ranked)))
    ]
    return [
        Shard(offsets=share, positions=[positions[offset] for offset in share])
        for share in shares
    ]


async def resolve_sharded(
    server: Path,
    root: Path,
    shards: list[Shard],
    buffers: list[SourceBuffer] | None = None,
) -> list[list[DefinitionSite]]:
    """Run every shard's session at once and put the answers back in order."""
    resolved = await asyncio.gather(
        *(resolve(server, root, shard.positions, buffers) for shard in shards)
    )
    found = {
        offset: sites
        for shard, answers in zip(shards, resolved, strict=True)
        for offset, sites in zip(shard.offsets, answers, strict=True)
    }
    return [found[offset] for offset in range(len(found))]


class PyrightOracle(DefinitionOracle):
    """Answers declaration queries by driving `pyright-langserver` over stdio."""

    def __init__(
        self,
        server: Path,
        root: Path,
        timeout: float = RESOLVE_TIMEOUT_SECONDS,
        workers: int = RESOLVE_WORKERS,
    ) -> None:
        self.server = server
        self.root = root
        self.timeout = timeout
        self.workers = workers

    def definitions(
        self,
        positions: list[SourcePosition],
        buffers: list[SourceBuffer] | None = None,
    ) -> list[list[DefinitionSite]]:
        """Resolve a whole sweep across server sessions, degrading on failure."""
        if not positions:
            return []
        try:
            return asyncio.run(
                asyncio.wait_for(
                    resolve_sharded(
                        self.server,
                        self.root,
                        sharded(positions, self.workers),
                        buffers,
                    ),
                    timeout=self.timeout,
                )
            )
        except (OSError, EOFError, TimeoutError, ValueError) as error:
            typer.echo(
                f"{SERVER_NAME}: {error} — anti-pattern findings keep their "
                "unrefined verdicts",
                err=True,
            )
            return [[] for _ in positions]


def default_oracle() -> DefinitionOracle | None:
    """The pyright-backed oracle, or None where the language server is absent."""
    server = langserver_path()
    return None if server is None else PyrightOracle(server, project_root())
