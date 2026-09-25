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
from lup.trust.approved import APPROVED_TREE_ENV
from lup.trust.objects import ObjectStore
from lup.trust.record import TrustState
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


type Executor = Callable[[Handoff], None]
"""What starts the project's launch once it is approved; replaced in tests."""

type Runner = Callable[[Handoff], bool]
"""What runs a hand-off to completion; replaced in tests."""
