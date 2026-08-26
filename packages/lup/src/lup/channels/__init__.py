"""File-backed channels: a value that settles, and an ordered log.

The widest dependency in the library: most of its top-level entries write
through this one, which is what makes it a package rather than a helper inside
any of them. Counted rather than listed, because the list is the thing that
falls behind — the roster this paragraph came from named six consumers where
the import graph held eleven, and nobody notices a sentence going stale.
"""
