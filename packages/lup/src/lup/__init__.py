"""Lup — agent development library for the Claude Agent SDK.

Core utilities for building agents with hooks, MCP tools, tracing, and session management.

``Sandbox`` is imported lazily: it requires the ``docker`` extra
(``pip install lup[docker]``), and ``import lup`` must work without it.
"""

from typing import TYPE_CHECKING

from lup.background import BackgroundAgent
from lup.client import (
    ResponseCollector,
    TokenUsage,
    build_client,
    query,
)
from lup.history import (
    SessionResult,
    format_history_for_context,
    get_latest_session_json,
    list_all_session_ids,
    load_sessions_json,
    resolve_version,
    save_session,
    update_session_metadata,
)
from lup.hooks import (
    HooksConfig,
    allow_hook_output,
    block_hook_output,
    create_capture_hook,
    create_nudge_hook,
    create_permission_hooks,
    create_tool_allowlist_hook,
    create_tool_gate,
    deny_hook_output,
    merge_hooks,
)
from lup.mcp import (
    LupMcpTool,
    ToolError,
    create_mcp_server,
    extract_sdk_tools,
    lup_tool,
)
from lup.metrics import (
    MetricsSummary,
    get_metrics_summary,
    log_metrics_summary,
    reset_metrics,
    tracked,
)
from lup.notes import NotesConfig, setup_notes
from lup.paths import (
    TIMESTAMP_FMT,
    agent_version,
    configure,
    parse_timestamp,
    project_root,
)
from lup.realtime import (
    Scheduler,
    SleepResult,
    create_meta_before_sleep_guard,
    create_pending_event_guard,
    create_stop_guard,
)
from lup.reflect import ReflectionGate, create_reflection_gate
from lup.retry import with_retry
from lup.throttle import Throttle
from lup.trace import TraceLogger, print_message

if TYPE_CHECKING:
    from lup.sandbox import Sandbox

__all__ = [
    "TIMESTAMP_FMT",
    "BackgroundAgent",
    "HooksConfig",
    "LupMcpTool",
    "MetricsSummary",
    "NotesConfig",
    "ReflectionGate",
    "ResponseCollector",
    "Sandbox",
    "Scheduler",
    "SessionResult",
    "SleepResult",
    "Throttle",
    "TokenUsage",
    "ToolError",
    "TraceLogger",
    "agent_version",
    "allow_hook_output",
    "block_hook_output",
    "build_client",
    "configure",
    "create_capture_hook",
    "create_mcp_server",
    "create_meta_before_sleep_guard",
    "create_nudge_hook",
    "create_pending_event_guard",
    "create_permission_hooks",
    "create_reflection_gate",
    "create_stop_guard",
    "create_tool_allowlist_hook",
    "create_tool_gate",
    "deny_hook_output",
    "extract_sdk_tools",
    "format_history_for_context",
    "get_latest_session_json",
    "get_metrics_summary",
    "list_all_session_ids",
    "load_sessions_json",
    "log_metrics_summary",
    "lup_tool",
    "merge_hooks",
    "parse_timestamp",
    "print_message",
    "project_root",
    "query",
    "reset_metrics",
    "resolve_version",
    "save_session",
    "setup_notes",
    "tracked",
    "update_session_metadata",
    "with_retry",
]


def __getattr__(name: str) -> object:
    """Lazy import for exports with optional dependencies."""
    if name == "Sandbox":
        from lup.sandbox import Sandbox

        return Sandbox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
