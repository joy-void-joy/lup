"""Lup — agent development library for the Claude Agent SDK.

Core utilities for building agents with hooks, MCP tools, tracing, and session management.
"""

from lup.adapters.claude_client import ResponseCollector, build_client
from lup.adapters.claude_client import query as claude_query
from lup.adapters.common import query
from lup.hooks import (
    create_capture_hook,
    create_nudge_hook,
    create_permission_hooks,
    create_reflection_gate,
    create_tool_allowlist_hook,
)
from lup.mcp import (
    LupMcpTool,
    ToolError,
    create_mcp_server,
    lup_tool,
)
from lup.metrics import (
    MetricsSummary,
    get_metrics_summary,
    log_metrics_summary,
    reset_metrics,
)
from lup.paths import agent_version, configure, project_root
from lup.reflect import ReflectionGate
from lup.trace import TraceLogger, print_message
from lup.types import (
    LupHooksConfig,
    TokenUsage,
    allow_hook,
    block_hook,
    deny_hook,
    merge_hooks,
)

__all__ = [
    "LupHooksConfig",
    "LupMcpTool",
    "MetricsSummary",
    "ReflectionGate",
    "ResponseCollector",
    "TokenUsage",
    "ToolError",
    "TraceLogger",
    "agent_version",
    "allow_hook",
    "block_hook",
    "build_client",
    "claude_query",
    "configure",
    "create_capture_hook",
    "create_mcp_server",
    "create_nudge_hook",
    "create_permission_hooks",
    "create_reflection_gate",
    "create_tool_allowlist_hook",
    "deny_hook",
    "get_metrics_summary",
    "log_metrics_summary",
    "lup_tool",
    "merge_hooks",
    "print_message",
    "project_root",
    "query",
    "reset_metrics",
]
