"""Which tools a session called."""


def tools(calls: list[str]) -> set[str]:
    """Return the tools named in `calls`."""
    return set(calls)
