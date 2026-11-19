"""Fetching what a runtime's vendor publishes: its newest version, a release's description, a CLI's files."""

import urllib.request
lazy from datetime import timedelta


def got(url: str, within: timedelta) -> bytes:
    """Return what `url` answers, its redirects followed, a fetch past `within` refused.

    Raise `OSError` where it can't be fetched, `urllib.error.URLError` among it.
    """
    # lup: ignore("S310", why="each URL is a runtime channel's own, built from its https base, never a caller's")
    with urllib.request.urlopen(url, timeout=within.total_seconds()) as answered:
        return answered.read()
