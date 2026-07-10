"""Feedback aggregation: session results into domain metrics and cost rollups.

This is a TEMPLATE script. Run ``/lup:init`` to customize it for your domain.
"""

from collections import Counter
from datetime import datetime

from lup_template.devtools.feedback.models import (
    BackendCostRow,
    FeedbackMetrics,
    SessionData,
    SessionResult,
    empty_cost_row,
)


def compute_metrics(results: list[SessionResult]) -> FeedbackMetrics:
    """Compute aggregate metrics from session results.

    TEMPLATE: aggregate the outcome fields your domain scores on.
    Examples: a mean Brier score, win rate, or rating average.

    Sessions are counted per backend (``sessions_by_sdk``) so mixed
    Claude/Codex collections never pool silently into one trend.
    """
    sessions_with_outcomes = sum(1 for r in results if r.outcome is not None)
    by_sdk = Counter(r.agent_sdk or "unknown" for r in results)

    return FeedbackMetrics(
        collection_timestamp=datetime.now().isoformat(),
        total_sessions=len(results),
        sessions_with_outcomes=sessions_with_outcomes,
        sessions_by_sdk=dict(by_sdk),
        results=results,
    )


def rollup_costs(
    sessions: list[SessionData],
) -> dict[str, BackendCostRow]:
    """Group session cost and token totals by ``agent_sdk``.

    Sessions without a cost (codex/openai runs without
    ``CODEX_USD_PER_MTOK_*`` rates) count into ``without_cost`` so a
    missing-rates gap stays visible instead of reading as free.
    """
    rows: dict[str, BackendCostRow] = {}
    for s in sessions:
        sdk = s.get("agent_sdk") or "unknown"
        row = rows.setdefault(sdk, empty_cost_row())
        row["sessions"] += 1
        cost = s.get("cost_usd")
        if cost:
            row["cost_usd"] += cost
        else:
            row["without_cost"] += 1
        usage = s.get("token_usage") or {}
        row["input_tokens"] += usage.get("input_tokens", 0) or 0
        row["output_tokens"] += usage.get("output_tokens", 0) or 0
        row["cache_read_input_tokens"] += usage.get("cache_read_input_tokens", 0) or 0
    return rows
