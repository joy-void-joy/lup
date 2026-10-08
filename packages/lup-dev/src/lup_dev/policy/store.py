"""The store: snapshot, compare, set aside what was committed elsewhere, restore, save.

Each worktree has a store outside it (`layout.StoreLayout`): a bare repository
holding its snapshots, written through a private index (the store's own), with
the worktree as git's work tree (`docs/judging-writes.md`, *After a call: the
checkpoint*). Ignored files are left out, as the worktree's `.gitignore` says,
and so is `.lup/`, where saved versions wait. The accepted tree and each session's
starting tree are refs in the store, so they're kept as long as they're needed.

What was committed elsewhere, and what git merges from it, is set aside
(`Elsewhere`). A move of the worktree's `HEAD` is read from its repository: the
files it changed, and each as the commit has it.

git runs with `core.fsmonitor` and hooks turned off, in the store and in the
worktree's own repository alike: the effects probe saw a planted `core.fsmonitor`
run inside a call.
"""

import os
from functools import cached_property
from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel

from lup.types import Model, MutableModel
from lup_dev.errors import LupDevError
from lup_dev.layout import CheckoutLayout, StoreLayout


class StoreError(LupDevError):
    """git refused something the store asked of it."""


def read_model[M: BaseModel](path: Path, model: type[M]) -> M | None:
    """Read the model stored at `path`, or return none where nothing is stored."""
    if not path.is_file():
        return None
    return model.model_validate_json(path.read_text())


def write_model(path: Path, value: BaseModel) -> None:
    """Store `value` at `path`, replacing what was there in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial")
    partial.write_text(value.model_dump_json(indent=2))
    partial.replace(path)


def nul_separated(output: bytes) -> list[str]:
    r"""Read git's `-z` output: paths, each ended by a NUL byte.

    >>> nul_separated(b"a.py\x00dir/b c.py\x00")
    ['a.py', 'dir/b c.py']
    """
    # lup: ignore("string-split", why="git's -z format ends each path with a NUL")
    fields = output.split(b"\0")
    return [field.decode() for field in fields if field]


class Git(Model):
    """git, run in one place with what could run code turned off."""

    arguments: list[str] = []
    """Arguments before the command: which repository and work tree."""
    cwd: Path

    def run(
        self, *arguments: str, stdin: bytes | None = None, ok: list[int] | None = None
    ) -> sh.RunningCommand:
        """Run git with `arguments`; raise `StoreError` on an exit code not in `ok`."""
        safe = [
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.quotePath=false",
            "-c",
            "core.autocrlf=false",
        ]
        try:
            return sh.Command("git")(
                *safe,
                *self.arguments,
                *arguments,
                _in=stdin,
                _cwd=str(self.cwd),
                _ok_code=ok or [0],
                _tty_out=False,
                _return_cmd=True,
            )
        except sh.ErrorReturnCode as failed:
            message = f"git {' '.join(arguments)} failed: {failed.stderr.decode()}"
            raise StoreError(message) from failed

    def text(self, *arguments: str) -> str:
        """Run git and return what it printed, without the trailing newline."""
        return self.run(*arguments).stdout.decode().strip()


class Changed(Model):
    """One path that differs between two trees."""

    path: Path
    kind: Literal["added", "modified", "deleted"]


class Held(Model):
    """A change waiting for the operator's answer, which checkpoints leave alone."""

    hold: str
    path: Path
    blob: str
    """The held content's object id."""


class WorktreeState(MutableModel):
    """What the store remembers about a worktree between checkpoints."""

    tips: list[str] = []
    """Every commit a ref of the worktree's repository named at the last checkpoint."""
    saved: int = 0
    """How many refusals have saved versions, numbering the next one."""
    holding: list[Held] = []


class Heads(MutableModel):
    """Each worktree's `HEAD` at its last checkpoint, for one repository.

    A worktree missing here has no `HEAD` recorded yet; one recorded as none had
    no commit at its last checkpoint.
    """

    worktrees: dict[Path, str | None] = {}


