"""Git checkpoint for retained conversation deliveries."""

import logging
from pathlib import Path

import sh
import typer

from lup.devtools.utils import decode_stderr, git

logger = logging.getLogger(__name__)


def checkpoint_delivery(root: Path, destination: Path, *, provider: str) -> str | None:
    """Commit one retained input only when Git does not ignore its destination."""
    try:
        relative = destination.resolve().relative_to(root.resolve())
    except ValueError:
        typer.echo("Retained destination is outside the repository; not committed.")
        return None
    try:
        ignored = git.out(
            "check-ignore",
            "--",
            str(relative),
            _cwd=str(root),
            _ok_code=[0, 1],
        )
        if ignored:
            typer.echo("Retained destination is gitignored; not committed.")
            return None
        git.add("-A", "--", str(relative), _cwd=str(root))
        staged = git.out(
            "diff",
            "--cached",
            "--name-only",
            "--",
            str(relative),
            _cwd=str(root),
            _ok_code=[0, 1],
        )
        if not staged:
            return None
        git.commit(
            "-m",
            f"data(conversations): retain {provider}",
            "--",
            str(relative),
            _cwd=str(root),
        )
        revision = git.out("rev-parse", "--short", "HEAD", _cwd=str(root))
    except sh.ErrorReturnCode as error:
        logger.exception("Could not checkpoint retained conversation data")
        raise typer.BadParameter(
            f"Could not checkpoint retained conversation data: {decode_stderr(error)}"
        ) from error
    typer.echo(f"Committed {provider} conversation checkpoint: {revision}")
    return revision
