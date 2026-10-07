"""The root of the errors `lup_dev` raises."""


class LupDevError(Exception):
    """The root of every error `lup_dev` raises, so one clause catches them all.

    >>> try:
    ...     raise LupDevError("the gate failed")
    ... except LupDevError as error:
    ...     print(error)
    the gate failed
    """
