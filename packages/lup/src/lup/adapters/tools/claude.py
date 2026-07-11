"""Claude Code's builtin tool table (SDK-free).

The names are the framework's neutral vocabulary
(:mod:`lup.adapters.tools.names` — they originate here); this module
holds what is Claude's own: the set of tools a Claude session may call
natively.
"""

from lup.adapters.tools.names import (
    BASH,
    EDIT,
    ToolNames,
    GLOB,
    GREP,
    NOTEBOOK_EDIT,
    READ,
    TASK,
    TODO_WRITE,
    WEB_FETCH,
    WEB_SEARCH,
    WRITE,
)

CLAUDE_BUILTIN_TOOLS: ToolNames = frozenset(  # lup: ignore[frozenset-shape]
    {
        BASH,
        EDIT,
        GLOB,
        GREP,
        NOTEBOOK_EDIT,
        READ,
        TASK,
        TODO_WRITE,
        WEB_FETCH,
        WEB_SEARCH,
        WRITE,
    }
)
"""The tools a Claude session may call natively (shell/file/web).

A property of the Claude backend, not of any domain. The allowlist
computation (``BaseToolPolicy.get_allowed_tools``) takes an engine's
built-in set as a parameter and adds the ``mcp__{server}__{tool}`` names;
subprocess-served backends get their tools from the served MCP groups
plus the runtime's own native tools instead."""
