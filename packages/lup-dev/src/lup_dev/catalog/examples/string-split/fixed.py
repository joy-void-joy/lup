"""Read a URL's host."""

from urllib.parse import urlsplit


def host(url: str) -> str:
    """Return the host `url` names, or nothing when it names none."""
    return urlsplit(url).hostname or ""
