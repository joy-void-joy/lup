"""Lup — an agent development library over multiple agent SDKs.

Core utilities for building agents with hooks, MCP tools, tracing, and
session management. SDK-specific code lives in ``lup.adapters``; this
package imports no SDK at load time — install the optional-dependency
extra for the backend you use (one per engine module under
``lup.adapters``).

``Sandbox`` is imported lazily: it requires the ``docker`` extra
(``pip install lup[docker]``), and ``import lup`` must work without it.
"""

from typing import TYPE_CHECKING

from lup.adapters.background.Background import (
    BaseBackgroundAgent,
    create_background_agent,
)
from lup.adapters.clients.Client import Client, Session
from lup.adapters.options import LupAgentOptions
from lup.adapters.wiring import create_client, query
from lup.workspace.history import (
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
    LupHooksConfig,
    allow_hook,
    block_hook,
    create_capture_hook,
    create_nudge_hook,
    create_permission_hooks,
    create_tool_allowlist_hook,
    create_tool_gate,
    deny_hook,
    merge_hooks,
)
from lup.mcp import (
    LupMcpTool,
    ToolError,
    create_mcp_server,
    lup_tool,
)
from lup.telemetry.metrics import (
    MetricsSummary,
    get_metrics_summary,
    log_metrics_summary,
    read_metrics_summary,
    reset_metrics,
    tracked,
)
from lup.workspace.notes import NotesConfig, setup_notes
from lup.workspace.paths import (
    TIMESTAMP_FMT,
    agent_version,
    configure,
    parse_timestamp,
    project_root,
)
from lup.realtime.scheduler import (
    Scheduler,
    SleepResult,
    create_meta_before_sleep_guard,
    create_pending_event_guard,
    create_stop_guard,
)
from lup.reflect import ReflectionGate, create_reflection_gate
from lup.resilience.retry import with_retry
from lup.resilience.throttle import Throttle
from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    JsonObject,
    JsonValue,
    Usage,
)

if TYPE_CHECKING:
    from lup.sandbox.container import Sandbox

__all__ = [
    "TIMESTAMP_FMT",
    "BaseBackgroundAgent",
    "Client",
    "JsonObject",
    "JsonValue",
    "LupAgentOptions",
    "LupHooksConfig",
    "LupMcpTool",
    "MetricsSummary",
    "NotesConfig",
    "ReflectionGate",
    "Sandbox",
    "Scheduler",
    "Session",
    "SessionResult",
    "SleepResult",
    "Throttle",
    "ToolError",
    "TraceLogger",
    "Usage",
    "agent_version",
    "allow_hook",
    "block_hook",
    "configure",
    "create_background_agent",
    "create_capture_hook",
    "create_client",
    "create_mcp_server",
    "create_meta_before_sleep_guard",
    "create_nudge_hook",
    "create_pending_event_guard",
    "create_permission_hooks",
    "create_reflection_gate",
    "create_stop_guard",
    "create_tool_allowlist_hook",
    "create_tool_gate",
    "deny_hook",
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
    "read_metrics_summary",
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
        from lup.sandbox.container import Sandbox

        return Sandbox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
