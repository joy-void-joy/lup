"""Session commit operations: stage and commit per-session result files.

Backs ``lup-devtools feedback commit`` — one ``data(sessions):`` commit per
session, matched against the *configured* trace root so a relocated
``AGENT_NOTES_PATH`` keeps working.
"""

import logging
from pathlib import Path

import sh
import typer

from lup.workspace.history import get_latest_session_json, iter_session_dirs
from lup.workspace.paths import project_root, traces_path
from lup_template.devtools.utils import git

logger = logging.getLogger(__name__)


def get_uncommitted_session_ids() -> set[str]:
    """Find session IDs with uncommitted result files.

    Paths are matched against the *configured* trace root (``lup.workspace.paths``),
    so a relocated ``AGENT_NOTES_PATH`` keeps ``feedback commit`` working.
    The layout below the root is ``<version>/(sessions|logs)/<session_id>/``.
    Uses ``-z`` so paths with spaces or quoting never shear.
    """
    try:
        traces_rel = traces_path().relative_to(project_root())
    except ValueError:
        # Trace root configured outside the repo — nothing for git to commit
        return set()

    status = str(git.status("--porcelain", "-z", "--", str(traces_rel), _ok_code=[0]))
    return session_ids_from_status(status, traces_rel)


def session_ids_from_status(status: str, traces_rel: Path) -> set[str]:
    """Parse ``git status --porcelain -z`` output into session IDs.

    Only paths under ``traces_rel`` with the versioned layout
    (``<version>/(sessions|logs)/<session_id>/...``) count; rename/copy
    entries contribute their target path and their source is discarded.
    """
    session_ids: set[str] = set()
    chunks = iter(status.split("\0"))  # lup: ignore — NUL is porcelain -z framing
    for chunk in chunks:
        if len(chunk) < 4:
            continue
        code, file_path = chunk[:2], chunk[3:]
        if code.startswith(("R", "C")):
            next(chunks, None)  # discard the rename/copy source path
        relative = Path(file_path)
        if not relative.is_relative_to(traces_rel):
            continue
        match relative.relative_to(traces_rel).parts:
            case (_, "sessions" | "logs", session_id, *_):
                session_ids.add(session_id)

    return session_ids


def get_session_summary(session_id: str) -> str:
    """Read summary from the latest session JSON across all versions."""
    data = get_latest_session_json(session_id)
    if data is None:
        return f"session {session_id}"
    output = data.get("output", {})
    if isinstance(output, dict):
        summary = output.get("summary")
        if isinstance(summary, str):
            return summary[:50]
    return f"session {session_id}"


def commit_session(session_id: str, *, dry_run: bool = False) -> bool:
    """Stage and commit files for a single session ID."""
    paths: list[str] = []

    for session_dir in iter_session_dirs(session_id=session_id):
        paths.append(str(session_dir))

    if traces_path().exists():
        for ver_dir in traces_path().iterdir():
            if not ver_dir.is_dir():
                continue
            log_dir = ver_dir / "logs" / session_id
            if log_dir.exists():
                paths.append(str(log_dir))

    if not paths:
        return False

    if dry_run:
        summary = get_session_summary(session_id)
        typer.echo(f"  Would commit {session_id}: {summary}")
        for p in paths:
            typer.echo(f"    {p}")
        return True

    for path in paths:
        try:
            git.add(path)
        except sh.ErrorReturnCode as e:
            logger.warning("Failed to stage %s: %s", path, e)

    diff = str(git.diff("--cached", "--stat", _ok_code=[0, 1])).strip()
    if not diff:
        return False

    summary = get_session_summary(session_id)
    slug = summary[:50].strip().rstrip(".")
    git.commit("-m", f"data(sessions): {slug}")
    typer.echo(f"  Committed {session_id}: {slug}")
    return True
