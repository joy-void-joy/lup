"""Scan tracked files for unresolved `# claude:` / `// claude:` feedback notes.

Examples::

    $ uv run lup-devtools dev comments
    $ uv run lup-devtools dev comments --json
"""

from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.markers import MARKER_RE, FeedbackComment, find_feedback
from lup_template.devtools.utils import decode_stderr, git, output_json

MARKDOWN_SUFFIXES = {
    ".md",
    ".markdown",
}  # claude: Huh? Why is this needed? We can just always scan for # claude, // claude, etc... in all files


class FoundComment(BaseModel):
    file: str
    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str
    context: str


def scan_feedback() -> list[FoundComment]:
    """All unresolved feedback notes across tracked text files."""
    results: list[FoundComment] = []
    for rel in str(git("ls-files")).splitlines():
        path = Path(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        is_md = path.suffix.lower() in MARKDOWN_SUFFIXES
        lines = text.splitlines()
        for comment in find_feedback(text, is_markdown=is_md):
            context = "\n".join(lines[comment.read_start - 1 : comment.read_end])
            results.append(
                FoundComment(file=rel, context=context, **comment.model_dump())
            )
    return results


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
    branch = str(git("rev-parse", "--abbrev-ref", "HEAD")).strip()
    if not branch.startswith("resolve/"):
        typer.echo(
            f"Refusing to clear markers: HEAD is '{branch}', not a resolve/* "
            "branch. Markers are stripped only inside a disposable resolve "
            "worktree; on a real checkout, edit the note (which prompts) or "
            "merge a resolve branch.",
            err=True,
        )
        raise typer.Exit(1)

    def strip_span(lines: list[str], comment: FeedbackComment) -> None:
        head = lines[comment.start_line - 1]
        match = MARKER_RE.search(head)
        if match is not None and head[: match.start()].strip():
            lines[comment.start_line - 1] = head[: match.start()].rstrip()
        else:
            del lines[comment.start_line - 1 : comment.end_line]

    by_file: dict[str, set[int]] = {}
    for target in targets:
        rel, _, line_str = target.rpartition(":")
        if not rel or not line_str.isdigit():
            typer.echo(f"Skipping malformed target: {target}", err=True)
            continue
        by_file.setdefault(rel, set()).add(int(line_str))

    for rel, wanted in by_file.items():
        path = Path(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            typer.echo(f"Skipping unreadable file: {rel}", err=True)
            continue
        is_md = path.suffix.lower() in MARKDOWN_SUFFIXES
        lines = text.splitlines()
        spans = {c.start_line: c for c in find_feedback(text, is_markdown=is_md)}
        removed = 0
        for line_no in sorted(wanted, reverse=True):
            comment = spans.get(line_no)
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
    found = scan_feedback()
    if not found:
        typer.echo("No # claude: comments to commit.")
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
        typer.echo(f"Nothing committed: {decode_stderr(e).strip()}")
        return
    typer.echo(f"Committed {len(found)} prompt(s) across {len(files)} file(s).")


def report(as_json: bool, commit: bool) -> None:
    """List unresolved feedback comments; --json for tooling, --commit to snapshot them."""
    if commit:
        commit_prompts()
        return
    found = scan_feedback()
    if as_json:
        output_json([comment.model_dump() for comment in found])
        return
    if not found:
        typer.echo("No unresolved # claude: comments.")
        return
    for comment in found:
        typer.echo(
            f"{comment.file}:{comment.start_line}-{comment.end_line}  "
            f"(read {comment.read_start}-{comment.read_end})"
        )
        typer.echo(f"    {comment.text}")
    files = {comment.file for comment in found}
    typer.echo(f"\n{len(found)} comment(s) in {len(files)} file(s)")


# claude: This does not seem wired in? The docstring say we can call lup-devtools run comments, but I don't see how that works here
