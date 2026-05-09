"""Version bump operations.

Mechanical helpers for ``/lup:bump``.

Examples::

    $ uv run lup-devtools bump status
    $ uv run lup-devtools bump status --json
    $ uv run lup-devtools bump apply minor
    $ uv run lup-devtools bump apply patch --dry-run
"""

import logging
import re
from pathlib import Path
from typing import Annotated

import sh
import typer
from pydantic import BaseModel

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)

git = sh.Command("git").bake("--no-pager")


class CommitEntry(BaseModel):
    sha: str
    message: str


class BumpStatusResult(BaseModel):
    current_version: str
    latest_tag: str | None
    ref_since: str
    commits: list[CommitEntry]
    files_changed: list[str]


class BumpApplyResult(BaseModel):
    old_version: str
    new_version: str
    version_file: str
    tag: str


def find_version_file() -> Path:
    """Find version.py under src/*/."""
    src = Path("src")
    if not src.is_dir():
        typer.echo("Error: src/ directory not found", err=True)
        raise typer.Exit(1)

    for pkg_dir in sorted(src.iterdir()):
        version_file = pkg_dir / "version.py"
        if version_file.is_file():
            return version_file

    typer.echo("Error: no version.py found under src/*/", err=True)
    raise typer.Exit(1)


def read_version(version_file: Path) -> str:
    """Extract AGENT_VERSION string from version.py."""
    text = version_file.read_text()
    match = re.search(r'AGENT_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        typer.echo(f"Error: AGENT_VERSION not found in {version_file}", err=True)
        raise typer.Exit(1)
    return match.group(1)


def compute_new_version(current: str, level: str) -> str:
    """Compute new version from current version and bump level."""
    parts = current.split(".")
    if len(parts) != 3:
        typer.echo(f"Error: version {current!r} is not semver (x.y.z)", err=True)
        raise typer.Exit(1)

    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        typer.echo(f"Error: version {current!r} has non-numeric parts", err=True)
        raise typer.Exit(1)

    match level:
        case "major":
            return f"{major + 1}.0.0"
        case "minor":
            return f"{major}.{minor + 1}.0"
        case "patch":
            return f"{major}.{minor}.{patch + 1}"
        case _:
            typer.echo(f"Error: invalid level {level!r} (use major/minor/patch)", err=True)
            raise typer.Exit(1)


@app.command("status")
def status_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show current version, latest tag, and changes since last bump."""
    version_file = find_version_file()
    current = read_version(version_file)

    tag_output = str(
        git("tag", "--list", "v*", "--sort=-version:refname", _ok_code=[0])
    ).strip()
    tags = tag_output.splitlines() if tag_output else []
    latest_tag = tags[0] if tags else None

    ref_since = latest_tag or "HEAD~50"

    log_output = str(
        git("log", "--oneline", f"{ref_since}..HEAD", _ok_code=[0, 128])
    ).strip()
    commits = []
    for line in log_output.splitlines():
        if not line:
            continue
        parts = line.split(maxsplit=1)
        sha = parts[0]
        message = parts[1] if len(parts) > 1 else ""
        commits.append(CommitEntry(sha=sha, message=message))

    diff_output = str(
        git("diff", "--stat", "--name-only", f"{ref_since}..HEAD", _ok_code=[0, 128])
    ).strip()
    files_changed = [f for f in diff_output.splitlines() if f]

    result = BumpStatusResult(
        current_version=current,
        latest_tag=latest_tag,
        ref_since=ref_since,
        commits=commits,
        files_changed=files_changed,
    )

    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Version: {current}")
        typer.echo(f"Latest tag: {latest_tag or '(none)'}")
        typer.echo(f"Commits since {ref_since}: {len(commits)}")
        if commits:
            typer.echo()
            for c in commits[:20]:
                typer.echo(f"  {c.sha} {c.message}")
            if len(commits) > 20:
                typer.echo(f"  ... and {len(commits) - 20} more")
        typer.echo(f"\nFiles changed: {len(files_changed)}")


@app.command("apply")
def apply_cmd(
    level: Annotated[
        str,
        typer.Argument(help="Bump level: major, minor, or patch"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
) -> None:
    """Apply a version bump and create a git tag."""
    version_file = find_version_file()
    current = read_version(version_file)
    new_version = compute_new_version(current, level)
    tag = f"v{new_version}"

    if dry_run:
        typer.echo(f"Would bump: {current} -> {new_version}")
        typer.echo(f"Would update: {version_file}")
        typer.echo(f"Would create tag: {tag}")
        return

    text = version_file.read_text()
    text = text.replace(f'AGENT_VERSION = "{current}"', f'AGENT_VERSION = "{new_version}"')
    version_file.write_text(text)
    typer.echo(f"Updated {version_file}: {current} -> {new_version}")

    try:
        git("tag", tag)
        typer.echo(f"Created tag: {tag}")
    except sh.ErrorReturnCode as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        typer.echo(f"Warning: tag creation failed: {stderr}", err=True)

    result = BumpApplyResult(
        old_version=current,
        new_version=new_version,
        version_file=str(version_file),
        tag=tag,
    )
    print(result.model_dump_json(indent=2))
