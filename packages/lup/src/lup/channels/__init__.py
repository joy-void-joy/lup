"""File-backed channels: a value that settles, and an ordered log.

The widest dependency in the library: most of its top-level entries write
through this one, which is what makes it a package rather than a helper inside
any of them. Counted rather than listed, because the list is the thing that
falls behind — the roster this paragraph came from named six consumers where
the import graph held eleven, and nobody notices a sentence going stale.

A foundation rather than part of a subject, which is why it sits beside
:mod:`lup.types` and not under one. It imports nothing else in the library,
and the two halves it serves belong to different subjects: most callers take
the atomic write and the timestamp, while the actors take the slot, the
stream and the cursor they meet each other over. Filing it under storage was
tried and manufactured a cycle — the journals read a stream while a
workspace's history reads a metrics summary, so the two entries closed a loop
that had been two separate one-way edges.
"""
