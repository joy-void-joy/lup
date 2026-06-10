"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
from collections.abc import Mapping, Sequence
from typing import Annotated

import sh
import typer
from pydantic import BaseModel

git = sh.Command("git").bake("--no-pager", "-c", "color.ui=never", _tty_out=False)
gh = sh.Command("gh").bake(_tty_out=False)
uv = sh.Command("uv")


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns True on success."""
    for command, args in (
        ("xclip", ["-selection", "clipboard"]),
        ("xsel", ["--clipboard", "--input"]),
        ("pbcopy", []),
    ):
        try:
            sh.Command(command)(*args, _in=text)
            return True
        except sh.ErrorReturnCode, sh.CommandNotFound:
            continue
    return False


def output_json(  # claude: ignore
    data: BaseModel | Mapping[str, object] | Sequence[object],
) -> None:
    if isinstance(data, BaseModel):
        typer.echo(data.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(data, indent=2))


VERSION_OPT = Annotated[
    str | None,
    typer.Option("--version", "-v", help="Agent version (default: current)"),
]
ALL_VERSIONS_OPT = Annotated[
    bool,
    typer.Option("--all-versions", help="Include all versions"),
]
JSON_OPT = Annotated[
    bool,
    typer.Option("--json", help="Output as JSON"),
]
