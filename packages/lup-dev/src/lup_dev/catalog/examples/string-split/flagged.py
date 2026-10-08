"""Read a URL's host."""


def host(url: str) -> str:
    """Return the host `url` names."""
    return url.split("/")[2]
