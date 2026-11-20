"""The root of the code rules' errors."""

from lup import LupError


class LupCodeRulesError(LupError):
    """Something the code rules couldn't do: build their engine, run it, or read what it answered."""
