"""The ``codex`` engine: the OpenAI Codex runtime behind the neutral seam.

Runs OpenAI models on the Codex app-server. The runtime is a subprocess,
so tools are served externally (``served_tool_groups``), writes are
confined natively (``writable_roots``), and persistent mode rides the
file-relay mailbox. One concern per module:

- ``options`` — translation-side helpers: the effort map, the
  priced-budget read, and the session's sandbox-cleanup guarantee;
- ``config`` — the ``config_overrides`` builders (MCP servers, native
  sandbox, command hooks);
- ``messages`` — thread-item conversion into lup types and the
  turn-result projection;
- ``usage`` — usage normalization and per-MTok cost estimation;
- ``hooks`` — lup hook policies rendered as standalone Codex
  command-hook scripts. Quarantined: a live probe showed config.toml
  command hooks never fire on the Codex builds this project targets, so
  no live adapter wires it — enforcement is the native workspace-write
  sandbox — and the module is kept as the wire-format reference,
  imported only by tests;
- ``client`` — ``create_codex``, ``compose_codex``, ``CodexSession``,
  and ``CodexSessions``: the run path.

``openai-compat`` (:mod:`lup.adapters.clients.openai_compat`) fronts any
OpenAI-protocol endpoint through this same runtime. Each module imports
the Codex SDK as a qualified namespace (``codex`` for the package,
``codex_items`` for its generated item types) so every SDK type reads
with its origin visible.
"""
