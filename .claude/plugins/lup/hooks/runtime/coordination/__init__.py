"""The half of coordination a bare interpreter runs, shipped into every plugin.

Three processes read one repository's coordination store and no two of them
share an import: the typed library inside a session's tool server, the hooks a
runtime spawns as bare scripts before a prompt and as a session ends, and the
compiled permission dispatcher. Only the first has ``lup`` on its path, and
only the first has pydantic — so anything all three must agree about has to be
written under the strictest of the three constraints, which is this package:
the standard library alone, no third-party import, and no reach into ``lup``.

Each plugin ships it whole beneath ``hooks/runtime/``, the way the policy
kernel is shipped, so the modules here resolve each other by relative import
in the plugin exactly as they do in the library and travel byte for byte.
"""
