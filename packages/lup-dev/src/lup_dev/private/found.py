"""Finding the values never published in a text: each literally, ignoring case, never inside a longer word.

`docs/private.md`, *Matching*. A value is a string, never a pattern:
- **ignoring case:** both sides are case-folded (`str.casefold`), so `Op`
  starting a sentence is `op`; a place is counted in the text as written, even
  where folding changes a character's length (`ß` folds to `ss`);
- **whole words:** where a value begins or ends with a letter or digit, the
  character beside it on that side isn't one, so a user name `op` is found in
  `op@host` and in `-home-op-src-`, not in `operator` or `loop`, and a home
  `/home/op` in `/home/op/x`, not in `/home/opal`;
- **the longest of overlapping matches:** `/home/op/src/demo.git/x` is the
  repository's path, not the home's as well;
- **what isn't text** (not UTF-8, or holding a NUL) is read as bytes, ignoring
  ASCII case, each value's occurrences counted.

A value escaped, encoded or split across lines isn't found.
"""

from bisect import bisect_right
from difflib import SequenceMatcher
from functools import reduce
from itertools import accumulate
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.private.withheld import Held, Withheld

if TYPE_CHECKING:
    from collections.abc import Iterator


class Found(Model):
    """One value found in a text, and where."""

    held: Held
    line: int
    """Counted from 1, as Python's `splitlines` counts lines."""
    column: int
    """Counted from 1, in characters of the text as written."""
    end: int
    """The column just past its last character."""


class Span(Model):
    """One match in a text, by its offsets in characters, before lines are counted."""

    held: Held
    start: int
    end: int

    def meets(self, other: Span) -> bool:
        """Say whether it overlaps `other`."""
        return self.start < other.end and other.start < self.end


class Folded(Model):
    """A text case-folded, and where each folded character came from where folding changed a length."""

    text: str
    origin: list[int] | None = None
    """The offset in the text as written of each folded character; none where
    every character folded to one."""

    @classmethod
    def of(cls, text: str) -> Folded:
        """Fold `text`.

        >>> Folded.of("Op"), Folded.of("Straße").origin
        (Folded(text='op', origin=None), [0, 1, 2, 3, 4, 4, 5])
        """
        lowered = text.casefold()
        if len(lowered) == len(text):
            return cls(text=lowered)
        origin = [at for at, char in enumerate(text) for _ in char.casefold()]
        return cls(text=lowered, origin=origin)

    def span(self, held: Held, start: int, end: int) -> Span:
        """Return the match at `start` to `end` in the folded text as a span of the text as written."""
        if self.origin is None:
            return Span(held=held, start=start, end=end)
        return Span(held=held, start=self.origin[start], end=self.origin[end - 1] + 1)


def textual(content: bytes) -> str | None:
    r"""Return `content` as text where it's UTF-8 holding no NUL; none where it's binary.

    >>> textual(b"a\nb"), textual(b"\x00a"), textual(b"\xff")
    ('a\nb', None, None)
    """
    if b"\0" in content:
        return None
    try:
        return content.decode()
    except UnicodeDecodeError:
        return None


def starts[T: (str, bytes)](hay: T, value: T) -> Iterator[int]:
    """Yield each offset `value` starts at in `hay`, overlapping ones too."""
    start = hay.find(value)
    while start != -1:
        yield start
        start = hay.find(value, start + 1)


def bounded(hay: str, start: int, end: int) -> bool:
    """Say whether what's found at `start` to `end` in `hay` isn't part of a longer word.

    >>> bounded("loop", 2, 4), bounded("an op.", 3, 5), bounded("a/b", 1, 2)
    (False, True, True)
    """
    opens = hay[start].isalnum() and start > 0 and hay[start - 1].isalnum()
    closes = hay[end - 1].isalnum() and end < len(hay) and hay[end].isalnum()
    return not (opens or closes)


def spans(text: str, withheld: Withheld) -> list[Span]:
    """Return every value of `withheld` in `text`, the longest of overlapping ones, in the order they come."""
    hay = Folded.of(text)
    every = [
        hay.span(held, start, start + len(value))
        for held in withheld.held
        for value in [held.text.casefold()]
        for start in starts(hay.text, value)
        if bounded(hay.text, start, start + len(value))
    ]
    longest = sorted(every, key=lambda span: (span.start - span.end, span.start))

    def kept(chosen: list[Span], span: Span) -> list[Span]:
        if any(span.meets(other) for other in chosen):
            return chosen
        return [*chosen, span]

    return sorted(reduce(kept, longest, []), key=lambda span: span.start)


def found(text: str, withheld: Withheld) -> list[Found]:
    r"""Return every value of `withheld` in `text`, each placed on its line and column.

    >>> held = Withheld(held=[Held(kind="user", text="op")])
    >>> [(each.line, each.column) for each in found("Hi\nOP's loop, op@box", held)]
    [(2, 1), (2, 12)]
    """
    beginnings = [0, *accumulate(len(line) for line in text.splitlines(keepends=True))]

    def at(span: Span) -> Found:
        index = bisect_right(beginnings, span.start) - 1
        begins = beginnings[index]
        return Found(
            held=span.held,
            line=index + 1,
            column=span.start - begins + 1,
            end=span.end - begins + 1,
        )

    return [at(span) for span in spans(text, withheld)]


def masked(text: str, withheld: Withheld) -> str:
    """Return `text` with each character of a value of `withheld` in it shown as `•`, for naming a place by it, such as a file's path.

    >>> masked("docs/Kestrel-notes.md", Withheld(held=[Held(kind="value", text="kestrel")]))
    'docs/•••••••-notes.md'
    """
    found = spans(text, withheld)
    return "".join(
        "•" if any(span.start <= at < span.end for span in found) else char
        for at, char in enumerate(text)
    )


def worded(byte: int) -> bool:
    """Say whether a byte is an ASCII letter or digit.

    >>> worded(ord("a")), worded(ord("/")), worded(0xC3)
    (True, False, False)
    """
    return chr(byte).isascii() and chr(byte).isalnum()


def counted(content: bytes, held: Held) -> list[int]:
    r"""Return where `held`'s value is in `content`, read as bytes ignoring ASCII case, each offset from 0.

    >>> counted(b"\x00HOME/OP/x op2", Held(kind="user", text="op"))
    [6]
    """
    hay = content.lower()
    value = held.text.encode().lower()

    def alone(start: int) -> bool:
        end = start + len(value)
        opens = worded(value[0]) and start > 0 and worded(hay[start - 1])
        closes = worded(value[-1]) and end < len(hay) and worded(hay[end])
        return not (opens or closes)

    return [start for start in starts(hay, value) if alone(start)]


def added_lines(before: str | None, after: str) -> list[int]:
    r"""List the lines of `after` a change from `before` adds or rewrites, counted from 1: every line where there was no file.

    A line only removed adds nothing, so unlike the judge's touched lines no
    line beside a deletion counts.

    >>> added_lines("a\nb\nc\n", "a\nB\nd\n"), added_lines("a\nb\n", "a\n")
    ([2, 3], [])
    """
    lines = after.splitlines()
    if before is None:
        return list(range(1, len(lines) + 1))
    matcher = SequenceMatcher(a=before.splitlines(), b=lines, autojunk=False)
    return [
        line + 1
        for tag, _, _, start, end in matcher.get_opcodes()
        if tag in ["replace", "insert"]
        for line in range(start, end)
    ]
