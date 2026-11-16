"""`raises`: a promise saying that something fails, and how.

A module's promises are imported with its declaration, so they can't import a
test runner; this is what they say a failure with.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from lup.types import MutableModel

if TYPE_CHECKING:
    from collections.abc import Generator


class Raised[E: BaseException](MutableModel, arbitrary_types_allowed=True):
    """What a block expected to fail raised, once it has."""

    error: E | None = None

    def raised(self) -> E:
        """Return what the block raised.

        Raise `AssertionError` where it raised nothing yet, as inside the block.
        """
        if self.error is None:
            message = "the block hasn't raised: read what it raised after it"
            raise AssertionError(message)
        return self.error


@contextmanager
def raises[E: BaseException](kind: type[E]) -> Generator[Raised[E]]:
    """Fail unless the block raises `kind`, and hold what it raised, to read after it.

    Anything else it raises goes up as raised.

    >>> with raises(KeyError) as missing:
    ...     {}["key"]
    >>> type(missing.raised()).__name__
    'KeyError'
    """
    held = Raised[E]()
    try:
        yield held
    except kind as error:
        held.error = error
        return
    message = f"the block raised no `{kind.__name__}`"
    raise AssertionError(message)
