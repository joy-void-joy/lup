"""Scan tracked files for inline markers.

Backs two `lup-devtools dev` commands (wired in
`lup_template.devtools.dev.app`):

- `dev comments` lists unresolved `# lup:` / `// lup:` feedback notes;
  `report`, `commit_prompts`, and `clear_markers` back its default listing
  and its `--commit` / `--clear` modes.
- `dev todos` lists `TEMPLATE:` customization markers — the template's
  domain decision points that `/lup:init` walks one by one.

Examples::

    $ uv run lup-devtools dev comments
    $ uv run lup-devtools dev comments --json
    $ uv run lup-devtools dev comments --commit
    $ uv run lup-devtools dev comments --clear path/to/file.py:42
    $ uv run lup-devtools dev todos --json
"""

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.codescan.markers import (
    MARKER_RE,
    TEMPLATE_MARKER_RE,
    MarkerComment,
    find_feedback,
    find_markers,
    scan_mode_for,
)
from lup_template.devtools.utils import decode_stderr, git, output_json


class FoundComment(BaseModel):
    file: str
    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str
    context: str


def scan_tracked(
    find: Callable[[str, str], list[MarkerComment]],
) -> list[FoundComment]:
    """Run one marker scan across every tracked text file.

    `find` maps a file's text and its scan mode to the markers it holds —
    :func:`lup.codescan.markers.find_feedback` for review notes, or
    :func:`lup.codescan.markers.find_markers` bound to another convention.
    """
    results: list[FoundComment] = []  # lup: ignore[empty-collection] — scan fold
    for rel in git.lines("ls-files"):
        path = Path(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        for comment in find(text, scan_mode_for(path)):
            context = "\n".join(lines[comment.read_start - 1 : comment.read_end])
            results.append(
                FoundComment(file=rel, context=context, **comment.model_dump())
            )
    return results


def find_todos(text: str, mode: str) -> list[MarkerComment]:
    """Customization markers in one file's text (the `TEMPLATE:` convention)."""
    return find_markers(text, mode, marker=TEMPLATE_MARKER_RE)


def clear_markers(targets: list[str]) -> None:
    """Remove specific feedback markers named as `file:line` targets.

    The execute workflow calls this at fork time to strip a concern's own
    notes from an editor's throwaway worktree, so the editor fixes the
    generalized spec without ever seeing — or being able to cheat by
    deleting — its markers. A standalone comment line is dropped whole; an
    inline trailing marker keeps its code and loses only the comment.

    Refuses to run unless HEAD is a disposable `resolve/*` branch, so a note
    can never be silently stripped from a real checkout — there, a note is
    removed only through an `Edit` (which prompts for review) or a reviewed
    merge of a resolve branch.
    """
    branch = git.out("rev-parse", "--abbrev-ref", "HEAD")
    if not branch.startswith("resolve/"):
        typer.echo(
            f"Refusing to clear markers: HEAD is '{branch}', not a resolve/* "
            "branch. Markers are stripped only inside a disposable resolve "
            "worktree; on a real checkout, edit the note (which prompts) or "
            "merge a resolve branch.",
            err=True,
        )
        raise typer.Exit(1)

    def strip_span(lines: list[str], comment: MarkerComment) -> None:
        head = lines[comment.start_line - 1]
        match = MARKER_RE.search(head)
        head_code = head[: match.start()] if match is not None else ""
        prefix_code = head_code.strip()
        if match is not None and prefix_code:
            lines[comment.start_line - 1] = head[: match.start()].rstrip()
        else:
            del lines[comment.start_line - 1 : comment.end_line]

    by_file: defaultdict[str, list[int]] = defaultdict(list)
    for target in targets:
        rel, _, line_str = target.rpartition(":")  # lup: ignore[string-split] — CLI arg
        if not rel or not line_str.isdigit():
            typer.echo(f"Skipping malformed target: {target}", err=True)
            continue
        if int(line_str) not in by_file[rel]:
            by_file[rel].append(int(line_str))

    for rel, wanted in by_file.items():
        path = Path(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            typer.echo(f"Skipping unreadable file: {rel}", err=True)
            continue
        lines = text.splitlines()
        spans = {c.start_line: c for c in find_feedback(text, scan_mode_for(path))}
        removed = 0
        for line_no in sorted(wanted, reverse=True):
            comment = spans.get(line_no)  # lup: ignore[dict-get] — span lookup
            if comment is None:
                typer.echo(f"No marker at {rel}:{line_no}", err=True)
                continue
            strip_span(lines, comment)
            removed += 1
        trailing = "\n" if text.endswith("\n") else ""
        path.write_text("\n".join(lines) + trailing, encoding="utf-8")
        typer.echo(f"Cleared {removed} marker(s) from {rel}")


def commit_prompts() -> None:
    """Snapshot the current feedback prompts into one commit before resolving them."""
    found = scan_tracked(find_feedback)
    if not found:
        typer.echo("No # lup: comments to commit.")
        return
    files = sorted({comment.file for comment in found})
    git("add", "--", *files)
    body = "\n".join(
        f"{comment.file}:{comment.start_line} {comment.text}" for comment in found
    )
    subject = f"chore(review): {len(found)} inline feedback prompt(s)"
    try:
        git("commit", "-m", f"{subject}\n\n{body}")
    except sh.ErrorReturnCode as e:
        typer.echo(f"Nothing committed: {decode_stderr(e)}")
        return
    typer.echo(f"Committed {len(found)} prompt(s) across {len(files)} file(s).")


def render(found: list[FoundComment], *, as_json: bool, empty: str) -> None:
    """Print one scan's results as a listing or JSON (same shape either way)."""
    if as_json:
        output_json([comment.model_dump() for comment in found])
        return
    if not found:
        typer.echo(empty)
        return
    for comment in found:
        typer.echo(
            f"{comment.file}:{comment.start_line}-{comment.end_line}  "
            f"(read {comment.read_start}-{comment.read_end})"
        )
        typer.echo(f"    {comment.text}")
    files = {comment.file for comment in found}
    typer.echo(f"\n{len(found)} comment(s) in {len(files)} file(s)")


def report(as_json: bool, commit: bool) -> None:
    """List unresolved feedback comments; --json for tooling, --commit to snapshot them."""
    if commit:
        commit_prompts()
        return
    render(
        scan_tracked(find_feedback),
        as_json=as_json,
        empty="No unresolved # lup: comments.",
    )


def todos(as_json: bool) -> None:
    """List `TEMPLATE:` customization markers across tracked files."""
    render(
        scan_tracked(find_todos),
        as_json=as_json,
        empty="No TEMPLATE: markers — no customization decisions pending.",
    )
