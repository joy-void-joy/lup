"""The ``codex`` engine: the OpenAI Codex runtime behind the neutral seam.

Runs OpenAI models on the Codex app-server. The runtime is a subprocess,
so tools are served externally (``served_tool_groups``), writes are
confined natively (``writable_roots``), and persistent mode rides the
file-relay mailbox. One concern per module; ``create`` is the recipe
that names every slot, composing the governance the runtime lacks
(budget, turn timeout) over pure thread-driving sessions.
``openai-compat`` (:mod:`lup.adapters.clients.codex.compat`) fronts any
OpenAI-protocol endpoint through this same runtime. Each module imports
the Codex SDK as a qualified namespace (``codex`` for the package,
``codex_items`` for its generated item types) so every SDK type reads
with its origin visible.
"""
