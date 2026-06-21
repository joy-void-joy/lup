"""Claude Agent SDK built-in tool names.

A property of the Claude backend, not of any domain: the set of tools the SDK
exposes natively (shell/file/web) plus the framework tool the agent emits its
structured output through. The allowlist computation reads these to name every
tool a Claude session may call; Codex/OpenAI agents get tools from the served
MCP groups plus the Codex runtime's own native tools instead.
"""

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
"""The Claude Code built-in tool names a session may call."""

FRAMEWORK_TOOLS: frozenset[str] = frozenset({"StructuredOutput"})
"""Tools the agent always needs: ``StructuredOutput`` emits the final result
under ``ClaudeAgentOptions.output_format``, so the allowlist must carry it even
though no template tool defines it."""
