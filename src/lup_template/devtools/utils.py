"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Literal

import sh
import typer
from pydantic import BaseModel

# Git abbreviates object names to this many hex characters by default
# (`core.abbrev`), the same width as `git log --oneline`. Short shas are for
# human-readable display only; never parse or compare against them.
SHORT_SHA_LENGTH = 7


class LazyCommand:
    """Shell command that resolves its binary on first use.

    ``sh.Command`` raises ``CommandNotFound`` at construction time, so a
    module-level command for a missing binary (e.g. ``gh``) would crash
    every CLI invocation at import — including ``--help``. Resolution is
    deferred to the first call or sub-command attribute access instead.
    """

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


# lup: Yeah, okay, this makes sense
git = LazyCommand("git", "--no-pager", "-c", "color.ui=never", tty_out=False)
gh = LazyCommand("gh", tty_out=False)
uv = LazyCommand("uv")


def decode_stderr(e: sh.ErrorReturnCode) -> str:
    """Decode a failed ``sh`` command's stderr to text.

    ``sh`` captures stderr as raw ``bytes`` and exposes no decoded
    accessor, so callers that want a readable message decode it here.
    """
    return e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. Returns True on success.

    Best-effort and cross-platform: tries each platform's clipboard tool
    in turn (Linux ``xclip``/``xsel``, macOS ``pbcopy``, Windows ``clip``)
    and stops at the first one that is installed and succeeds. Returns
    False when none is available so callers can fall back to printing the
    text for manual copying.
    """
    for command, args in (
        ("xclip", ["-selection", "clipboard"]),
        ("xsel", ["--clipboard", "--input"]),
        ("pbcopy", []),
        ("clip", []),
    ):
        try:
            sh.Command(command)(*args, _in=text)
            return True
        except (sh.ErrorReturnCode, sh.CommandNotFound):
            continue
    return False


def output_json(
    data: BaseModel | Mapping[str, object] | Sequence[object],  # lup: ignore
    # lup: Inputting this #lup: ignore makes me realize that in the devtool check, we probably want something that rechecks the whole codebase and verifies if there should be lup: ignore when there isn't any
) -> None:
    if isinstance(data, BaseModel):
        typer.echo(data.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(data, indent=2))


def short_sha(sha: str) -> str:
    """Abbreviate a git object name for human-readable display.

    The single source of truth for how shas are shortened across devtools so
    every table and message uses one consistent width. Returns shorter input
    unchanged so already-abbreviated shas pass through.
    """
    return sha[:SHORT_SHA_LENGTH]


def format_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    aligns: Sequence[Literal["left", "right"]] | None = None,
) -> str:
    """Render rows as a column-aligned table sized to its own contents.

    Column widths come from the widest cell in each column, so no caller has
    to guess a fixed width that later clips real data. ``aligns`` picks left
    (default) or right justification per column; a trailing column gets no
    padding so variable-length tails (paths, messages) aren't padded out.
    """
    materialized = [list(row) for row in rows]
    widths = [len(h) for h in headers]
    for row in materialized:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(cells: Sequence[str]) -> str:
        last = len(cells) - 1
        parts: list[str] = []
        for i, cell in enumerate(cells):
            align = aligns[i] if aligns else "left"
            if i == last:
                parts.append(cell if align == "left" else f"{cell:>{widths[i]}}")
            elif align == "right":
                parts.append(f"{cell:>{widths[i]}}")
            else:
                parts.append(f"{cell:<{widths[i]}}")
        return " ".join(parts)

    header_line = render(headers)
    lines = [header_line, "-" * len(header_line)]
    lines.extend(render(row) for row in materialized)
    return "\n".join(lines)


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
