"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
from collections.abc import Mapping, Sequence
from typing import Annotated

import sh
import typer
from pydantic import BaseModel


class LazyCommand:
    """Shell command that resolves its binary on first use.

    ``sh.Command`` raises ``CommandNotFound`` at construction time, so a
    module-level command for a missing binary (e.g. ``gh``) would crash
    every CLI invocation at import — including ``--help``. Resolution is
    deferred to the first call or sub-command attribute access instead.
    """
    # claude: Didn't get that. Why do we need LazyCommand? As in, when is it used? Is it just to construct the command at top-level without crashing the import?

    def __init__(self, name: str, *bake_args: str, tty_out: bool = True) -> None:
        self.name = name
        self.bake_args = bake_args
        self.tty_out = tty_out
        self.resolved: sh.Command | None = None

    def resolve(self) -> sh.Command:
        if self.resolved is None:
            command = sh.Command(self.name)
            if self.bake_args or not self.tty_out:
                command = command.bake(*self.bake_args, _tty_out=self.tty_out)
            self.resolved = command
        return self.resolved

    def __call__(self, *args: str, **kwargs: object) -> sh.RunningCommand | str | None:
        return self.resolve()(*args, **kwargs)

    def __getattr__(self, attr: str) -> sh.Command:
        return getattr(self.resolve(), attr)


# claude: Yeah, okay, this makes sense
git = LazyCommand("git", "--no-pager", "-c", "color.ui=never", tty_out=False)
gh = LazyCommand("gh", tty_out=False)
uv = LazyCommand("uv")


def decode_stderr(e: sh.ErrorReturnCode) -> str:
    """Decode the stderr of a failed ``sh`` command to a string.""" # claude: Huh? There's no sh builtin for this?
    return e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns True on success.

    Tries xclip, xsel, then pbcopy; returns False when none is available
    so callers can fall back to printing the text for manual copying.
    """
    # claude: Would that work on windows or mac os?
    for command, args in (
        ("xclip", ["-selection", "clipboard"]),
        ("xsel", ["--clipboard", "--input"]),
        ("pbcopy", []),
    ):
        try:
            sh.Command(command)(*args, _in=text)
            return True
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            continue
    return False


def output_json(
    data: BaseModel | Mapping[str, object] | Sequence[object], # claude: ignore
    # claude: Inputting this #claude: ignore makes me realize that in the devtool check, we probably want something that rechecks the whole codebase and verifies if there should be claude: ignore when there isn't any
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
