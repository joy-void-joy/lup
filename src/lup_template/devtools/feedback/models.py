"""Feedback data shapes: session JSON, domain results, and report rows.

This is a TEMPLATE script. Run ``/lup:init`` to customize it for your domain.
The loaders live in ``state``, aggregation in ``metrics``, presentation in
``reports``.
"""

from typing import TypedDict

from pydantic import BaseModel

from lup.telemetry.metrics import MetricsSummary, ToolMetricsDict

# =============================================================================
# SESSION JSON TYPES
# =============================================================================


class TokenUsage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int


class SessionData(TypedDict, total=False):
    """Raw session JSON loaded from disk.

    The payload shape comes from :class:`lup.workspace.history.SessionResult`;
    ``_session_id`` and ``_file`` are injected at load time for display.
    """

    timestamp: str
    agent_sdk: str
    outcome: object
    tool_metrics: MetricsSummary
    token_usage: TokenUsage
    cost_usd: float
    output: dict[str, str]
    _session_id: str
    _file: str


# =============================================================================
# TEMPLATE: replace these models' fields with what your domain scores on
# =============================================================================


class SessionResult(BaseModel):
    """A session matched with its outcome/feedback.

    Replace ``outcome``/``metrics`` with the fields your domain scores on.
    This is the per-domain shape the whole feedback loop aggregates over
    (``/lup:init`` customization step 9); the generic fields below only
    carry sessions through unscored until you do.

    Customize this for your domain. Examples:

    For forecasting:
        question_id: int
        probability: float
        resolution: bool | None
        brier_score: float | None

    For coaching:
        conversation_id: str
        user_rating: int | None
        session_duration: float
        goals_addressed: list[str]

    For game playing:
        game_id: str
        outcome: str  # "win", "loss", "draw"
        moves_played: int
        opponent_strength: float
    """

    session_id: str
    timestamp: str
    agent_sdk: str | None = None
    outcome: object | None = None
    metrics: MetricsSummary | None = None


class FeedbackMetrics(BaseModel):
    """Aggregated metrics from sessions.

    Customize this for your domain.
    """

    collection_timestamp: str
    since_timestamp: str | None = None
    total_sessions: int
    sessions_with_outcomes: int
    sessions_by_sdk: dict[str, int] = {}
    results: list[SessionResult] = []


# =============================================================================
# JSON OUTPUT TYPES
# =============================================================================


class ToolUsageEntry(TypedDict):
    name: str
    calls: int
    errors: int
    error_rate: float
    avg_ms: float


class ErrorSessionEntry(TypedDict):
    session_id: str
    errors: int
    by_tool: dict[str, ToolMetricsDict]


class TrendEntry(TypedDict):
    date: str
    avg_calls: float
    error_rate: float
    avg_cost: float


class PromptSection(TypedDict):
    name: str
    lines: int
    characters: int


class PromptHealthReport(TypedDict):
    file: str
    rendered_characters: int
    estimated_tokens: int
    sections: list[PromptSection]


class FeedbackFileData(TypedDict, total=False):
    total_sessions: int
    sessions_with_outcomes: int


class BackendCostRow(TypedDict):
    """Per-backend rollup row for the costs command."""

    sessions: int
    cost_usd: float
    without_cost: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int


def empty_cost_row() -> BackendCostRow:
    return BackendCostRow(
        sessions=0,
        cost_usd=0.0,
        without_cost=0,
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
    )
