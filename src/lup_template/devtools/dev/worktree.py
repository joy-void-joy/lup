"""Worktree create, list, and remove operations."""

import shutil
from pathlib import Path

import sh
import typer

from lup_template.devtools.utils import (
    copy_to_clipboard,
    decode_stderr,
    format_table,
    git,
    short_sha,
    uv,
)


# Gitignored paths that `git worktree add` does not carry over but a working
# worktree still needs (local secrets/settings, logs, downstream `refs/`
# symlinks); `create` copies them into the new worktree unless --no-copy-data.
GITIGNORED_EXTRAS = [
    ".env.local",
    "downstream.json.local",
    ".claude/settings.local.json",
    "logs",
    "refs",
]


def branch_exists(branch: str) -> bool:
    """Check if a git branch exists (local only)."""
    try:
        git("rev-parse", "--verify", f"refs/heads/{branch}")
        return True
    except sh.ErrorReturnCode:
        return False


def worktree_is_registered(path: Path) -> bool:
    """Check if a path is registered as a git worktree (even if dir is missing)."""
    output = str(git("worktree", "list", "--porcelain"))
    resolved = str(path.resolve())
    for line in output.splitlines():
        if line.startswith("worktree ") and line.split(" ", 1)[1] == resolved:
            return True
    return False


def get_tree_dir() -> Path:
    """Locate the ``tree/`` directory that holds sibling worktrees.

    Two checkout layouts are supported. In the bare-repo layout the current
    checkout is itself a worktree living inside ``tree/``, so ``tree/`` is the
    parent. Otherwise ``tree/`` sits at the current directory or an ancestor,
    so walking upward lets the command run from anywhere inside the checkout.
    """
    cwd = Path.cwd().resolve()

    if cwd.parent.name == "tree":
        return cwd.parent

    for directory in (cwd, *cwd.parents):
        tree = directory / "tree"
        if tree.is_dir():
            return tree

    typer.echo("Error: Could not find tree/ directory", err=True)
    raise typer.Exit(1)


def create(
    name: str,
    no_sync: bool,
    no_copy_data: bool,
    base_branch: str | None,
    force: bool = False,
) -> None:
    """Create or re-attach a git worktree."""
    current_dir = Path.cwd()

    tree_dir = get_tree_dir()
    worktree_path = tree_dir / name
    already_exists = branch_exists(name)

    if worktree_path.exists():
        if worktree_is_registered(worktree_path):
            typer.echo(f"Worktree already active: {worktree_path}")
            raise typer.Exit(0)
        if not force:
            typer.echo(
                f"Directory exists but is not a registered worktree: {worktree_path}\n"
                "Re-run with --force to delete it and create the worktree.",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo(f"Removing stale worktree directory: {worktree_path}")
        shutil.rmtree(worktree_path)

    git("worktree", "prune")

    if already_exists:
        typer.echo(f"Re-attaching worktree: {worktree_path}")
        typer.echo(f"Existing branch: {name}")
    else:
        typer.echo(f"Creating worktree: {worktree_path}")
        typer.echo(f"New branch: {name}")

    try:
        if already_exists:
            git("worktree", "add", str(worktree_path), name)
        elif base_branch:
            git("worktree", "add", str(worktree_path), "-b", name, base_branch)
        else:
            git("worktree", "add", str(worktree_path), "-b", name)
    except sh.ErrorReturnCode as e:
        typer.echo(f"Error creating worktree: {decode_stderr(e)}")
        raise typer.Exit(1)

    if not no_copy_data:
        for rel_path in GITIGNORED_EXTRAS:
            src = current_dir / rel_path
            if not src.exists():
                continue
            dst = worktree_path / rel_path
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                typer.echo(f"Copied {rel_path}/")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                typer.echo(f"Copied {rel_path}")

    if not no_sync:
        typer.echo("Running uv sync...")
        try:
            uv("sync", _cwd=str(worktree_path))
        except sh.ErrorReturnCode as e:
            typer.echo(f"Warning: uv sync failed: {decode_stderr(e)}")

    typer.echo()
    cd_command = f"cd /; cd {worktree_path}; claude"

    if copy_to_clipboard(cd_command):
        typer.echo(f"Copied to clipboard: {cd_command}")
    else:
        typer.echo("Done! To switch to the new worktree:")
        typer.echo(f"  {cd_command}")


def worktree_status(path: str) -> str:
    """Check if a worktree has uncommitted changes."""
    try:
        status = str(git("-C", path, "status", "--porcelain", _ok_code=[0])).strip()
        return "dirty" if status else "clean"
    except sh.ErrorReturnCode:
        return "?"


def list_worktrees() -> None:
    """List all git worktrees with branch and status info."""
    output = str(git("worktree", "list", "--porcelain"))

    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in output.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = short_sha(line.split(" ", 1)[1])
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
        elif line == "bare":
            current["bare"] = "true"
        elif line == "prunable":
            current["prunable"] = "true"

    if current:
        entries.append(current)

    if not entries:
        typer.echo("No worktrees found")
        return

    cwd = str(Path.cwd().resolve())

    typer.echo(f"\n=== Worktrees ({len(entries)}) ===\n")
    rows: list[tuple[str, str, str, str]] = []
    for entry in entries:
        branch = entry.get("branch", "(bare)" if entry.get("bare") else "(detached)")
        head = entry.get("head", "")
        path = entry.get("path", "")
        marker = "* " if path == cwd else "  "

        if not entry.get("bare") and Path(path).is_dir():
            status = worktree_status(path)
        else:
            status = ""

        flag_str = " [prunable]" if entry.get("prunable") else ""
        rows.append((f"{marker}{branch}", head, status, f"{path}{flag_str}"))

    typer.echo(format_table(("Branch", "HEAD", "Status", "Path"), rows))


def remove(name: str, force: bool) -> None:
    """Remove a git worktree."""
    path = Path(name)

    if not path.is_absolute():
        tree_dir = get_tree_dir()
        path = tree_dir / name

    if not worktree_is_registered(path):
        typer.echo(f"Not a registered worktree: {path}", err=True)
        raise typer.Exit(1)

    try:
        args = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        git(*args)
        typer.echo(f"Removed worktree: {path}")
    except sh.ErrorReturnCode as e:
        typer.echo(f"Error removing worktree: {decode_stderr(e)}", err=True)
        if not force:
            typer.echo("Use --force to remove even if dirty")
        raise typer.Exit(1)
