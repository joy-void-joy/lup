"""Python introspection tools.

Vetted alternatives to ``python -c`` for package, type, and value exploration.

Examples::

    $ uv run lup-devtools dev py info claude_agent_sdk.types.ToolUseBlock
    $ uv run lup-devtools dev py info pydantic.BaseModel --schema
    $ uv run lup-devtools dev py source lup.tools.mcp.lup_tool
    $ uv run lup-devtools dev py source claude_agent_sdk --tree
    $ uv run lup-devtools dev py imports lup.tools.mcp
    $ uv run lup-devtools dev py imports lup.tools.mcp --reverse
    $ uv run lup-devtools dev py search ToolUseBlock
"""
