"""The root of the code rules' errors."""

from lup import LupError


class CodeRulesError(LupError):
    """Something the code rules couldn't do: build their engine, run it, or read what it answered."""
