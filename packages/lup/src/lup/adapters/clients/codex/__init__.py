"""The ``codex`` engine: the OpenAI Codex runtime behind the neutral seam.

Runs OpenAI models on the Codex app-server. The runtime is a subprocess,
so tools are served externally (``served_tool_groups``), writes are
confined natively (``writable_roots``), and persistent mode rides the
file-relay mailbox. One concern per module:

- ``native`` — ``CodexNativeConfig``, the translated configuration the
  client carries;
- ``translate`` — ``build_codex_native`` and its helpers: the effort
  map, the priced-budget read, the sandbox-cleanup guard factory;
- ``config`` — the ``config_overrides`` builders (MCP servers, native
  sandbox);
- ``messages`` — thread-item conversion into lup types and the
  turn-result projection;
- ``usage`` — usage normalization and per-MTok cost estimation;
- ``sessions`` — ``CodexSession`` and ``CodexSessions``: the run path;
- ``create`` — ``create_codex`` and ``compose_codex``: the construction
  door.

``openai-compat`` (:mod:`lup.adapters.clients.codex.compat`) fronts any
OpenAI-protocol endpoint through this same runtime. Each module imports
the Codex SDK as a qualified namespace (``codex`` for the package,
``codex_items`` for its generated item types) so every SDK type reads
with its origin visible.
"""
