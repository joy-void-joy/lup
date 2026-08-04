# lup: ignore[empty-collection]
# A protocol session accumulates answers in the order it asks for them.
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
import json
import shutil
import sys
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer
from pydantic import BaseModel, TypeAdapter, ValidationError

from lup.codescan.oracle import DefinitionOracle, DefinitionSite, SourcePosition
from lup.types import JsonObject, JsonValue
from lup.workspace.paths import project_root

SERVER_NAME = "pyright-langserver"

RESOLVE_TIMEOUT_SECONDS = 600.0
"""Budget for a whole sweep. Exhausting it degrades to the broad rule."""


class LspPosition(BaseModel):
    """A zero-based LSP line and UTF-16 character offset."""

    line: int
    character: int


class LspRange(BaseModel):
    """The span an LSP location covers."""

    start: LspPosition


class LspLocation(BaseModel):
    """One LSP `Location`: the document and span a symbol is declared at."""

    uri: str
    range: LspRange


LOCATIONS = TypeAdapter(list[LspLocation] | LspLocation | None)
"""Every shape `textDocument/definition` is specified to answer with."""


def langserver_path() -> Path | None:
    """The language server shipped beside this interpreter, or on PATH."""
    beside = Path(sys.executable).parent / SERVER_NAME
    if beside.is_file():
        return beside
    located = shutil.which(SERVER_NAME)
    return Path(located) if located is not None else None


def utf16_column(line: str, column: int) -> int:
    """Convert an `ast` UTF-8 byte offset into the UTF-16 offset LSP wants."""
    prefix = line.encode("utf-8")[:column].decode("utf-8", errors="ignore")
    return len(prefix.encode("utf-16-le")) // 2


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
    server: Path, root: Path, positions: list[SourcePosition]
) -> list[list[DefinitionSite]]:
    """Run one language-server session and answer every queried position."""
    process = await asyncio.create_subprocess_exec(
        str(server),
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdin, stdout = process.stdin, process.stdout
    if stdin is None or stdout is None:
        process.kill()
        raise OSError(f"{SERVER_NAME} started without usable pipes")

    asked = 0

    async def send(method: str, params: JsonObject, request_id: int | None) -> None:
        body: JsonObject = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        payload = json.dumps(body).encode("utf-8")
        stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
        await stdin.drain()

    async def receive() -> JsonObject:
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            chunk = await stdout.readline()
            if not chunk:
                raise OSError(f"{SERVER_NAME} closed its output stream")
            header.extend(chunk)
        declared = BytesParser().parsebytes(bytes(header))["Content-Length"]
        if declared is None:
            raise OSError(f"{SERVER_NAME} sent a frame with no Content-Length")
        message: JsonObject = json.loads(await stdout.readexactly(int(declared)))
        return message

    async def request(method: str, params: JsonObject) -> JsonValue:
        nonlocal asked
        asked += 1
        await send(method, params, asked)
        while True:
            message = await receive()
            if "id" in message and message["id"] == asked:
                return message["result"] if "result" in message else None

    async def session() -> list[list[DefinitionSite]]:
        folder: JsonObject = {"uri": root.as_uri(), "name": root.name}
        await request(
            "initialize",
            {
                "processId": None,
                "rootUri": root.as_uri(),
                "capabilities": {},
                "workspaceFolders": [folder],
            },
        )
        await send("initialized", {}, None)

        lines: dict[str, list[str]] = {}
        for path in dict.fromkeys(position.path for position in positions):
            text = path.read_text(encoding="utf-8")
            lines[path.as_posix()] = text.splitlines()
            await send(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": path.absolute().as_uri(),
                        "languageId": "python",
                        "version": 1,
                        "text": text,
                    }
                },
                None,
            )

        answers: list[list[DefinitionSite]] = []
        for position in positions:
            source = lines[position.path.as_posix()]
            row = source[position.line - 1] if position.line <= len(source) else ""
            result = await request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": position.path.absolute().as_uri()},
                    "position": {
                        "line": position.line - 1,
                        "character": utf16_column(row, position.column),
                    },
                },
            )
            answers.append(locations_of(result))

        await request("shutdown", {})
        await send("exit", {}, None)
        return answers

    try:
        return await session()
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


class PyrightOracle(DefinitionOracle):
    """Answers declaration queries by driving `pyright-langserver` over stdio."""

    def __init__(self, server: Path, root: Path) -> None:
        self.server = server
        self.root = root

    def definitions(
        self, positions: list[SourcePosition]
    ) -> list[list[DefinitionSite]]:
        """Resolve a whole sweep in one server session, degrading on failure."""
        if not positions:
            return []
        try:
            return asyncio.run(
                asyncio.wait_for(
                    resolve(self.server, self.root, positions),
                    timeout=RESOLVE_TIMEOUT_SECONDS,
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
