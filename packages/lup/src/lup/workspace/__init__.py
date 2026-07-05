"""Session workspace: where a run's data lives and how it is addressed.

`paths` resolves version-aware locations under the project root and relays
the active :class:`SessionContext`; `context` carries that context across a
process boundary for subprocess-served tools. `history` stores and retrieves
sessions; `notes` lays out the RO/RW directory structure; `output` finalizes
the agent's submitted result.
"""
