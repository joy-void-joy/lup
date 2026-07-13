"""The ``claude`` engine: the Claude Agent SDK behind the neutral seam.

Runs Anthropic models with the full scaffolding — in-process MCP
servers, permission hooks, native subagents, the SDK sandbox. One
concern per module; ``create`` is the recipe that names every slot.
Each module imports the SDK as a qualified namespace (``claude`` for the
package, ``claude_types`` for its ``types`` submodule) so every SDK type
reads with its origin visible at the use site.
"""
