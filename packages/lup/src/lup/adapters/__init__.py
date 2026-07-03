"""SDK adapters — every engine behind one neutral seam.

Five modules: ``common`` is the whole SDK-free seam (the
Session/Client/Engine ABCs, the unsupported-behavior errors, the
model-name router, and the doors in — ``create_client()`` and the
one-shot ``query()``); ``claude`` and ``codex`` are the primary engines,
one per SDK; ``claude_compat`` and ``openai_compat`` subclass their
primary to front Anthropic- and OpenAI-protocol-compatible endpoints.
"""
