"""Worktree create, list, and remove operations."""

import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import sh
import typer
from pydantic import BaseModel

from lup.devtools.dev.git_guards import DECLARED_GUARDS, GitGuard, arm, read_guards
from lup.policy.assets.host import project_environment
from lup.devtools.layout import get_tree_dir
from lup.devtools.utils import (
    copy_to_clipboard,
    decode_stderr,
    format_table,
    git,
    refuse_blocked_config_writes,
    short_sha,
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
    try:
        sh.Command("env")(
            "-u", "VIRTUAL_ENV", "uv", "sync", "--all-extras", _cwd=str(worktree_path)
        )
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


# lup: ignore[constant-declaration] — the driver name `.gitattributes` and this
# registration must spell alike for git to find one from the other
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


class SetupStep(BaseModel, ABC, frozen=True):
    """One part of making a worktree usable, checkable on its own.

    A worktree is registered by one git call and made usable by several more,
    so an interruption between them leaves a directory that exists without
    being ready — and a later run that asks only whether the directory exists
    calls that ready. Each step reads its own effect off the worktree instead,
    rather than off a record of what an earlier run meant to do, so a re-run
    finishes exactly what was left and ``already active`` can mean ready
    rather than merely present.
    """

    @abstractmethod
    def label(self) -> str:
        """What to call this step where it has to be named as missing."""

    @abstractmethod
    def satisfied(self) -> bool:
        """Whether this step's effect is already there to be found."""

    @abstractmethod
    def run(self) -> None:
        """Carry the step out; whether it worked is re-read, never reported."""

    def required(self) -> bool:
        """Whether a worktree without this step's effect is unusable.

        A step that answers no is still run and still re-read, and is still
        named where it did not finish — what it does not do is fail the
        command. Anything reaching the network belongs here: a checkout made
        offline is a checkout to work in, and refusing to hand one over
        because a remote could not be told about it would cost more than the
        step itself is worth.
        """
        return True


class MergeDriver(SetupStep, frozen=True):
    """The merge driver ``.gitattributes`` names, registered for this clone."""

    def label(self) -> str:
        return f"the {OWNERSHIP_MERGE_DRIVER} merge driver"

    def satisfied(self) -> bool:
        return all(
            git.out(
                "config",
                "--get",
                f"merge.{OWNERSHIP_MERGE_DRIVER}.{setting}",
                _ok_code=[0, 1],
            )
            for setting in ("name", "driver")
        )

    def run(self) -> None:
        register_merge_driver()


class ArmedGitGuards(SetupStep, frozen=True):
    """The refusals of stale output and a failing gate, installed here.

    A worktree is where a commit is made and where a branch is pushed from,
    so it is where the guards have to be armed: a check that only runs when
    somebody remembers to run it is what let two artifact-stale commits land.

    Armed from the project's own declaration rather than from lup's default
    pair. Reading the default instead made a repository that guards its
    moments differently unable to finish setup at all: the step arms hooks
    that repository never declared, finds its own hooks at those paths and
    reads them as somebody else's, and reports itself unsatisfied on every
    re-run — a worktree that is never ready over guards nobody asked for.
    """

    guards: list[GitGuard] = DECLARED_GUARDS
    worktree: Path

    def label(self) -> str:
        moments = dict.fromkeys(guard.hook for guard in self.guards)
        return f"the {' and '.join(moments)} guards"

    def satisfied(self) -> bool:
        return all(state.armed for state in read_guards(self.guards, self.worktree))

    def run(self) -> None:
        for line in arm(self.guards, self.worktree):
            typer.echo(line)


class RecordedBase(SetupStep, frozen=True):
    """The branch a worktree was cut from, recorded where detection reads it.

    Recorded wherever it is missing rather than only on a branch this run
    created: an interrupted run leaves the branch made and the record unmade,
    and afterwards the two are indistinguishable. A branch that already
    carries a record keeps it.
    """

    branch: str
    origin: str

    def label(self) -> str:
        return f"the base recorded for {self.branch}"

    def already_recorded(self) -> bool:
        """Whether a base is written for this branch, whoever wrote it."""
        return bool(
            git.out(
                "config", "--get", f"branch.{self.branch}.lup-base", _ok_code=[0, 1]
            )
        )

    def satisfied(self) -> bool:
        if self.origin == self.branch:
            return True
        return self.already_recorded()

    def run(self) -> None:
        git("config", f"branch.{self.branch}.lup-base", self.origin)


class PushedBranch(SetupStep, frozen=True):
    """The branch given a remote to track, from the moment it exists.

    An upstream is what lets a later session keep this checkout level without
    asking anybody: a fast-forward pull and a push both name a remote branch,
    and a branch that has none has nothing to be kept level with and no copy
    anywhere but this disk until a pull request is opened. Pushed at creation
    rather than at that point, because the whole span between them is when
    the work happens.
    """

    branch: str

    def label(self) -> str:
        return f"the remote branch tracking {self.branch}"

    def satisfied(self) -> bool:
        return bool(
            git.out("config", "--get", f"branch.{self.branch}.merge", _ok_code=[0, 1])
        )

    def carries_unpushed_work(self) -> bool:
        """Whether this branch holds commits no remote does, unknown counting as yes."""
        counted = git.out(
            "rev-list", "--count", self.branch, "--not", "--remotes", _ok_code=[0, 1]
        )
        return not counted.isdigit() or bool(int(counted))

    def run(self) -> None:
        if self.carries_unpushed_work():
            typer.echo(
                f"Not pushing {self.branch}: it holds commits no remote does, "
                "and setting a checkout up does not publish somebody's work. "
                "`dev pr push` sends them."
            )
            return
        # This push carries a tip some remote already holds, so there is
        # nothing in it for a guard to judge — and a project declaring one at
        # this moment would make setup wait through its whole gate for that
        # nothing. Which is why the branch is only ever given its remote here
        # while that is still true of it.
        git("push", "--no-verify", "-u", "origin", self.branch)

    def required(self) -> bool:
        return False


class CopiedExtras(SetupStep, frozen=True):
    """The gitignored files a checkout needs that ``worktree add`` leaves behind."""

    source: Path
    worktree: Path
    extras: list[str]

    def label(self) -> str:
        return "the gitignored extras"

    def satisfied(self) -> bool:
        return all(
            (self.worktree / rel_path).exists()
            for rel_path in self.extras
            if (self.source / rel_path).exists()
        )

    def run(self) -> None:
        for rel_path in copy_gitignored_extras(self.source, self.worktree, self.extras):
            typer.echo(f"Copied {rel_path}")


class SyncedEnvironment(SetupStep, frozen=True):
    """The environment ``uv sync`` builds inside the worktree.

    Its absence is the expensive failure, and the reason a worktree that only
    exists cannot be called ready: pyright resolves the project from wherever
    else it can and reports errors in code nobody touched, which reads as a
    bug in the change rather than as setup that never ran.
    """

    worktree: Path

    def label(self) -> str:
        return f"the synced environment ({project_environment(self.worktree).name})"

    def satisfied(self) -> bool:
        return project_environment(self.worktree).is_dir()

    def run(self) -> None:
        typer.echo("Running uv sync...")
        sync_dependencies(self.worktree)


def finish(steps: Sequence[SetupStep]) -> Iterator[SetupStep]:
    """Run each step given, yielding the ones still unfinished afterwards.

    Whether a step worked is re-read from the worktree rather than taken from
    whether it raised: a step whose tool exited badly and a step that quietly
    produced nothing leave the same worktree behind, and both are judged by
    what a later run will find rather than by their own account of themselves.
    """
    for step in steps:
        try:
            step.run()
        except sh.ErrorReturnCode as e:
            typer.echo(f"Warning: {step.label()} failed: {decode_stderr(e)}", err=True)
        if not step.satisfied():
            yield step


def descends_from(branch: str, base: str) -> bool:
    """Whether `base` is already in `branch`'s history."""
    try:
        git("merge-base", "--is-ancestor", base, branch)
        return True
    except sh.ErrorReturnCode:
        return False


def register_worktree(name: str, worktree_path: Path, base_branch: str | None) -> None:
    """Register the worktree itself, the one step nothing else can precede."""
    git("worktree", "prune")
    already_exists = branch_exists(name)

    # A named base that re-attaching cannot honour, refused rather than
    # dropped. `worktree add <path> <branch>` takes a branch where it already
    # is, so the flag reaches nothing -- and the caller then writes against a
    # tree they did not ask for, which is the expensive way to find out. The
    # branch is never moved to answer this: whatever sits on it would go.
    if already_exists and base_branch and not descends_from(name, base_branch):
        typer.echo(
            f"{name} already exists and does not descend from {base_branch}, "
            f"so --base {base_branch} would reach nothing: re-attaching takes "
            "a branch where it already stands.\n"
            "Drop --base to re-attach it there, pick a name that does not "
            f"exist yet to cut a fresh branch from {base_branch}, or move "
            f"{name} yourself first if discarding what is on it is meant.",
            err=True,
        )
        raise typer.Exit(1)

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
        typer.echo(f"Error creating worktree: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)


def create(
    name: str,
    no_sync: bool,
    no_copy_data: bool,
    base_branch: str | None,
    launcher: WorktreeLauncher,
    force: bool = False,
    no_record: bool = False,
    clipboard: bool = False,
    extras: list[str] = GITIGNORED_EXTRAS,
    guards: list[GitGuard] = DECLARED_GUARDS,
) -> None:
    """Create a git worktree, re-attach one, or finish one left half-made."""
    # Three config writes follow — the two merge-driver settings and the
    # recorded base — and `worktree add` takes the same lock before any of
    # them, so a confinement that owns `config.lock` is said once here rather
    # than discovered as `File exists` against a half-created worktree.
    #
    refuse_blocked_config_writes()
    current_dir = Path.cwd()

    tree_dir = get_tree_dir()
    worktree_path = tree_dir / name
    resuming = worktree_path.exists() and worktree_is_registered(worktree_path)

    # What a base is recorded from, settled before anything is created. The
    # fallback reads this checkout's current branch, which answers only while
    # there is one: on a detached HEAD the read comes back empty, the record
    # is skipped, and nothing says so — which is why `sync base` reports "Base
    # guessed" long afterwards, on a topology that has since moved. A base
    # nobody can name is refused here instead, where the answer is a flag
    # rather than archaeology.
    recorded = RecordedBase(
        branch=name, origin=base_branch or git.out("branch", "--show-current")
    )
    if not recorded.origin and not no_record and not recorded.already_recorded():
        typer.echo(
            f"Cannot tell what {name} would be cut from: {current_dir} is not on "
            "a branch, so nothing would be recorded as its base and every later "
            "reader would have to guess it from topology.\n"
            "Name it with --base <branch>, or pass --no-record to create the "
            "worktree with no base recorded.",
            err=True,
        )
        raise typer.Exit(1)

    if worktree_path.exists() and not resuming:
        if not force:
            typer.echo(
                f"Directory exists but is not a registered worktree: {worktree_path}\n"
                "Re-run with --force to delete it and create the worktree.",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo(f"Removing stale worktree directory: {worktree_path}")
        shutil.rmtree(worktree_path)

    if not resuming:
        register_worktree(name, worktree_path, base_branch)

    def setup() -> Iterator[SetupStep]:
        """Everything that has to hold before this worktree can be used."""
        yield MergeDriver()
        yield ArmedGitGuards(guards=guards, worktree=worktree_path)
        # lup: solved: `lup-devtools sync base` often reports "Base guessed", because
        # this is where the record fails to happen: the fallback reads the *cwd's*
        # current branch, which is not the branch being worked in once EnterWorktree
        # has moved the session, and records nothing at all when the read comes back
        # empty. Make `worktree create` refuse without `--branch` when it cannot know
        # what base to record, with a `--no-record` to suppress that deliberately.
        if not no_record:
            yield recorded
        yield PushedBranch(branch=name)
        if not no_copy_data:
            yield CopiedExtras(
                source=current_dir, worktree=worktree_path, extras=extras
            )
        if not no_sync:
            yield SyncedEnvironment(worktree=worktree_path)

    pending = [step for step in setup() if not step.satisfied()]

    if resuming and not pending:
        typer.echo(f"Worktree already active: {worktree_path}")
        raise typer.Exit(0)
    if resuming:
        typer.echo(f"Worktree exists, but its setup never finished: {worktree_path}")

    incomplete = list(finish(pending))
    unusable = [step for step in incomplete if step.required()]

    typer.echo()
    typer.echo(f"Worktree path: {worktree_path}")

    for step in incomplete:
        if not step.required():
            typer.echo(
                f"Without {step.label()}, which this worktree is usable without."
            )

    if unusable:
        typer.echo("This worktree is not ready — these steps did not complete:")
        for step in unusable:
            typer.echo(f"  - {step.label()}")
        typer.echo("Re-run the same command to finish them.", err=True)
        raise typer.Exit(1)

    typer.echo("Creating a worktree does not move whoever ran this. To follow it:")
    hint = launcher(worktree_path)
    if hint.agent:
        typer.echo(f"  agent:  {hint.agent}")

    # Opt-in, because most runs of this command are an agent's. The clipboard
    # is the human's own channel and a side effect nobody asked for is still a
    # side effect: an agent that copied here would silently replace whatever
    # its operator had put there, for a line the operator never sees.
    copied = clipboard and copy_to_clipboard(hint.shell)
    typer.echo(
        f"  shell:  {hint.shell}" + ("   [copied to clipboard]" if copied else "")
    )


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
