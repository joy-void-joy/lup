"""The root of the errors `lup_transcripts` raises."""

from lup.errors import LupError


class LupTranscriptsError(LupError):
    """The root of every error `lup_transcripts` raises, so one clause catches them all.

    It descends from `lup`'s own, so a caller catching what `lup` raises catches it too.

    >>> try:
    ...     raise LupTranscriptsError("no kept session is `zz`")
    ... except LupError as error:
    ...     print(error)
    no kept session is `zz`
    """
