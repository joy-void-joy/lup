"""The Claude Code built-in tool-name table (SDK-free)."""

CLAUDE_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {
        "Bash",
        "Edit",
        "Glob",
        "Grep",
        "NotebookEdit",
        "Read",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)
"""The tools a Claude session may call natively (shell/file/web).

A property of the Claude backend, not of any domain. The allowlist
computation (``BaseToolPolicy.get_allowed_tools``) takes an engine's
built-in set as a parameter and adds the ``mcp__{server}__{tool}`` names;
subprocess-served backends get their tools from the served MCP groups
plus the runtime's own native tools instead."""
