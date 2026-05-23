"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
from collections.abc import Mapping, Sequence

import sh
import typer
from pydantic import BaseModel

git = sh.Command("git").bake("--no-pager", "-c", "color.ui=never", _tty_out=False)
gh = sh.Command("gh").bake(_tty_out=False)
uv = sh.Command("uv")


def output_json(  # claude: ignore
    data: BaseModel | Mapping[str, object] | Sequence[object],
) -> None:
    if isinstance(data, BaseModel):
        typer.echo(data.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(data, indent=2))
