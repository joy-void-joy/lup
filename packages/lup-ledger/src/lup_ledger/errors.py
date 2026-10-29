"""The root of the errors `lup_ledger` raises."""

from lup.errors import LupError


class LupLedgerError(LupError):
    """The root of every error `lup_ledger` raises: a record the store refuses, or one it can't read.

    It descends from `lup`'s own, so a caller catching what `lup` raises catches it too.

    >>> try:
    ...     raise LupLedgerError("the ledger holds no @12")
    ... except LupError as error:
    ...     print(error)
    the ledger holds no @12
    """
