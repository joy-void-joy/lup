"""Read a branch's name."""


def branch(ref: str) -> str:
    """Return the branch a git ref names."""
    return ref[len("refs/heads/") :]
