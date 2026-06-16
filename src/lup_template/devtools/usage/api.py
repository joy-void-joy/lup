"""Data layer for the usage display.

Loads Claude Code OAuth credentials, fetches the live usage API at
api.anthropic.com, and parses stats-cache.json into typed models.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

import httpx
from pydantic import BaseModel, ConfigDict, Field

# ── constants ──────────────────────────────────────────────


def creds_path(config_dir: Path) -> Path:
    """OAuth credentials file inside a Claude config dir."""
    return config_dir / ".credentials.json"


def stats_path(config_dir: Path) -> Path:
    """Stats cache file inside a Claude config dir."""
    return config_dir / "stats-cache.json"


USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA = "oauth-2025-04-20"


# ── API response types ─────────────────────────────────────


class UsageBucket(TypedDict):
    utilization: float
    resets_at: str


class ExtraUsage(TypedDict):
    is_enabled: bool
    monthly_limit: int
    used_credits: float
    utilization: float


class UsageResponse(TypedDict):
    five_hour: UsageBucket | None
    seven_day: UsageBucket | None
    seven_day_opus: UsageBucket | None
    seven_day_sonnet: UsageBucket | None
    seven_day_oauth_apps: UsageBucket | None
    seven_day_cowork: UsageBucket | None
    iguana_necktie: UsageBucket | None
    extra_usage: ExtraUsage | None


# ── stats cache models ─────────────────────────────────────


class DailyActivity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date: str
    message_count: int = Field(alias="messageCount", default=0)
    session_count: int = Field(alias="sessionCount", default=0)
    tool_call_count: int = Field(alias="toolCallCount", default=0)


class DailyModelTokens(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date: str
    tokens_by_model: dict[str, int] = Field(alias="tokensByModel", default_factory=dict)


class ModelUsageEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    input_tokens: int = Field(alias="inputTokens", default=0)
    output_tokens: int = Field(alias="outputTokens", default=0)
    cache_read_input_tokens: int = Field(alias="cacheReadInputTokens", default=0)
    cache_creation_input_tokens: int = Field(
        alias="cacheCreationInputTokens", default=0
    )
    web_search_requests: int = Field(alias="webSearchRequests", default=0)
    cost_usd: float = Field(alias="costUSD", default=0)
    context_window: int = Field(alias="contextWindow", default=0)
    max_output_tokens: int = Field(alias="maxOutputTokens", default=0)


class LongestSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    session_id: str = Field(alias="sessionId")
    duration: int
    message_count: int = Field(alias="messageCount")
    timestamp: str


class StatsCache(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    version: int = 0
    last_computed_date: str = Field(alias="lastComputedDate", default="")
    daily_activity: list[DailyActivity] = Field(
        alias="dailyActivity", default_factory=list
    )
    daily_model_tokens: list[DailyModelTokens] = Field(
        alias="dailyModelTokens", default_factory=list
    )
    model_usage: dict[str, ModelUsageEntry] = Field(
        alias="modelUsage", default_factory=dict
    )
    total_sessions: int = Field(alias="totalSessions", default=0)
    total_messages: int = Field(alias="totalMessages", default=0)
    longest_session: LongestSession | None = Field(alias="longestSession", default=None)
    first_session_date: str = Field(alias="firstSessionDate", default="")
    hour_counts: dict[str, int] = Field(alias="hourCounts", default_factory=dict)
    total_speculation_time_saved_ms: int = Field(
        alias="totalSpeculationTimeSavedMs", default=0
    )


# ── derived data ───────────────────────────────────────────


class DailyBreakdown(BaseModel):
    date: str
    total_tokens: int
    tokens_by_model: dict[str, int]
    activity: DailyActivity | None


# ── API ────────────────────────────────────────────────────


def fetch_usage(config_dir: Path) -> UsageResponse:
    """Call the live usage API using the profile's OAuth credentials."""
    creds_file = creds_path(config_dir)
    try:
        creds = json.loads(creds_file.read_text())
        oauth = creds["claudeAiOauth"]
        token: str = oauth["accessToken"]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        msg = f"Bad credentials file at {creds_file}: {e}"
        raise RuntimeError(msg) from e

    resp = httpx.get(
        USAGE_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": ANTHROPIC_BETA,
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data: UsageResponse = resp.json()
    return data


# ── stats cache ────────────────────────────────────────────


def load_stats(config_dir: Path) -> StatsCache | None:
    path = stats_path(config_dir)
    if not path.exists():
        return None
    try:
        return StatsCache.model_validate_json(path.read_bytes())
    except (ValueError, OSError):
        return None


def get_daily_breakdown(
    stats: StatsCache,
    window_start: datetime,
    window_end: datetime,
) -> list[DailyBreakdown]:
    """Get per-day token and activity breakdown for a time window."""
    tokens_by_date = {
        entry.date: entry.tokens_by_model for entry in stats.daily_model_tokens
    }
    activity_by_date = {entry.date: entry for entry in stats.daily_activity}

    days: list[DailyBreakdown] = []
    d = window_start.date()
    end = window_end.date()
    while d <= end:
        ds = d.isoformat()
        by_model = tokens_by_date.get(ds, {})
        days.append(
            DailyBreakdown(
                date=ds,
                total_tokens=sum(by_model.values()),
                tokens_by_model=by_model,
                activity=activity_by_date.get(ds),
            )
        )
        d += timedelta(days=1)
    return days
