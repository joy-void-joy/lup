"""Handing an approved launch to the project, from a copy of exactly what was approved.

Once the host zone is approved, the project's own launch runs: its
environment is synced, its package imported, its trees generated, its
container started. It does not run from the checkout. The approved tree is
materialized from the launcher's store into a directory under its own state,
and the launch is started with that directory as its project, its working
directory still the checkout it writes into and mounts.

That is what makes the approval mean something after the moment it is given.
Run from the checkout, the launch would read each file a second time, after
the check -- a session writing between the two would be approved and replaced
in the same breath -- and it would read what the check never looked at: an
untracked module beside the package, a ``sitecustomize`` on its path, a
``__pycache__`` whose bytecode no longer matches its source. From the export
none of those exist, because nothing but the approved tree was put there.

The rest of what the launch reads is pointed away from the checkout for the
same reason. Its Python environment is one the launcher keeps per worktree,
because the checkout's own ``.venv`` is writable from inside the container,
and a ``.pth`` file planted there runs in every interpreter started from it.
Its bytecode cache is the launcher's. Its registries -- the project's
``sync.json`` and the machine's ``sync.json.local`` -- are read from the
export (:mod:`lup.trust.approved`), since both decide the next session's
boundary and the live files are exactly what a session could rewrite.
"""

import hashlib
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from uuid import uuid4

import sh
from pydantic import BaseModel

from lup.devtools.launcher import CONSOLE_SCRIPT
from lup.sandbox.process import running_environments
from lup.trust.approved import APPROVED_TREE_ENV
from lup.trust.objects import ObjectStore
from lup.trust.record import ExportLease, TrustState
from lup.trust.zone import snapshot
from lup.types import EnvVars

# lup: ignore[constant-declaration] — the name of the marker a materialization
# writes last, which every later launch reads to know it may reuse the export
EXPORT_MARKER = ".lup-export"
"""The file an export holds once it is complete, naming the tree it is."""


class Export(BaseModel, frozen=True):
    """One approved tree on disk, and the links it declined to create."""

    path: Path
    withheld: list[str] = []
    """Symbolic links whose target lies outside the export.

    Created, such a link would reach past the approved tree into whatever it
    names -- a free zone of the live checkout, which a session writes -- and
    the launch would run that instead. Withheld, a launch that needed one
    fails naming the path, which is the honest outcome.
    """


class Handoff(BaseModel, frozen=True):
    """How the project's own launch is started once its tree is approved."""

    argv: list[str]
    environment: EnvVars


def escapes(link: PurePosixPath, target: str) -> bool:
    """Whether a link at ``link`` pointing at ``target`` resolves outside the tree."""
    if PurePosixPath(target).is_absolute():
        return True
    resolved = [*link.parent.parts]
    for part in PurePosixPath(target).parts:
        match part:
            case "..":
                if not resolved:
                    return True
                resolved.pop()
            case ".":
                continue
            case _:
                resolved.append(part)
    return False


def materialized(store: ObjectStore, tree: str, destination: Path) -> Export:
    """The approved tree on disk at ``destination``, written once and reused.

    Written into a sibling directory and renamed into place with the marker
    already inside, so a launch interrupted halfway leaves a directory no later
    launch mistakes for complete. A directory without the marker is removed
    and written again: the store is the source of truth, not the copy.
    """
    marker = destination / EXPORT_MARKER
    if marker.is_file() and marker.read_text(encoding="ascii") == tree:
        return Export(path=destination)
    if destination.exists():
        shutil.rmtree(destination)
    staging = destination.with_name(f"{destination.name}.{uuid4().hex}.partial")
    withheld = [
        entry.path.as_posix()
        for entry in snapshot(store, tree).entries
        if not written(store, staging, entry.path, entry.mode, entry.oid)
    ]
    (staging / EXPORT_MARKER).write_text(tree, encoding="ascii")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        staging.replace(destination)
    except OSError:
        # A second launch of the same tree finished first: its copy is the
        # same bytes, so keep it and drop this one.
        if not (marker.is_file() and marker.read_text(encoding="ascii") == tree):
            raise
        shutil.rmtree(staging)
    return Export(path=destination, withheld=withheld)


def exported(
    state: TrustState, store: ObjectStore, tree: str, holder: int | None = None
) -> Export:
    """One approved tree on disk for a process to run from, and no export nothing uses.

    Under the record's lock, so a launch pruning never removes an export
    another launch is between materializing and leasing. The lease is taken
    for ``holder`` (this process, unset) before anything runs from the
    export, and every export the record does not keep is removed: each
    worktree's latest, and every one a running process leases, stay.
    """
    lease = ExportLease.of(tree, holder if holder is not None else os.getpid())
    with state.locked():
        record = state.read().leased(lease)
        state.write(record)
        export = materialized(store, tree, state.export(tree))
        pruned(state, [tree, *record.exports_kept(), *run_from(state)])
    return export


def run_from(state: TrustState) -> list[str]:
    """Every export a process still runs from, as its environment names it.

    Everything a launch starts inherits the export it was handed off from:
    the session, its tool servers, and a companion the launch started beside
    it, which may outlive the launch and hold no lease of its own.
    """
    exports = state.root / "exports"
    return [
        Path(environment[APPROVED_TREE_ENV]).name
        for environment in running_environments()
        if APPROVED_TREE_ENV in environment
        and Path(environment[APPROVED_TREE_ENV]).parent == exports
    ]


