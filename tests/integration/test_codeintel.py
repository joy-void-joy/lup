"""The code-intelligence tools against the real language server.

A tool that is merely registered is worth nothing: the failure this guards is
a server that starts and answers every question with silence, which an agent
reads as "this symbol has no definition and no uses". So these drive the real
`pyright-langserver` over this repository and assert it resolved something
specific, rather than asserting the tools exist.
"""

import json
from pathlib import Path

import pytest

from lup.codeintel.tools import (
    DocumentInput,
    PositionInput,
    RenameInput,
    create_codeintel_tools,
)
from lup.codescan.common import PythonSource
from lup.codescan.grammar import refute
from lup.workspace.edition import publish_edition
from lup.workspace.paths import project_root
from lup.devtools.dev.pyright_oracle import PyrightOracle, langserver_path

pytestmark = pytest.mark.skipif(
    langserver_path() is None, reason="pyright-langserver is not installed"
)

TARGET = "packages/lup/src/lup/codeintel/client.py"


def tools_by_name(edition: Path | None = None):
    server = langserver_path()
    assert server is not None
    return {
        tool.name: tool
        for tool in create_codeintel_tools(server, project_root(), edition=edition)
    }


async def call(name: str, params, edition: Path | None = None):
    handler = tools_by_name(edition)[name].handler
    response = await handler(params.model_dump())
    assert "content" in response, response
    block = response["content"][0]
    assert block["type"] == "text"
    # A tool error carries prose where an answer carries JSON, so decoding it
    # fails somewhere unrelated to what went wrong. The message is the finding.
    assert "is_error" not in response, block["text"]
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
async def test_a_file_in_another_checkout_resolves_against_its_own(
    tmp_path: Path,
) -> None:
    """The server is started once; the work happens somewhere else.

    A worktree is a second checkout of the same repository, which is where
    this project asks that every change be made, and a server rooted on the
    launch directory resolves the same module names against different
    source. The failure is silent — a well-formed answer about the wrong
    tree — so this pins the import, which only resolves if the workspace
    followed the file.
    """
    elsewhere = tmp_path / "other-checkout"
    elsewhere.mkdir()
    (elsewhere / "pyproject.toml").write_text("[project]\nname = 'other'\n")
    (elsewhere / "helpers.py").write_text("def only_here() -> int:\n    return 1\n")
    caller = elsewhere / "caller.py"
    caller.write_text("from helpers import only_here\n\nonly_here()\n")

    result = await call(
        "find_definition",
        PositionInput(path=str(caller), line=3, column=0),
    )

    assert result["sites"], "the import resolved against the wrong checkout"
    assert result["sites"][0]["path"].endswith("helpers.py")


@pytest.mark.asyncio
async def test_a_relative_path_follows_where_editing_is_happening(
    tmp_path: Path,
) -> None:
    """The half deriving the workspace from an absolute path could not reach.

    A relative path is relative to the working directory of whoever asked,
    and this server is a separate long-lived process whose own was fixed at
    launch. Joining it to the launch checkout is a guess, and it is wrong
    silently whenever work has moved, because both trees hold that path.

    The permission hook publishes where editing is happening on every edit,
    which is the fact the guess was standing in for.
    """
    elsewhere = tmp_path / "other-checkout"
    (elsewhere / ".git").mkdir(parents=True)
    (elsewhere / "pyproject.toml").write_text("[project]\nname = 'other'\n")
    (elsewhere / "helpers.py").write_text("def only_here() -> int:\n    return 1\n")
    caller = elsewhere / "caller.py"
    caller.write_text("from helpers import only_here\n\nonly_here()\n")

    published = tmp_path / "edition.json"
    publish_edition(published, elsewhere, caller)

    result = await call(
        "find_definition",
        PositionInput(path="caller.py", line=3, column=0),
        edition=published,
    )

    assert result["sites"], "the relative path resolved against the launch checkout"
    assert result["sites"][0]["path"].endswith("helpers.py")


def test_the_oracle_resolves_a_buffer_that_disk_does_not_hold(tmp_path: Path) -> None:
    """An edit is judged before it is written, so disk is the wrong source.

    The file on disk here holds none of the code being asked about — a
    checker that read it would find nothing at the queried position and
    answer with silence, which the grammar reads as "cannot resolve" and
    leaves the broad verdict standing. The refutation only happens if the
    server was told the text the audit is actually reading.
    """
    server = langserver_path()
    assert server is not None
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'other'\n")
    (tmp_path / "vendor.py").write_text(
        "class Client:\n    def get(self, url): ...\n\n\ndef get(url): ...\n",
        encoding="utf-8",
    )
    edited = tmp_path / "caller.py"
    edited.write_text("x = 1\n", encoding="utf-8")
    proposed = 'import vendor\n\nresponse = vendor.get("https://example.com")\n'

    refutations = refute(
        [PythonSource(path=edited, module="caller", text=proposed)],
        PyrightOracle(server, tmp_path),
    )

    refuted = refutations[edited.as_posix()]
    assert [row.rule_id for row in refuted] == ["dict-get"]
    assert "the module-level `get`" in refuted[0].evidence


@pytest.mark.asyncio
async def test_a_missing_file_is_an_error_rather_than_an_empty_answer() -> None:
    handler = tools_by_name()["find_definition"].handler

    response = await handler(
        PositionInput(path="does/not/exist.py", line=1).model_dump()
    )

    assert "is_error" in response
    assert response["is_error"] is True
