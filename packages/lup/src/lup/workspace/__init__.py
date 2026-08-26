"""Session workspace: where a run's data lives and how it is addressed.

Where a run's data lives: version-aware paths, the `SessionContext` that
crosses a process boundary, session history, and the note directories a session
may touch.

`paths` resolves version-aware locations under the project root; `context`
carries the active :class:`SessionContext` across a process boundary for
subprocess-served tools; `history` stores, retrieves, and iterates session
data across versions; `notes` lays out the RO/RW directory structure a
session may touch.
"""