def released(state: TrustState, tree: str, holder: int | None = None) -> None:
    """Let go of an export a process ran from and no longer does."""
    lease = ExportLease.of(tree, holder if holder is not None else os.getpid())
    with state.locked():
        state.write(state.read().released(lease))


def pruned(state: TrustState, kept: list[str]) -> list[Path]:
    """Remove every export not ``kept``, with the bytecode compiled from it.

    A partial export an interrupted launch left behind goes too: exports are
    only written under the record's lock, so none is being written now.
    """
    exports = state.root / "exports"
    if not exports.is_dir():
        return []
    removed = [
        directory
        for directory in sorted(exports.iterdir())
        if directory.name not in kept
    ]
    for directory in removed:
        shutil.rmtree(directory)
        compiled = state.pycache() / directory.relative_to(directory.anchor)
        if compiled.is_dir():
            shutil.rmtree(compiled)
    return removed


def written(
    store: ObjectStore, staging: Path, path: PurePosixPath, mode: str, oid: str
) -> bool:
    """Write one entry into the export, answering whether it was written.

    A submodule is left out: its content is another repository's, and the
    commit the zone records is not a directory anything could be run from.
    """
    target = staging / path
    target.parent.mkdir(parents=True, exist_ok=True)
    match mode:
        case "160000":
            return True
        case "120000":
            pointed = os.fsdecode(store.read(oid, "blob"))
            if escapes(path, pointed):
                return False
            target.symlink_to(pointed)
            return True
        case _:
            target.write_bytes(store.read(oid, "blob"))
            target.chmod(0o755 if mode == "100755" else 0o644)
            return True


def worktree_digest(worktree: Path) -> str:
    """The name one worktree's launch environment is kept under."""
    return (
        f"{worktree.name}-{hashlib.sha256(str(worktree).encode('utf-8')).hexdigest()}"
    )


def handoff(
    state: TrustState,
    export: Path,
    worktree: Path,
    command: list[str],
    inherited: EnvVars,
    script: str = CONSOLE_SCRIPT,
) -> Handoff:
    """The ``uv run`` that starts the project's own ``command`` from the export.

    ``--frozen`` installs exactly the lockfile the operator approved, with
    nothing resolved afresh. ``--directory`` keeps the checkout the working
    directory, which is where the launch writes its trees and what it mounts;
    ``--project`` makes the export the project whose code runs.
    """
    environment = {
        **{name: value for name, value in inherited.items() if name != "VIRTUAL_ENV"},
        "UV_PROJECT_ENVIRONMENT": str(state.environment(worktree_digest(worktree))),
        "PYTHONPYCACHEPREFIX": str(state.pycache()),
        APPROVED_TREE_ENV: str(export),
    }
    return Handoff(
        argv=[
            "uv",
            "run",
            "--directory",
            str(worktree),
            "--project",
            str(export),
            "--frozen",
            script,
            *command,
        ],
        environment=environment,
    )


def ran(handoff: Handoff) -> bool:
    """Run one hand-off to completion in the foreground, answering whether it succeeded."""
    try:
        sh.Command(handoff.argv[0])(
            *handoff.argv[1:], _env=handoff.environment, _fg=True
        )
    except sh.ErrorReturnCode:
        return False
    return True


def executed(handoff: Handoff) -> None:
    """Replace this process with the hand-off, keeping the terminal.

    Replaced rather than waited on, so the launch is the process the terminal
    and its signals belong to, and its exit status is the launcher's. What the
    launcher said is flushed first: a replaced process never writes out what
    it buffered, and a pipe buffers.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    # lup: ignore[os-shell] — the hand-off must become the process the operator's
    # terminal belongs to; `sh` starts a child and cannot replace its caller
    os.execvpe(handoff.argv[0], handoff.argv, handoff.environment)


def beside(handoff: Handoff) -> sh.RunningCommand:
    """Start one hand-off as a child on this terminal, for a launcher that stays.

    What stays is the review's inbox, to send its tab to the page the command
    opens; the command still owns the terminal, its input and its output.
    Every exit status is the command's to report, so none is raised here.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    return sh.Command(handoff.argv[0])(
        *handoff.argv[1:],
        _env=handoff.environment,
        _bg=True,
        _bg_exc=False,
        _in=sys.stdin,
        _out=sys.stdout,
        _err=sys.stderr,
        _ok_code=list(range(256)),
        _return_cmd=True,
    )


def exit_status(running: sh.RunningCommand) -> int:
    """How a command started :func:`beside` this launcher ended, as a shell says it."""
    try:
        return running.wait().exit_code
    except sh.SignalException as error:
        return 128 + abs(error.exit_code)


type Spawner = Callable[[Handoff], sh.RunningCommand]
"""What starts a hand-off beside the launcher; replaced in tests."""

type Executor = Callable[[Handoff], None]
"""What starts the project's launch once it is approved; replaced in tests."""

type Runner = Callable[[Handoff], bool]
"""What runs a hand-off to completion; replaced in tests."""
