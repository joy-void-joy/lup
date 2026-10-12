"""The root of every error `lup` raises, so a caller can catch them all at once."""


class LupError(Exception):
    """Something `lup` couldn't do; each area's errors descend from it."""
