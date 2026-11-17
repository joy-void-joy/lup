"""What the store raises: a record it can't keep, or one it holds that doesn't read."""

from lup.errors import LupError


class StoreError(LupError):
    """The store can't do what it was asked: a version not after the last, a name another node holds, a kind refusing what it was given, or a record it holds that its class can't read."""
