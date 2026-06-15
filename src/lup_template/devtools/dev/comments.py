"""Scan tracked files for unresolved `# claude:` / `// claude:` feedback notes.

Examples::

    $ uv run lup-devtools dev comments
    $ uv run lup-devtools dev comments --json
"""

from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.markers import find_feedback
from lup_template.devtools.utils import decode_stderr, git, output_json

MARKDOWN_SUFFIXES = {".md", ".markdown"} #claude: Huh? Why is this needed? We can just always scan for # claude, // claude, etc... in all files


class FoundComment(BaseModel):
    file: str
    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str


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
        for comment in find_feedback(text, is_markdown=is_md):
            results.append(FoundComment(file=rel, **comment.model_dump()))
    return results


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