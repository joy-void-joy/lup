"""Read a version number."""

import re


def major(version: str) -> int:
    """Return the major part of a version number."""
    found = re.match("[0-9]+", version)
    return int(found.group()) if found else 0
