"""The code-intelligence tools against the real language server.

A tool that is merely registered is worth nothing: the failure this guards is
a server that starts and answers every question with silence, which an agent
reads as "this symbol has no definition and no uses". So these drive the real
`pyright-langserver` over this repository and assert it resolved something
specific, rather than asserting the tools exist.
"""

import json

import pytest

from lup.codeintel.tools import (
    DocumentInput,
    PositionInput,
    RenameInput,
    create_codeintel_tools,
)
from lup.workspace.paths import project_root
from lup.devtools.dev.pyright_oracle import langserver_path

pytestmark = pytest.mark.skipif(
    langserver_path() is None, reason="pyright-langserver is not installed"
)

TARGET = "packages/lup/src/lup/codeintel/client.py"


def tools_by_name():
    server = langserver_path()
    assert server is not None
    return {tool.name: tool for tool in create_codeintel_tools(server, project_root())}


async def call(name: str, params):
    handler = tools_by_name()[name].handler
    response = await handler(params.model_dump())
    assert "content" in response, response
    block = response["content"][0]
    assert block["type"] == "text"
    return json.loads(block["text"])


@pytest.mark.asyncio
async def test_a_definition_resolves_through_the_import_that_names_it() -> None:
    """`utf16_column` is called in `position_in`; the definition is above it."""
    lines = (project_root() / TARGET).read_text(encoding="utf-8").splitlines()
    line = next(
        number
        for number, text in enumerate(lines, start=1)
        if "utf16_column(row, column)" in text
    )
    column = lines[line - 1].index("utf16_column")

    result = await call(
        "find_definition", PositionInput(path=TARGET, line=line, column=column)
    )

    assert result["sites"], "the server resolved no definition at all"
    assert any(site["path"].endswith("codeintel/client.py") for site in result["sites"])


@pytest.mark.asyncio
async def test_references_find_a_use_the_declaration_line_does_not_show() -> None:
    lines = (project_root() / TARGET).read_text(encoding="utf-8").splitlines()
    line = next(
        number
        for number, text in enumerate(lines, start=1)
        if text.startswith("def utf16_column")
    )
    column = lines[line - 1].index("utf16_column")

    result = await call(
        "find_references", PositionInput(path=TARGET, line=line, column=column)
    )

    assert result["sites"], "the server found no uses of a symbol that has one"


@pytest.mark.asyncio
async def test_listing_symbols_names_the_session_class() -> None:
    result = await call("list_symbols", DocumentInput(path=TARGET))

    names = {symbol["name"] for symbol in result["symbols"]}
    assert "LspSession" in names
    assert "request" in names, "nested members are flattened out of their class"


@pytest.mark.asyncio
async def test_hover_reports_a_resolved_type() -> None:
    lines = (project_root() / TARGET).read_text(encoding="utf-8").splitlines()
    line = next(
        number
        for number, text in enumerate(lines, start=1)
        if text.startswith("def utf16_column")
    )
    column = lines[line - 1].index("utf16_column")

    result = await call("hover", PositionInput(path=TARGET, line=line, column=column))

    assert "utf16_column" in result["text"]


@pytest.mark.asyncio
async def test_a_rename_is_planned_and_never_written() -> None:
    target = project_root() / TARGET
    before = target.read_text(encoding="utf-8")
    lines = before.splitlines()
    line = next(
        number
        for number, text in enumerate(lines, start=1)
        if text.startswith("def utf16_column")
    )
    column = lines[line - 1].index("utf16_column")

    result = await call(
        "rename_symbol",
        RenameInput(path=TARGET, line=line, column=column, new_name="utf16_offset"),
    )

    assert result["files"], "a symbol with uses planned no edits"
    assert target.read_text(encoding="utf-8") == before, "the plan wrote to disk"


@pytest.mark.asyncio
async def test_a_missing_file_is_an_error_rather_than_an_empty_answer() -> None:
    handler = tools_by_name()["find_definition"].handler

    response = await handler(
        PositionInput(path="does/not/exist.py", line=1).model_dump()
    )

    assert "is_error" in response
    assert response["is_error"] is True
