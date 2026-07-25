"""Worktree create, list, and remove operations."""

import shutil
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup_template.devtools.harness.launch import relocation_hint
from lup_template.devtools.utils import (
    copy_to_clipboard,
    decode_stderr,
    format_table,
    git,
    short_sha,
    uv,
)


# Gitignored paths that `git worktree add` does not carry over but a working
# worktree still needs (local secrets/settings, logs, sync `refs/`
# symlinks); `create` copies them into the new worktree unless --no-copy-data.
GITIGNORED_EXTRAS = [
    ".env.local",
    "sync.json.local",
    "downstream.json.local",  # legacy sync.json.local name, still read via fallback
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
    resolved = str(path.resolve())
    return any(
        line == f"worktree {resolved}"
        for line in git.lines("worktree", "list", "--porcelain")
    )


OWNERSHIP_MERGE_DRIVER = "lup-ownership"


def register_merge_driver() -> None:
    """Teach this clone the merge driver ``.gitattributes`` names.

    A driver that exits without writing leaves git holding one side, which is
    the whole resolution a generated digest manifest can have — regeneration
    settles it afterwards. Git resolves driver names from config alone, so no
    repository can ship this and every clone registers it once; the config is
    shared with every worktree of the same repository.
    """
    git("config", f"merge.{OWNERSHIP_MERGE_DRIVER}.name", "keep one side, regenerate")
    git("config", f"merge.{OWNERSHIP_MERGE_DRIVER}.driver", "true")


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

    register_merge_driver()

    if not already_exists:
        origin = base_branch or git.out("branch", "--show-current")
        if origin and origin != name:
            git("config", f"branch.{name}.lup-base", origin)

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
    typer.echo(f"Worktree path: {worktree_path}")
    typer.echo("Creating a worktree does not move whoever ran this. To follow it:")
    hint = relocation_hint(worktree_path)
    if hint.agent:
        typer.echo(f"  agent:  {hint.agent}")

    if copy_to_clipboard(hint.shell):
        typer.echo(f"  shell:  {hint.shell}   [copied to clipboard]")
    else:
        typer.echo(f"  shell:  {hint.shell}")


def worktree_status(path: str) -> str:
    """Check if a worktree has uncommitted changes."""
    try:
        dirty = git.lines("-C", path, "status", "--porcelain", _ok_code=[0])
        return "dirty" if dirty else "clean"
    except sh.ErrorReturnCode:
        return "?"


class WorktreeEntry(BaseModel):
    """One record of ``git worktree list --porcelain``."""

    path: str = ""
    head: str = ""
    branch: str = ""
    bare: bool = False
    prunable: bool = False


def list_worktrees() -> None:
    """List all git worktrees with branch and status info."""
    entries: list[WorktreeEntry] = []  # lup: ignore[empty-collection] — record fold
    current = WorktreeEntry()

    for line in git.lines("worktree", "list", "--porcelain"):
        if not line:
            if current.path:
                entries.append(current)
                current = WorktreeEntry()
            continue
        if line.startswith("worktree "):
            current.path = line.removeprefix("worktree ")
        elif line.startswith("HEAD "):
            current.head = short_sha(line.removeprefix("HEAD "))
        elif line.startswith("branch "):
            current.branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif line == "bare":
            current.bare = True
        elif line == "prunable":
            current.prunable = True

    if current.path:
        entries.append(current)

    if not entries:
        typer.echo("No worktrees found")
        return

    cwd = str(Path.cwd().resolve())

    def row(entry: WorktreeEntry) -> list[str]:
        branch = entry.branch or ("(bare)" if entry.bare else "(detached)")
        marker = "* " if entry.path == cwd else "  "
        in_dir = not entry.bare and Path(entry.path).is_dir()
        dirtiness = worktree_status(entry.path) if in_dir else ""
        flag = " [prunable]" if entry.prunable else ""
        return [f"{marker}{branch}", entry.head, dirtiness, f"{entry.path}{flag}"]

    typer.echo(f"\n=== Worktrees ({len(entries)}) ===\n")
    typer.echo(
        format_table(("Branch", "HEAD", "Status", "Path"), [row(e) for e in entries])
    )


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