class Entry(Model):
    """One path as a commit has it, its content copied into the store."""

    path: Path
    mode: str = ""
    """Its file mode, as git writes it: `100644`, `100755`, `120000`."""
    blob: str | None = None
    """Its object id, stored in the store too; none where the commit lacks the path."""


class Merge(Model):
    """git's merge of two commits, remade: its tree, and the paths it couldn't merge."""

    tree: str
    """The merged tree, in the worktree's repository."""
    conflicted: list[Path] = []


class Store(Model):
    """The store of one worktree."""

    layout: StoreLayout
    worktree: Path

    def snapshots(self) -> Git:
        """Return git on the store, with the worktree as its work tree."""
        return Git(
            arguments=[
                "--git-dir",
                str(self.layout.snapshots),
                "--work-tree",
                str(self.worktree),
            ],
            cwd=self.worktree,
        )

    def repository(self) -> Git:
        """Return git on the worktree's own repository."""
        return Git(cwd=self.worktree)

    def ensure(self) -> None:
        """Create the store where there's none, and keep its exclusions current.

        The store excludes `.lup/` and whatever the worktree's repository excludes
        outside `.gitignore` (its `info/exclude`).
        """
        if not self.layout.snapshots.is_dir():
            self.layout.home.mkdir(parents=True, exist_ok=True)
            Git(cwd=self.layout.home).run(
                "init", "--quiet", "--bare", str(self.layout.snapshots)
            )
        own = self.repository().text(
            "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
        )
        theirs = Path(own).read_text() if Path(own).is_file() else ""
        exclude = self.layout.snapshots / "info" / "exclude"
        wanted = f"/{CheckoutLayout(root=Path()).home}/\n{theirs}"
        if not exclude.is_file() or exclude.read_text() != wanted:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(wanted)

    def snapshot(self) -> str:
        """Write the worktree into the store as a tree, and return its id."""
        self.ensure()
        store = self.snapshots()
        store.run("add", "--all")
        return store.text("write-tree")

    def ref(self, name: str) -> str | None:
        """Return the tree a store ref names, or none where it isn't set.

        A store not created yet has no refs.
        """
        if not self.layout.snapshots.is_dir():
            return None
        found = self.snapshots().run(
            "rev-parse", "--verify", "--quiet", name, ok=[0, 1]
        )
        return found.stdout.decode().strip() if found.exit_code == 0 else None

    def accepted(self) -> str | None:
        """Return the last tree lup accepted, or none before the first."""
        return self.ref("refs/lup/accepted")

    def accept(self, tree: str) -> None:
        """Make `tree` the accepted tree."""
        self.snapshots().run("update-ref", "refs/lup/accepted", tree)

    def started(self, session: str) -> str | None:
        """Return the tree `session` started from, or none if it isn't recorded."""
        return self.ref(f"refs/lup/sessions/{session}")

    def start(self, session: str, tree: str) -> None:
        """Record `tree` as the tree `session` started from."""
        self.snapshots().run("update-ref", f"refs/lup/sessions/{session}", tree)

    def changed(self, old: str, new: str) -> list[Changed]:
        """List the paths that differ from tree `old` to tree `new`."""

        def filtered(kind: Literal["added", "modified", "deleted"]) -> list[Changed]:
            letters = {"added": "A", "modified": "MT", "deleted": "D"}
            listed = self.snapshots().run(
                "diff-tree",
                "-r",
                "-z",
                "--no-renames",
                "--name-only",
                f"--diff-filter={letters[kind]}",
                old,
                new,
            )
            return [
                Changed(path=Path(path), kind=kind)
                for path in nul_separated(listed.stdout)
            ]

        return sorted(
            [*filtered("added"), *filtered("modified"), *filtered("deleted")],
            key=lambda change: change.path,
        )

    def content(self, tree: str | None, path: Path) -> bytes | None:
        """Return `path`'s content in `tree`, or none where it isn't there."""
        if tree is None:
            return None
        found = self.snapshots().run("cat-file", "blob", f"{tree}:{path}", ok=[0, 128])
        return found.stdout if found.exit_code == 0 else None

    def blob(self, tree: str, path: Path) -> str | None:
        """Return the object id of `path` in `tree`, or none where it isn't there."""
        return self.ref(f"{tree}:{path}")

    def keep(self, content: bytes) -> str:
        """Store `content` as an object, and return its id."""
        self.ensure()
        stored = self.snapshots().run("hash-object", "-w", "--stdin", stdin=content)
        return stored.stdout.decode().strip()

    def object(self, blob: str) -> bytes | None:
        """Return the content of stored object `blob`, or none if it isn't stored."""
        found = self.snapshots().run("cat-file", "blob", blob, ok=[0, 128])
        return found.stdout if found.exit_code == 0 else None

    def unstage(self, tree: str, paths: list[Path], entries: list[Entry]) -> str:
        """Put paths back in the private index, and write it as a tree.

        The index holds the latest snapshot, so the tree written is that snapshot
        with `paths` as they were in `tree`, and each of `entries` as a commit has
        it.
        """
        store = self.snapshots()
        if paths:
            store.run("reset", "--quiet", tree, "--", *(str(path) for path in paths))
        for entry in entries:
            if entry.blob is None:
                store.run("update-index", "--force-remove", "--", str(entry.path))
                continue
            store.run(
                "update-index",
                "--add",
                "--cacheinfo",
                entry.mode,
                entry.blob,
                str(entry.path),
            )
        return store.text("write-tree")

    def restore(self, tree: str, paths: list[Path]) -> None:
        """Put `paths` back on disk as `tree` has them, removing those it lacks."""
        present = [path for path in paths if self.blob(tree, path) is not None]
        if present:
            self.snapshots().run(
                "checkout", tree, "--", *(str(path) for path in present)
            )
        for path in paths:
            if path not in present:
                (self.worktree / path).unlink(missing_ok=True)

    def save(self, number: int, path: Path, content: bytes) -> Path:
        """Save the agent's version of `path` under refusal `number`; return where."""
        saved = CheckoutLayout(root=self.worktree).saved_copy(number, path)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(content)
        return saved

    def head(self) -> str | None:
        """Return the commit the worktree's `HEAD` names, or none before its first."""
        found = self.repository().run(
            "rev-parse", "--verify", "--quiet", "HEAD", ok=[0, 1]
        )
        return found.stdout.decode().strip() if found.exit_code == 0 else None

    def tips(self, head: str | None) -> list[str]:
        """List every commit the worktree's repository names: its refs, and `head`.

        `head` is the commit the worktree's `HEAD` names, as `head()` read it.
        """
        refs = self.repository().text("for-each-ref", "--format=%(objectname)")
        return list(dict.fromkeys([*refs.splitlines(), *([head] if head else [])]))

    def moved(self, before: str | None, after: str | None) -> list[Path]:
        """List the paths that differ between two commits; none is no commit at all."""
        repository = self.repository()
        empty = repository.run("hash-object", "-t", "tree", "--stdin", stdin=b"")
        nothing = empty.stdout.decode().strip()
        listed = repository.run(
            "diff-tree",
            "-r",
            "-z",
            "--no-renames",
            "--name-only",
            before or nothing,
            after or nothing,
        )
        return [Path(path) for path in nul_separated(listed.stdout)]

    def entry(self, commit: str | None, path: Path) -> Entry:
        """Return `path` as `commit` has it, its content copied into the store."""
        if commit is None:
            return Entry(path=path)
        repository = self.repository()
        found = repository.run("cat-file", "blob", f"{commit}:{path}", ok=[0, 128])
        if found.exit_code != 0:
            return Entry(path=path)
        mode = repository.text(
            "ls-tree", "--format=%(objectmode)", commit, "--", str(path)
        )
        return Entry(path=path, mode=mode, blob=self.keep(found.stdout))

    def merges(self, commits: list[str]) -> list[Merge]:
        """Remake git's merges of two commits from the history of `commits`.

        The merges `HEAD` reached that `commits` don't, and a merge in progress
        (`MERGE_HEAD`), each remade only where both its parents are in the history
        of `commits`: content judged on each side. Remaking one writes its objects
        into the repository, as git's own merge does, and runs the merge drivers
        the repository configures, as `git merge` would.
        """
        head = self.head()
        if head is None or not commits:
            return []
        repository = self.repository()
        reached = repository.text("rev-list", "--merges", head, "--not", *commits)
        made = [
            repository.text("rev-parse", f"{merge}^@").splitlines()
            for merge in reached.splitlines()
        ]
        progress = repository.run(
            "rev-parse", "--verify", "--quiet", "MERGE_HEAD", ok=[0, 1]
        )
        merging = (
            [[head, progress.stdout.decode().strip()]]
            if progress.exit_code == 0
            else []
        )

        def judged(parents: list[str]) -> bool:
            if len(parents) != 2:
                return False
            beyond = repository.text(
                "rev-list", "--max-count=1", *parents, "--not", *commits
            )
            return not beyond

        def remade(parents: list[str]) -> Merge:
            ours, theirs = parents
            merged = repository.run(
                "merge-tree",
                "--write-tree",
                "--name-only",
                "--no-messages",
                "-z",
                ours,
                theirs,
                ok=[0, 1],
            )
            tree, *conflicted = nul_separated(merged.stdout)
            return Merge(tree=tree, conflicted=[Path(path) for path in conflicted])

        return [remade(parents) for parents in [*made, *merging] if judged(parents)]

    def merged(self, path: Path, blob: str | None, merge: Merge) -> bool:
        """Say whether `path` as object `blob` is what `merge` makes of it.

        For a deletion (`blob` none): whether the merge lacks the path.
        """
        if path in merge.conflicted:
            return False
        found = self.repository().run(
            "rev-parse", "--verify", "--quiet", f"{merge.tree}:{path}", ok=[0, 1, 128]
        )
        if found.exit_code != 0:
            return blob is None
        return found.stdout.decode().strip() == blob

    def remote_tips(self) -> list[str]:
        """List the commits the worktree's remote-tracking refs name."""
        listed = self.repository().text(
            "for-each-ref", "--format=%(objectname)", "refs/remotes"
        )
        return listed.splitlines()

    def committed(self, path: Path, blob: str | None, tips: list[str]) -> bool:
        """Say whether `path` as object `blob` is in a commit reachable from `tips`.

        For a deletion (`blob` none): whether `HEAD` lacks the path and was
        reachable from `tips`, as after switching to a branch without the file.
        """
        if not tips:
            return False
        repository = self.repository()
        if blob is None:
            if self.head() is None:
                return False
            newer = repository.text("rev-list", "--max-count=1", "HEAD", "--not", *tips)
            lacks = repository.run(
                "cat-file", "-e", f"HEAD:{path}", ok=[0, 128]
            ).exit_code
            return not newer and lacks != 0
        found = repository.text(
            "log",
            "--format=%H",
            "--max-count=1",
            f"--find-object={blob}",
            *tips,
            "--",
            str(path),
        )
        return bool(found)

    def state(self) -> WorktreeState:
        """Read what the store remembers about the worktree."""
        return read_model(self.layout.state, WorktreeState) or WorktreeState()

    def remember(self, state: WorktreeState) -> None:
        """Store what to remember about the worktree."""
        write_model(self.layout.state, state)


class Elsewhere(Model):
    """Content judged before this checkpoint: commits, and git's merges of them.

    A file whose content is in the history of these commits at its path, or
    which git's clean merge of two of them makes, isn't judged again: it was
    judged where it was written (`docs/judging-writes.md`, *After a call: the
    checkpoint*, step 3).
    """

    store: Store
    commits: list[str]
    """The commits the repository's refs and the worktree's `HEAD` named at its last
    checkpoint, the `HEAD` each other worktree had at its own, and the
    remote-tracking refs as they stand."""

    def holds(self, path: Path, blob: str | None) -> bool:
        """Say whether `path` as object `blob` was judged elsewhere; none, deleted."""
        if self.store.committed(path, blob, self.commits):
            return True
        return any(self.store.merged(path, blob, merge) for merge in self.merges)

    @cached_property
    def merges(self) -> list[Merge]:
        """The merges git makes from these commits, remade once, when first asked."""
        return self.store.merges(self.commits)
