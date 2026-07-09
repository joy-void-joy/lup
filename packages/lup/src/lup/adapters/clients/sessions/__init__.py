"""The session concept: ``Session`` (one live conversation), ``Sessions``
(an engine's opener for them), and the governance wrappers any engine can
compose over its own — ``budget`` (cost metering + refusal) and
``timeout`` (a wall clock per turn). Engines implement the verbs inside
their own packages (``clients/claude/``, ``clients/codex/``)."""
