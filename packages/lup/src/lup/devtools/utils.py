"""Pre-configured shell commands and output helpers for devtools scripts."""

import json
import logging
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import sh
import typer
from pydantic import BaseModel

from lup.execution.shell import LazyCommand, git
from lup.execution.writability import admin_dirs, diagnose_git_admin, inspect_git_admin

logger = logging.getLogger(__name__)


# Git abbreviates object names to this many hex characters by default
# (`core.abbrev`), the same width as `git log --oneline`. Short shas are for
# human-readable display only; never parse or compare against them.
SHORT_SHA_LENGTH = 7


gh = LazyCommand("gh", tty_out=False)
uv = LazyCommand("uv")


def slug_from_remote(url: str) -> str:
    """The ``owner/name`` a remote names, empty when it names none.

    Read here rather than left to `gh` to infer, because a remote written
    through an SSH alias — ``<alias>:owner/name.git``, whose host ssh resolves
    from its own config — names no host `gh` recognizes, and every query then
    fails with "no known GitHub host" as though the repository were
    unreachable.

    The pair is the last two path segments in every shape a remote is written
    in, and nothing before a colon is ever one of them — which is what reads
    the scp-like form (``git@host:owner/name``) that is not a URL and has no
    parser in the standard library.
    """
    trimmed = url.removesuffix(".git")
    located = trimmed.rpartition(":")[2]  # lup: ignore[string-split] — no parser
    named = PurePosixPath(located).parts
    return "/".join(named[-2:]) if len(named) >= 2 else ""


def repository_slug() -> str:
    """The ``owner/name`` this checkout answers to, empty when unreadable."""
    try:
        return slug_from_remote(git.out("remote", "get-url", "origin"))
    except sh.ErrorReturnCode as error:
        logger.warning("no origin remote to read a slug from: %s", decode_stderr(error))
        return ""


def repository_arguments() -> list[str]:
    """The ``--repo`` a `gh` query needs, or nothing where none is readable.

    Every `gh` subcommand infers its repository from the origin remote unless
    told, and that inference is what an alias defeats. Naming it once here is
    what stops a query depending on the spelling a checkout happens to use.

    Empty where no slug is readable, which is a project with no forge rather
    than a forge that could not be reached. The two want opposite answers from
    a caller — absence is a fact in the first and unknown in the second — so
    they are not collapsed here.
    """
    slug = repository_slug()
    return ["--repo", slug] if slug else []


def decode_stderr(e: sh.ErrorReturnCode) -> str:
    """Decode a failed ``sh`` command's stderr to trimmed text.

    ``sh`` captures stderr as raw ``bytes`` and exposes no decoded accessor,
    so callers that want a readable message decode it here; the trailing
    newline the failing tool printed with is framing, not message.
    """
    raw = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
    return raw.strip()


def git_admin_dirs(cwd: Path | None = None) -> list[Path]:
    """Every admin directory a checkout writes its configuration through.

    A worktree's own ``.git`` is a file naming its admin directory and a bare
    clone has no ``.git`` at all, so the layout is asked of git rather than
    reconstructed from the checkout — and the ask still answers when every
    write is being refused.
    """
    root = cwd if cwd is not None else Path.cwd()
    return admin_dirs(
        root, git.lines("rev-parse", "--git-dir", "--git-common-dir", _cwd=str(root))
    )


def config_lock_diagnosis(cwd: Path | None = None) -> str:
    """Why git config writes cannot run here, empty when they can."""
    try:
        admins = git_admin_dirs(cwd)
    except sh.ErrorReturnCode:
        # No repository to diagnose: whatever the caller's git failure was,
        # the lock protocol is not what it tripped on.
        return ""
    return diagnose_git_admin(admins)


def clear_stale_config_locks(cwd: Path | None = None) -> Iterator[str]:
    """Remove every lock nothing is holding, naming each one removed.

    A confinement manufactures this debris — a sandboxed git dies mid-write
    and its lock outlives it on the host — so the run that can reach the
    filesystem is the one that has to clear it, and the next unconfined run
    is not sent hunting for a failure the previous one left. Nothing that
    declines removal is touched.
    """
    try:
        admins = git_admin_dirs(cwd)
    except sh.ErrorReturnCode:
        return
    for admin in admins:
        for obstruction in inspect_git_admin(admin):
            cleared = obstruction.clear()
            if cleared:
                yield cleared


def refuse_blocked_config_writes(cwd: Path | None = None) -> None:
    """Clear what is removable, and stop before a config write that still cannot run."""
    for cleared in clear_stale_config_locks(cwd):
        typer.echo(cleared)
    diagnosis = config_lock_diagnosis(cwd)
    if diagnosis:
        typer.echo(diagnosis, err=True)
        raise typer.Exit(1)


def output_json(
    data: object,  # lup: ignore[bare-object] — pretty-printer: any serializable payload
) -> None:
    if isinstance(data, BaseModel):
        typer.echo(data.model_dump_json(indent=2))
    else:
        typer.echo(json.dumps(data, indent=2))


def short_sha(sha: str, length: int = SHORT_SHA_LENGTH) -> str:
    """Abbreviate a git object name for human-readable display.

    The single source of truth for how shas are shortened across devtools so
    every table and message uses one consistent width. Returns shorter input
    unchanged so already-abbreviated shas pass through.
    """
    return sha[:length]


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

        def pad(i: int, cell: str) -> str:
            align = aligns[i] if aligns else "left"
            if align == "right":
                return f"{cell:>{widths[i]}}"
            return cell if i == last else f"{cell:<{widths[i]}}"

        return " ".join(pad(i, cell) for i, cell in enumerate(cells))

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
