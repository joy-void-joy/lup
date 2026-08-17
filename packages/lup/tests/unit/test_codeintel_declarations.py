"""Code-intelligence registration compiled from its agent-facing catalog."""

from pathlib import Path

from lup.codeintel.tools import (
    CODEINTEL_TOOL_DECLARATIONS,
    create_codeintel_tools,
)


def test_registered_tools_match_their_declarations() -> None:
    registered = create_codeintel_tools(Path("pyright-langserver"), Path("."))

    assert [(tool.name, tool.description) for tool in registered] == [
        (declaration.name, declaration.description)
        for declaration in CODEINTEL_TOOL_DECLARATIONS
    ]
