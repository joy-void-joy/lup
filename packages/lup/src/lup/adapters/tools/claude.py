"""Claude Code's built-in tool vocabulary (SDK-free).

The framework adopts these tool names as its neutral lingua franca: each name
is spelled once here, and every non-Claude adapter translates its backend's
native tool identifiers to and from these constants. Consumers reference the
constants — or the grouped sets below — instead of re-spelling the strings, so
a rename lands in one place.
"""

BASH = "Bash"
EDIT = "Edit"
GLOB = "Glob"
GREP = "Grep"
NOTEBOOK_EDIT = "NotebookEdit"
READ = "Read"
TASK = "Task"
TODO_WRITE = "TodoWrite"
WEB_FETCH = "WebFetch"
WEB_SEARCH = "WebSearch"
WRITE = "Write"

CLAUDE_BUILTIN_TOOLS: frozenset[str] = frozenset(
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


WEB_TOOLS: set[str] = {WEB_SEARCH, WEB_FETCH}
"""The web-reaching builtins — search and fetch. Code that keys on whether a
turn touched the web matches against this set instead of re-listing the two
names."""
