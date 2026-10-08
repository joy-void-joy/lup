"""Read a branch's name."""

from pathlib import PurePosixPath


def branch(ref: str) -> str:
    """Return the branch a git ref names."""
    return PurePosixPath(ref).relative_to("refs/heads").as_posix()
