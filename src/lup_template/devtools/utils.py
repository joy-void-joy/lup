"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
from collections.abc import Mapping, Sequence
from typing import Annotated

import sh
import typer
from pydantic import BaseModel


class LazyCommand:
    """A ``sh.Command`` resolved on first use.

    Resolving ``git``/``gh``/``uv`` at import time means a single missing
    optional tool (e.g. ``gh``) aborts the whole CLI — including commands
    that never touch it. Deferring the lookup until the command is actually
    invoked keeps the failure scoped to the commands that need it, raising a
    clean :class:`sh.CommandNotFound` only then.
    """

    def __init__(
        self, name: str, *bake_args: str, **bake_kwargs: object
    ) -> None:  # claude: ignore  # sh.bake accepts arbitrary kwargs
        self.name = name
        self.bake_args = bake_args
        self.bake_kwargs = bake_kwargs
        self.resolved: sh.Command | None = None

    def command(self) -> sh.Command:
        if self.resolved is None:
            base = sh.Command(self.name)
            self.resolved = (
                base.bake(*self.bake_args, **self.bake_kwargs)
                if self.bake_args or self.bake_kwargs
                else base
            )
        return self.resolved

    def __call__(
        self, *args: object, **kwargs: object
    ) -> "str | sh.RunningCommand | None":  # claude: ignore  # sh passthrough
        return self.command()(*args, **kwargs)

    def __getattr__(self, attr: str) -> sh.Command:
        return getattr(self.command(), attr)


git = LazyCommand("git", "--no-pager", "-c", "color.ui=never", _tty_out=False)
gh = LazyCommand("gh", _tty_out=False)
uv = LazyCommand("uv")


def decode_stderr(e: sh.ErrorReturnCode) -> str:
    """Decode the stderr of a failed ``sh`` command to a string."""
    return e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)


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
