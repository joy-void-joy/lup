"""Where a function is defined."""


def location(name: str) -> tuple[str, int]:
    """Return the file and line that define `name`."""
    return name, 1
