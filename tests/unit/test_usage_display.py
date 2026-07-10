# lup: ignore[dict-get]
# Test fixtures and assertions construct these shapes deliberately.
"""Tests for the Claude Code usage display assembly.

The daily breakdown is fed by the local stats cache, so it must render
even when the live API exposes no weekly bucket — the bug that hid it in
the direct (non-watch) path. The ``--json`` snapshot must surface the
same buckets and trailing-week tokens as machine-readable counts.
"""

import json
from datetime import datetime, timedelta, timezone

from rich.console import Console

from lup_template.devtools.usage.api import StatsCache, UsageResponse
from lup_template.devtools.usage.render import build_display, build_snapshot


def recent_stats() -> StatsCache:
    """A stats cache (camelCase, as written on disk) inside the trailing week."""
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in (2, 1)]
    return StatsCache.model_validate(
        {
            "lastComputedDate": today.isoformat(),
            "dailyModelTokens": [
                {"date": days[0], "tokensByModel": {"claude-opus-4-8": 900_000}},
                {"date": days[1], "tokensByModel": {"claude-sonnet-4-6": 50_000}},
            ],
            "dailyActivity": [
                {"date": days[0], "messageCount": 120},
                {"date": days[1], "messageCount": 30},
            ],
        }
    )


def usage_without_weekly() -> UsageResponse:
    """An account that exposes only a 5-hour window — no weekly bucket."""
    resets = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    return {
        "five_hour": {"utilization": 12.0, "resets_at": resets},
        "seven_day": None,
        "seven_day_opus": None,
        "seven_day_sonnet": None,
        "seven_day_oauth_apps": None,
        "seven_day_cowork": None,
        "iguana_necktie": None,
        "extra_usage": None,
    }


def render(usage: UsageResponse, stats: StatsCache | None) -> str:
    console = Console(force_terminal=False, width=90)
    with console.capture() as cap:
        console.print(build_display(usage, stats, True, 58))
    return cap.get()


class TestDailyBreakdownWithoutWeeklyBucket:
    def test_breakdown_renders_from_stats_alone(self) -> None:
        # The weekly API bucket once gated the breakdown; local stats now drive it.
        out = render(usage_without_weekly(), recent_stats())
        assert "per day" in out
        assert "models" in out

    def test_no_stats_means_no_breakdown(self) -> None:
        out = render(usage_without_weekly(), None)
        assert "per day" not in out


class TestSnapshot:
    def test_buckets_and_tokens_match_stats(self) -> None:
        snap = build_snapshot(usage_without_weekly(), recent_stats())
        assert [b.name for b in snap.buckets] == ["5-hour"]
        assert snap.tokens_by_model["claude-opus-4-8"] == 900_000
        assert snap.tokens_by_model["claude-sonnet-4-6"] == 50_000
        assert len(snap.daily) == 7
        assert any(d.message_count == 120 for d in snap.daily)

    def test_no_stats_yields_empty_daily(self) -> None:
        snap = build_snapshot(usage_without_weekly(), None)
        assert snap.daily == []
        assert snap.tokens_by_model == {}
        assert snap.stats_cache_date is None


def test_json_dumps_snapshot_is_valid_json() -> None:
    snap = build_snapshot(usage_without_weekly(), recent_stats())
    parsed = json.loads(snap.model_dump_json())
    assert parsed["buckets"][0]["name"] == "5-hour"
    assert parsed["stats_cache_date"]
