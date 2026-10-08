"""Which tools a session called."""

from collections import Counter


def tools(calls: list[str]) -> Counter[str]:
    """Count the calls to each tool named in `calls`."""
    return Counter(calls)
