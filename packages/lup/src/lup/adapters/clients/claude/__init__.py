"""The ``claude`` engine: the Claude Agent SDK behind the neutral seam.

Runs Anthropic models with the full scaffolding — in-process MCP
servers, permission hooks, native subagents, the SDK sandbox. One
concern per module:

- ``options`` — neutral→native option translation
  (``build_claude_options``) and the engine's session-grade defaults,
  shared with ``claude-compat``
  (:mod:`lup.adapters.clients.claude_compat`);
- ``hooks`` — ``LupHooksConfig`` → SDK hook wiring;
- ``messages`` — subagent, block, message, and tool conversion between
  lup types and SDK types;
- ``collector`` — the Claude response path: one turn's SDK message
  stream into a ``LupResponse``;
- ``stream`` — ``ClaudeLiveStream``, the engine's live event feed;
- ``client`` — ``create_claude``, ``compose_claude``, ``ClaudeSession``,
  and ``ClaudeSessions``: the run path.

Each module imports the SDK as a qualified namespace (``claude`` for the
package, ``claude_types`` for its ``types`` submodule) so every SDK type
reads with its origin visible at the use site.
"""
