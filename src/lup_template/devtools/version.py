"""Agent version display, changelog, and bump.

Examples::

    $ uv run lup-devtools version
    $ uv run lup-devtools version --json
    $ uv run lup-devtools version changelog
    $ uv run lup-devtools version changelog --json
    $ uv run lup-devtools version bump minor
"""

from typing import Annotated, Literal, TypedDict

import sh
import typer

from lup.history import parse_semver
from lup.paths import agent_version

from lup_template.devtools.utils import git, output_json


ChangelogCategory = Literal["behavior", "data", "infrastructure"]

app = typer.Typer(invoke_without_command=True, no_args_is_help=False)


class VersionInfo(TypedDict):
    version: str
    latest_tag: str | None
    commits_since_tag: int
    files_changed: list[str]


class ChangelogEntry(TypedDict):
    sha: str
    message: str
    category: str


class ChangelogReport(TypedDict):
    since_tag: str | None
    behavior: list[ChangelogEntry]
    data: list[ChangelogEntry]
    infrastructure: list[ChangelogEntry]


BEHAVIOR_PREFIXES = ("feat", "fix", "refactor")
DATA_PREFIXES = ("data",)


def get_latest_tag() -> str | None:
    try:
        return str(git("describe", "--tags", "--abbrev=0", _ok_code=[0])).strip()
    except sh.ErrorReturnCode:
        return None


def classify_commit(message: str) -> ChangelogCategory:
    lower = message.lower()
    for prefix in BEHAVIOR_PREFIXES:
        if lower.startswith(prefix):
            return "behavior"
    for prefix in DATA_PREFIXES:
        if lower.startswith(prefix):
            return "data"
    return "infrastructure"


@app.callback()
def show(
    ctx: typer.Context,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show agent version, latest tag, and commits since last tag."""
    if ctx.invoked_subcommand is not None:
        return

    latest_tag = get_latest_tag()

    commits_since = 0
    files_changed: list[str] = []
    if latest_tag:
        ref_since = latest_tag
        try:
            commits_since = int(
                str(git("rev-list", "--count", f"{latest_tag}..HEAD")).strip()
            )
        except sh.ErrorReturnCode:
            pass
    else:
        try:
            commits_since = int(str(git("rev-list", "--count", "HEAD")).strip())
        except sh.ErrorReturnCode:
            pass
        try:
            root_commits = str(
                git("rev-list", "--max-parents=0", "HEAD", _ok_code=[0])
            ).strip()
            ref_since = root_commits.splitlines()[0] if root_commits else "HEAD"
        except sh.ErrorReturnCode:
            ref_since = "HEAD"

    try:
        diff_output = str(
            git("diff", "--name-only", f"{ref_since}..HEAD", _ok_code=[0, 128])
        ).strip()
        files_changed = [f for f in diff_output.splitlines() if f]
    except sh.ErrorReturnCode:
        pass

    if as_json:
        info: VersionInfo = {
            "version": agent_version(),
            "latest_tag": latest_tag,
            "commits_since_tag": commits_since,
            "files_changed": files_changed,
        }
        output_json(info)
        return

    typer.echo(f"\nAgent version: {agent_version()}")
    if latest_tag:
        typer.echo(f"Latest tag: {latest_tag} (+{commits_since} commits)")
    else:
        typer.echo("Latest tag: (none)")
    if files_changed:
        typer.echo(f"Files changed: {len(files_changed)}")


@app.command("changelog")
def changelog_cmd(
    since: Annotated[
        str | None,
        typer.Option(
            "--since", "-s", help="Tag or commit to start from (default: latest tag)"
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show changes since a version tag, classified by type."""
    latest_tag = get_latest_tag()
    tag = since or latest_tag
    if not tag:
        ref = (
            str(git("rev-list", "--max-parents=0", "HEAD", _ok_code=[0]))
            .strip()
            .split("\n")[0]
        )
        tag = ref

    try:
        log_output = str(git("log", "--oneline", f"{tag}..HEAD", _ok_code=[0])).strip()
    except sh.ErrorReturnCode:
        typer.echo(f"Could not read log since {tag}")
        raise typer.Exit(1)

    if not log_output:
        typer.echo(f"No commits since {tag}")
        return

    report: ChangelogReport = {
        "since_tag": since or latest_tag,
        "behavior": [],
        "data": [],
        "infrastructure": [],
    }

    for line in log_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        sha = parts[0]
        message = parts[1] if len(parts) > 1 else ""
        category = classify_commit(message)
        entry: ChangelogEntry = {"sha": sha, "message": message, "category": category}
        report[category].append(entry)

    if as_json:
        output_json(report)
        return

    tag_display = since or latest_tag or "(root)"
    typer.echo(f"\n=== Changes since {tag_display} ===\n")

    if report["behavior"]:
        typer.echo("Behavior changes:")
        for e in report["behavior"]:
            typer.echo(f"  {e['sha'][:7]} {e['message']}")

    if report["data"]:
        typer.echo("\nData changes:")
        for e in report["data"]:
            typer.echo(f"  {e['sha'][:7]} {e['message']}")

    if report["infrastructure"]:
        typer.echo("\nInfrastructure changes:")
        for e in report["infrastructure"]:
            typer.echo(f"  {e['sha'][:7]} {e['message']}")

    total = (
        len(report["behavior"]) + len(report["data"]) + len(report["infrastructure"])
    )
    typer.echo(f"\nTotal: {total} commits ({len(report['behavior'])} behavior)")


@app.command("bump")
def bump_cmd(
    level: Annotated[
        str | None,
        typer.Argument(help="Bump level: patch, minor, or major"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
) -> None:
    """Bump agent version and create a git tag."""
    from lup.paths import find_project_root, read_agent_version

    root = find_project_root()
    pyproject = root / "pyproject.toml"
    current = read_agent_version(root)

    semver = parse_semver(current)
    if semver is None:
        typer.echo(f"Version {current} is not in X.Y.Z format")
        raise typer.Exit(1)

    major, minor, patch_v = semver

    if level is None:
        typer.echo(f"Current version: {current}")
        typer.echo("Specify bump level: patch, minor, or major")
        raise typer.Exit(1)

    match level:
        case "patch":
            new_version = f"{major}.{minor}.{patch_v + 1}"
        case "minor":
            new_version = f"{major}.{minor + 1}.0"
        case "major":
            new_version = f"{major + 1}.0.0"
        case _:
            typer.echo(f"Unknown bump level: {level}. Use patch, minor, or major.")
            raise typer.Exit(1)

    if dry_run:
        if as_json:
            output_json({"old": current, "new": new_version, "tag": f"v{new_version}"})
        else:
            typer.echo(f"\nWould bump: {current} → {new_version}")
            typer.echo(f"Would tag: v{new_version}")
        return

    content = pyproject.read_text()
    new_content = content.replace(
        f'agent_version = "{current}"', f'agent_version = "{new_version}"'
    )
    if new_content == content:
        typer.echo(f"Could not find 'agent_version = \"{current}\"' in pyproject.toml")
        raise typer.Exit(1)
    pyproject.write_text(new_content)

    git.add(str(pyproject))
    git.commit("-m", f"chore(version): bump {current} → {new_version}")
    git.tag(f"v{new_version}")

    if as_json:
        output_json({"old": current, "new": new_version, "tag": f"v{new_version}"})
    else:
        typer.echo(f"\nBumped: {current} → {new_version}")
        typer.echo(f"Tag: v{new_version}")
