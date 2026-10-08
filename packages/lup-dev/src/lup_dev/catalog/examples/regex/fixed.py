"""Read a version number."""

from packaging.version import Version


def major(version: str) -> int:
    """Return the major part of a version number."""
    return Version(version).major
