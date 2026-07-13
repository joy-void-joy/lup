"""SDK adapters — every engine behind one neutral seam.

``Engine`` is the contract — one backend, complete: client, background,
profiles, builtin tools — and ``engines`` holds the shipped
implementations, each a lazy front door into the concept folders.
``options`` carries the neutral ``LupAgentOptions`` vocabulary and
``errors`` the seam errors; ``wiring`` is the SDK-free door — the
``ENGINES``/``MODEL_ROUTES`` routers and ``create_client()`` / ``query()``.
``clients`` holds the purely abstract ``Client``/``Session``, the shared
client machinery, and each engine's implementation package; ``background``
holds the background contract and wake/debounce machinery plus each
engine's background agent; ``profiles`` the account registry; ``tools``
the builtin tool-name tables. A custom backend is an ``Engine`` instance
passed as ``engine=`` — no registry to edit.
"""
