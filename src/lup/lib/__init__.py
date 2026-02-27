"""Library utilities for self-improving agents.

This package contains reusable, **parametric** abstractions that work
out of the box and are configured through function arguments — never
by modifying the source. Domain-specific code belongs in lup.agent.

Import directly from submodules (e.g., ``from lup.lib.mcp import lup_tool``).

Modules:
- client: Agent SDK client creation and response collection
- history: Session history storage and retrieval (generic, model-agnostic)
- hooks: Claude Agent SDK hook utilities (permission, nudge, capture)
- metrics: Tool call tracking with @tracked decorator
- mcp: MCP server creation utilities
- notes: RO/RW notes directory structure
- paths: Centralized path constants (configurable via configure())
- realtime: Scheduler for persistent agents (sleep/wake, debounce, reminders)
- reflect: Reflection gate (enforce reflect-before-output)
- responses: MCP response formatting utilities
- retry: Retry decorator for API calls
- sandbox: Docker-based Python sandbox for isolated code execution
"""
