"""Worktree create, list, and remove operations."""

import shutil
from collections.abc import Callable
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.devtools.layout import get_tree_dir
from lup.devtools.utils import (
    copy_to_clipboard,
    decode_stderr,
    format_table,
    git,
    refuse_blocked_config_writes,
    short_sha,
    uv,
)


class RelocationHint(BaseModel):
    """How the harness a command is running under follows a new worktree."""

    agent: str
    shell: str


type WorktreeLauncher = Callable[[Path], RelocationHint]


# Gitignored paths that `git worktree add` does not carry over but a working
# worktree still needs (local secrets/settings, logs, sync `refs/`
# symlinks); `create` copies them into the new worktree unless --no-copy-data.
GITIGNORED_EXTRAS = [
    ".env.local",
    "sync.json.local",
    "downstream.json.local",  # legacy sync.json.local name, still read via fallback
    ".claude/settings.local.json",
    ".codex/config.local.toml",
    "logs",
    "refs",
]


def copy_gitignored_extras(
    source_root: Path,
    worktree_path: Path,
    extras: list[str] = GITIGNORED_EXTRAS,
) -> list[str]:
    """Copy each present gitignored extra into a worktree; report what moved."""
    copied: list[str] = []  # lup: ignore[empty-collection] — copy report fold
    for rel_path in extras:
        src = source_root / rel_path
        if not src.exists():
            continue
        dst = worktree_path / rel_path
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(rel_path)
    return copied


def sync_dependencies(worktree_path: Path) -> None:
    """Sync one worktree's environment; warn instead of failing the caller."""
    # lup: A fresh worktree is not usable on creation, in two ways reported from
    # downstream. This sync takes no extras, so the environment lacks what the
    # source tree has and pyright reports errors in files nobody touched — an
    # agent then cannot tell an environmental failure from its own, and reasons
    # about a bug that is not there. Sync the extras the source tree declares,
    # or have `dev check` label environment-caused failures distinctly from code
    # ones. Second, every `uv run` from a worktree prints `VIRTUAL_ENV=... does
    # not match the project environment path`, dozens of times per session, in
    # front of the output that was actually wanted.
    try:
        uv("sync", _cwd=str(worktree_path))
    except sh.ErrorReturnCode as e:
        typer.echo(f"Warning: uv sync failed: {decode_stderr(e)}")


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


def create(
    name: str,
    no_sync: bool,
    no_copy_data: bool,
    base_branch: str | None,
    launcher: WorktreeLauncher,
    force: bool = False,
    extras: list[str] = GITIGNORED_EXTRAS,
) -> None:
    """Create or re-attach a git worktree."""
    # Three config writes follow — the two merge-driver settings and the
    # recorded base — and `worktree add` takes the same lock before any of
    # them, so a confinement that owns `config.lock` is said once here rather
    # than discovered as `File exists` against a half-created worktree.
    refuse_blocked_config_writes()
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

    # lup: The mechanism behind the note below, measured downstream: the sandbox
    # bind-mounts `/dev/null` over `.git/config.lock` and `.git/config.worktree`
    # (device 1:3, read-only devtmpfs) and mounts `.git/config` read-only, so git
    # cannot take its lock and every config write fails. This function does three
    # of them. It reaches far past `worktree create`: the resolver leases a
    # worktree per concern through this same path, so a sandboxed run dies at the
    # first lease with a message naming nothing about the sandbox. Detect it —
    # `.git/config` read-only, or `.git/config.lock` a device node — and say "git
    # config writes are blocked by the sandbox, rerun outside it" instead of
    # letting `File exists` send a reader after a stale lock that does not exist.
    #
    # lup: This config write is what fails under the sandbox, and the reported
    # cause is wrong. Sibling worktrees are *not* read-only — writing into
    # `tree/main/` succeeds, because the allowlist covers the whole repository
    # root. What fails is git's lock protocol: `config.lock` sits on a read-only
    # mount, so no config write can acquire it and git reports `File exists`,
    # which reads like a stale lock somebody forgot to delete. It is not one, and
    # deleting it does nothing. `git worktree prune`/`remove` fail the same way
    # on the admin dirs. Any fix deriving writable paths from the worktree set
    # misses this entirely.
    #
    # lup: `lup-devtools sync base` often reports "Base guessed", because this is
    # where the record fails to happen: the fallback reads the *cwd's* current
    # branch, which is not the branch being worked in once EnterWorktree has
    # moved the session, and records nothing at all when the read comes back
    # empty. Make `worktree create` refuse without `--branch` when it cannot know
    # what base to record, with a `--no-record` to suppress that deliberately.
    if not already_exists:
        origin = base_branch or git.out("branch", "--show-current")
        if origin and origin != name:
            git("config", f"branch.{name}.lup-base", origin)

    if not no_copy_data:
        for rel_path in copy_gitignored_extras(current_dir, worktree_path, extras):
            typer.echo(f"Copied {rel_path}")

    if not no_sync:
        typer.echo("Running uv sync...")
        sync_dependencies(worktree_path)

    typer.echo()
    typer.echo(f"Worktree path: {worktree_path}")
    typer.echo("Creating a worktree does not move whoever ran this. To follow it:")
    hint = launcher(worktree_path)
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
    # `worktree remove` rewrites the admin directory the same lock guards, so
    # it fails exactly as `create` does and gets the same diagnosis.
    refuse_blocked_config_writes()
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
