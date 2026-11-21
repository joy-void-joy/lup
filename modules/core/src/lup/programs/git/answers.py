"""How git's answers are read: one line, fields each ended by a NUL, rows of fields apart by tabs, each read here alone, beside the commands asking for them.

A command asks git for the form it reads best: `-z` wherever git offers it, so
a path is read as its bytes, whatever it holds.
"""

import csv
import io
import os
from itertools import groupby
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lup.doors.parts import Finished


def line(ran: Finished) -> str:
    r"""Return what git printed as one line: an id, a path or a word, its newline left out, whatever else it holds kept.

    >>> from lup.doors.parts import Finished
    >>> line(Finished(status=0, output=b"/src/my app \n"))
    '/src/my app '
    """
    return ran.text().removesuffix("\n")


def nul_separated(output: bytes) -> list[str]:
    r"""Return the fields of git's `-z` output, each ended by a NUL, the last one's end optional, each a path's bytes as the file system names it: each run of bytes between NULs.

    >>> nul_separated(b"a.py\x00dir/b c.py\x00"), nul_separated(b"")
    (['a.py', 'dir/b c.py'], [])
    """
    runs = groupby(output, key=lambda byte: byte == 0)
    return [os.fsdecode(bytes(run)) for ended, run in runs if not ended]


def tab_separated(output: str) -> list[list[str]]:
    r"""Return the rows git printed, a line each, each its fields apart by tabs, as `git ls-remote` prints an id and a ref.

    >>> tab_separated("0123\trefs/heads/dev\n4567\trefs/heads/main\n")
    [['0123', 'refs/heads/dev'], ['4567', 'refs/heads/main']]
    """
    return list(csv.reader(io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE))
