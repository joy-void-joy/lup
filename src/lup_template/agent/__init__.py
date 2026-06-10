"""Agent module for the self-improving loop.

This subpackage contains the core agent code that the feedback loop improves:
- core.py: Main agent orchestration
- config.py: Configuration via pydantic-settings
- models.py: Output models
- prompts.py: System prompt templates
- subagents.py: Subagent definitions
- tool_policy.py: Conditional tool availability (tag-based filtering)
- tools/: MCP tools (example, reflect, realtime)
"""
