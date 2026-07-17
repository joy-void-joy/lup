"""Codex-specific capability implementations and composition roots.

The runtime side: ``app_server`` is the typed JSON-RPC stdio transport,
``runtime`` opens app-server sessions behind the :mod:`lup.runtime`
contracts, and ``config`` holds profile and compatible-endpoint transforms.
The harness side: ``harness`` renders canonical declarations into the
``.codex`` plugin tree (including the generated policy dispatcher),
``harness_runtime`` probes the CLI, verifies the separately installed plugin
cache, and installs it explicitly, and ``native`` decodes hook payloads into
:mod:`lup.policy` events and renders decisions back to the wire.
"""
