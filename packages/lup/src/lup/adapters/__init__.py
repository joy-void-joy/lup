"""SDK adapters — every engine behind one neutral seam.

``options`` carries the neutral ``LupAgentOptions`` vocabulary and
``errors`` the seam errors; ``wiring`` is the SDK-free door — the
``ENGINES``/``MODEL_ROUTES`` routers and ``create_client()`` / ``query()``.
``clients`` holds the purely abstract ``Client``/``Session`` and each
engine's client, translation, and ``create_*`` factory; ``background``
holds the shared wake/debounce machinery and each engine's background
agent. A custom backend is a factory callable passed as ``engine=`` — no
registry to edit.
"""
