"""What lup keeps beneath the git directory every worktree of a clone shares.

Each name here is written by one module and read by another that never
imports it: the gate that takes a slot and the launch that makes the
directory before a read-only lease would refuse it; the sweep that archives
traces and the launch again. Declared once where both reach, so a rename in
one reaches the other rather than leaving a launch that readies a directory
nothing writes.
"""

# lup: ignore[constant-declaration] — an identity this repository defines: the
# directory a run takes its slot in, which every session must spell alike for
# any of them to see that another is holding one
SLOT_DIRECTORY = "lup-gate-slots"
"""Where this clone's slots live, beneath the shared git directory.

The one place every worktree of a clone agrees on, and one no worktree's own
branch can move out from under another.
"""

ARCHIVE_DIRECTORY_NAME = "trace-archive"
"""What the archive directory is called inside the common directory.

A default rather than a frozen name so a caller can say where to keep an
archive, which is what a test needs and what a repository holding two of them
would need. The location it sits in is still derived; only the leaf is named."""
