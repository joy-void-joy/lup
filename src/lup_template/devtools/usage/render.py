# lup: ignore[dict-get]
# Every read here probes the OAuth usage API's payload (all-optional keys)
# or an open per-model tally, so dict-get is opted out file-wide.
"""Pure rendering for the usage display.

Formats pacing bars, labels, bucket sections, the daily breakdown, and
the assembled panel from already-fetched data — no I/O here.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

from pydantic import BaseModel
from rich.panel import Panel
from rich.text import Text

from lup_template.devtools.usage.api import (
    DailyBreakdown,
    ExtraUsage,
    StatsCache,
    UsageBucket,
    UsageResponse,
    get_daily_breakdown,
)

# ── constants ──────────────────────────────────────────────

# Open map: new model ids appear ahead of this table; .get falls back to the id.
MODEL_NAMES: dict[str, str] = {  # lup: ignore[dict-str-payload]
    "claude-opus-4-8": "Opus 4.8",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-5-20251101": "Opus 4.5",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-sonnet-4-5-20250929": "Sonnet 4.5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}

MODEL_COLORS: dict[str, str] = {  # lup: ignore[dict-str-payload] — family → style
    "opus": "bright_magenta",
    "sonnet": "bright_blue",
    "haiku": "bright_cyan",
}

DAY_NAMES = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

# Bucket key in the API response → (display label, window length in hours).
# One source for both the pacing bars and the --json snapshot.
BUCKET_SPECS: list[tuple[str, str, float]] = [  # lup: ignore[tuple-shape] — spec rows
    ("seven_day", "weekly", 7 * 24),
    ("five_hour", "5-hour", 5),
    ("seven_day_opus", "opus 7d", 7 * 24),
    ("seven_day_sonnet", "sonnet 7d", 7 * 24),
    ("seven_day_cowork", "cowork 7d", 7 * 24),
    ("seven_day_oauth_apps", "oauth 7d", 7 * 24),
]


# ── display models ─────────────────────────────────────────


class PaceLabel(BaseModel):
    word: str
    style: str


# ── machine-readable snapshot ──────────────────────────────


class BucketSnapshot(BaseModel):
    """One rate-limit window as counts and limits an agent can act on."""

    name: str
    utilization_pct: float
    pace: str
    resets_at: str
    resets_in_seconds: int


class OverageSnapshot(BaseModel):
    enabled: bool
    used_usd: float
    limit_usd: float
    utilization_pct: float


class DaySnapshot(BaseModel):
    date: str
    total_tokens: int
    tokens_by_model: dict[str, int]  # lup: ignore[dict-str-payload] — open tally
    message_count: int


class UsageSnapshot(BaseModel):
    """Full machine-readable usage state for ``--json`` consumers."""

    buckets: list[BucketSnapshot]
    overage: OverageSnapshot | None
    daily: list[DaySnapshot]
    tokens_by_model: dict[str, int]  # lup: ignore[dict-str-payload] — open tally
    stats_cache_date: str | None


# ── pacing thresholds ──────────────────────────────────────

PACE_LABEL_THRESHOLDS: list[tuple[float, PaceLabel]] = [  # lup: ignore[tuple-shape]
    (0.5, PaceLabel(word="cruising", style="bold bright_green")),
    (0.85, PaceLabel(word="on track", style="bold bright_cyan")),
    (1.0, PaceLabel(word="on pace", style="bold bright_cyan")),
    (1.3, PaceLabel(word="ahead", style="bold bright_yellow")),
    (1.6, PaceLabel(word="running hot", style="bold bright_red")),
]
PACE_LABEL_DEFAULT = PaceLabel(word="heavy usage", style="bold red")


# ── formatting helpers ─────────────────────────────────────


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def fmt_countdown(dt: datetime) -> str:
    total_seconds = (dt - datetime.now(dt.tzinfo)).total_seconds()
    if total_seconds <= 0:
        return "now"
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    if h >= 48:
        return f"{h // 24}d {h % 24}h"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def model_color(model_id: str) -> str:
    for key, color in MODEL_COLORS.items():
        if key in model_id:
            return color
    return "white"


def pace_color(ratio: float) -> str:
    return pace_label(ratio).style.split()[-1]


def pace_label(ratio: float) -> PaceLabel:
    for threshold, label in PACE_LABEL_THRESHOLDS:
        if ratio <= threshold:
            return label
    return PACE_LABEL_DEFAULT


def get_bucket(usage: UsageResponse, key: str) -> UsageBucket | None:
    """Look up a rate-limit bucket by its API key, ignoring missing windows."""
    match key:
        case "seven_day":
            return usage.get("seven_day")
        case "five_hour":
            return usage.get("five_hour")
        case "seven_day_opus":
            return usage.get("seven_day_opus")
        case "seven_day_sonnet":
            return usage.get("seven_day_sonnet")
        case "seven_day_cowork":
            return usage.get("seven_day_cowork")
        case "seven_day_oauth_apps":
            return usage.get("seven_day_oauth_apps")
        case _:
            return None


class BucketPace(NamedTuple):
    """Where a bucket stands against even pace."""

    linear_pct: float
    ratio: float


def bucket_pace(bucket: UsageBucket, window_hours: float) -> BucketPace:
    """Even-pace percent and the utilization-to-pace ratio for a bucket."""
    resets_at = datetime.fromisoformat(bucket["resets_at"])
    window_start = resets_at - timedelta(hours=window_hours)
    now = datetime.now(resets_at.tzinfo)
    elapsed = (now - window_start).total_seconds()
    total = window_hours * 3600
    linear_pct = min((elapsed / total) * 100, 100) if total > 0 else 0
    ratio = (bucket["utilization"] / linear_pct) if linear_pct > 0 else 0
    return BucketPace(linear_pct, ratio)


def place_label(text: str, position: int, line_width: int) -> str:
    """Place a text label at a horizontal position in a fixed-width line."""
    line = [" "] * line_width
    for j, ch in enumerate(text):
        pos = position + j
        if 0 <= pos < line_width:
            line[pos] = ch
    return "".join(line)


# ── rendering ──────────────────────────────────────────────


BAR_INDENT = 8  # matches daily bar prefix "  Sa    "


def render_bar(
    out: Text,
    utilization: float,
    linear_pct: float,
    bar_width: int,
) -> None:
    """Render a pacing bar with actual fill and a linear-pace marker."""
    actual_frac = utilization / 100.0
    linear_frac = linear_pct / 100.0
    fill_color = pace_color(actual_frac / linear_frac if linear_frac > 0 else 0)

    actual_pos = min(int(actual_frac * bar_width), bar_width)
    linear_pos = min(int(linear_frac * bar_width), bar_width - 1)

    out.append(" " * BAR_INDENT)
    for i in range(bar_width):
        if i == linear_pos:
            out.append("▎", style="bright_black")
        elif i < actual_pos:
            out.append("█", style=fill_color)
        else:
            out.append("░", style="bright_black")
    out.append("\n")


def render_bucket(
    out: Text,
    label: str,
    bucket: UsageBucket,
    window_hours: float,
    bar_width: int,
) -> None:
    """Render a usage bucket: label, pacing bar, annotations."""
    utilization = bucket["utilization"]
    resets_at = datetime.fromisoformat(bucket["resets_at"])
    linear_pct, ratio = bucket_pace(bucket, window_hours)

    pace = pace_label(ratio)

    out.append(f"  {label}", style="bold bright_white")
    out.append(f"  {utilization:.0f}%", style="bold")
    out.append(f"  ◆ {pace.word}", style=pace.style)
    out.append(f"  resets in {fmt_countdown(resets_at)}", style="dim")
    out.append("\n")

    render_bar(out, utilization, linear_pct, bar_width)

    line_width = BAR_INDENT + bar_width

    you_text = f"↑ you ({utilization:.0f}%)"
    you_bar = min(int((utilization / 100) * bar_width), bar_width - len(you_text))
    out.append(place_label(you_text, BAR_INDENT + you_bar, line_width), style="dim")
    out.append("\n")

    pace_text = f"↑ even ({linear_pct:.0f}%)"
    pace_bar = min(int((linear_pct / 100) * bar_width), bar_width - len(pace_text))
    out.append(place_label(pace_text, BAR_INDENT + pace_bar, line_width), style="dim")
    out.append("\n")


def render_overage(out: Text, extra: ExtraUsage, bar_width: int) -> None:
    """Render the extra usage (overage) section."""
    used = extra["used_credits"] or 0
    limit = extra["monthly_limit"] or 0
    util = extra["utilization"] or 0

    out.append("  overage", style="bold bright_white")
    out.append(f"  ${used / 100:.2f}", style="bold")
    out.append(f" / ${limit / 100:.2f}", style="dim")
    out.append(f"  ({util:.0f}%)", style="bold")
    out.append("\n")

    frac = util / 100
    fill_color = pace_color(frac)
    filled = min(int(frac * bar_width), bar_width)
    out.append(" " * BAR_INDENT)
    for i in range(bar_width):
        if i < filled:
            out.append("█", style=fill_color)
        else:
            out.append("░", style="bright_black")
    out.append("\n\n")


def trailing_week(stats: StatsCache, window_end: datetime) -> list[DailyBreakdown]:
    """The 7 most recent days of the breakdown window ending at ``window_end``."""
    daily = get_daily_breakdown(stats, window_end - timedelta(days=7), window_end)
    # The 168-hour window can span 8 calendar dates; keep the 7 most recent
    if len(daily) > 7:
        daily = daily[1:]
    return daily


def render_daily_breakdown(
    out: Text,
    window_end: datetime,
    weekly_util: float,
    stats: StatsCache,
    bar_width: int,
) -> None:
    """Render the per-day cost-weighted breakdown over the trailing 7 days.

    The breakdown is built from the local stats cache, so it renders even
    when the live API exposes no weekly bucket. ``window_end`` anchors the
    7-day window (the weekly reset when known, otherwise now) and
    ``weekly_util`` scales the budget (0 falls back to raw token weighting).
    """
    resets_at = window_end
    window_start = resets_at - timedelta(days=7)
    now = datetime.now(resets_at.tzinfo)
    today = now.date()
    today_str = today.isoformat()

    daily = trailing_week(stats, resets_at)

    if not any(d.total_tokens > 0 for d in daily):
        return

    stale = bool(stats.last_computed_date and stats.last_computed_date < today_str)
    out.append("  per day", style="bold bright_white")
    if stale:
        out.append(f"  (cache: {stats.last_computed_date})", style="dim italic")
    out.append("\n")

    day_bar_w = bar_width

    cost_rates: dict[str, float] = {}  # lup: ignore[dict-str-payload, empty-collection]
    for mid, entry in stats.model_usage.items():
        total_tok = (
            entry.input_tokens
            + entry.output_tokens
            + entry.cache_read_input_tokens
            + entry.cache_creation_input_tokens
        )
        if total_tok > 0:
            cost_rates[mid] = entry.cost_usd / total_tok

    model_totals: dict[str, int] = {}  # lup: ignore[dict-str-payload, empty-collection]
    daily_weights: list[float] = []  # lup: ignore[empty-collection] — day fold
    for day in daily:
        weight = sum(
            tokens * cost_rates.get(model, 0)
            for model, tokens in day.tokens_by_model.items()
        )
        for model, tokens in day.tokens_by_model.items():
            model_totals[model] = model_totals.get(model, 0) + tokens
        daily_weights.append(weight)

    # Fall back to raw token counts when cost data is unavailable
    week_weight = sum(daily_weights)
    if not (cost_rates and week_weight > 0):
        daily_weights = [float(d.total_tokens) for d in daily]
        week_weight = sum(daily_weights)

    # Find today's index and estimate its weight when cache is stale
    today_idx: int | None = None
    estimated_today = False
    for i, day in enumerate(daily):
        if day.date == today_str:
            today_idx = i
            break

    if stale and today_idx is not None and daily_weights[today_idx] == 0:
        # Cache doesn't cover today — estimate from API utilization.
        # Assume usage rate is proportional to elapsed time to break
        # the circular dependency between budget and today's weight.
        elapsed_h = (now - window_start).total_seconds() / 3600
        cached_days_count = sum(
            1
            for day in daily
            if day.date <= stats.last_computed_date and day.total_tokens > 0
        )
        cached_h = cached_days_count * 24.0
        if cached_h > 0 and elapsed_h > cached_h and week_weight > 0:
            cached_frac = cached_h / elapsed_h
            today_weight = week_weight * (1 - cached_frac) / cached_frac
            daily_weights[today_idx] = today_weight
            # Estimate token count
            cached_tokens = sum(
                d.total_tokens for d in daily if d.date <= stats.last_computed_date
            )
            if cached_tokens > 0:
                est_tokens = int(cached_tokens * (1 - cached_frac) / cached_frac)
                daily[today_idx] = DailyBreakdown(
                    date=today_str,
                    total_tokens=est_tokens,
                    tokens_by_model={},  # lup: ignore[empty-collection] — estimate
                    activity=daily[today_idx].activity,
                )
            estimated_today = True

    week_weight = sum(daily_weights)
    if week_weight > 0 and weekly_util > 0:
        weekly_budget = week_weight / (weekly_util / 100)
    else:
        weekly_budget = max(week_weight, 1)

    # Rolling surplus budget: each day gets budget/7 plus leftover from prior days.
    # Heavy days eat into future budgets, light days bank surplus.
    even_daily = weekly_budget / 7
    surplus = 0.0
    daily_budgets: list[float] = []  # lup: ignore[empty-collection] — surplus fold
    for i, day in enumerate(daily):
        d = datetime.fromisoformat(day.date).date()
        budget = even_daily + surplus
        daily_budgets.append(budget)
        if d <= today:
            surplus = budget - daily_weights[i]

    for i, day in enumerate(daily):
        d = datetime.fromisoformat(day.date).date()
        day_name = DAY_NAMES[d.weekday()]

        if d == today:
            out.append(f"  {day_name}", style="bold bright_white")
            out.append(" ←  ", style="bold bright_cyan")
        elif d > today:
            out.append(f"  {day_name}    ", style="dim")
        else:
            out.append(f"  {day_name}    ", style="")

        if d > today:
            out.append("·" * day_bar_w, style="bright_black")
            out.append("\n")
            continue

        actual = daily_weights[i]
        budget = daily_budgets[i]
        fill_frac = actual / weekly_budget if weekly_budget > 0 else 0
        pace_frac = budget / weekly_budget if weekly_budget > 0 else 0
        fill_pos = min(int(fill_frac * day_bar_w), day_bar_w)
        pace_pos = min(max(int(pace_frac * day_bar_w), 0), day_bar_w - 1)
        ratio = actual / budget if budget > 0 else (2.0 if actual > 0 else 0)
        color = pace_color(ratio)
        is_est = i == today_idx and estimated_today
        fill_char = "▓" if is_est else "█"

        for j in range(day_bar_w):
            if j == pace_pos:
                out.append("▎", style="bright_black")
            elif j < fill_pos and j <= pace_pos:
                out.append(fill_char, style=color)
            elif j < fill_pos:
                out.append("▒", style=color)
            elif j < pace_pos:
                out.append("░", style="bright_black")
            else:
                out.append("░", style="black")

        tok_str = fmt_tokens(day.total_tokens)
        if is_est:
            out.append(f" ~{tok_str:>4}", style="bold dim")
        else:
            out.append(f" {tok_str:>5}", style="bold")
        if day.activity and day.activity.message_count > 0:
            out.append(f"  {day.activity.message_count:,}m", style="dim")
        out.append("\n")

    out.append("\n")

    model_token_total = sum(model_totals.values())
    if model_totals and model_token_total > 0:
        out.append("  models", style="bold bright_white")
        out.append("  ")
        for model, tokens in sorted(
            model_totals.items(), key=lambda x: x[1], reverse=True
        ):
            name = MODEL_NAMES.get(model, model)
            pct = tokens / model_token_total * 100
            out.append(f"● {name} ", style=model_color(model))
            out.append(f"{pct:.0f}%  ", style="dim")
        out.append("\n")


# ── display assembly ───────────────────────────────────────


class BreakdownWindow(NamedTuple):
    """The 7-day breakdown window's end and its budget-scaling utilization."""

    end: datetime
    utilization: float


def breakdown_window(usage: UsageResponse) -> BreakdownWindow:
    """Anchor the 7-day breakdown window and its budget-scaling utilization.

    The weekly API bucket gives the reset time and utilization when present;
    otherwise the window ends now and utilization is 0, so the breakdown
    still renders from the local stats cache with raw token weighting.
    """
    seven_day = get_bucket(usage, "seven_day")
    if seven_day and seven_day.get("resets_at"):
        return BreakdownWindow(
            datetime.fromisoformat(seven_day["resets_at"]), seven_day["utilization"]
        )
    return BreakdownWindow(datetime.now(), 0.0)


def build_display(
    usage: UsageResponse,
    stats: StatsCache | None,
    show_detail: bool,
    bar_width: int,
) -> Panel:
    # Common bar width so all bars are visually aligned.
    # Daily bars need room for prefix ("  Sa    " = 8) and suffix (" 400k" = 6).
    bar_w = bar_width - 14
    out = Text()

    for key, label, window_hours in BUCKET_SPECS:
        bucket = get_bucket(usage, key)
        if bucket and bucket.get("resets_at"):
            render_bucket(out, label, bucket, window_hours, bar_w)
            out.append("\n")

    extra = usage.get("extra_usage")
    if extra and extra["is_enabled"]:
        render_overage(out, extra, bar_w)

    if show_detail and stats:
        window_end, weekly_util = breakdown_window(usage)
        render_daily_breakdown(out, window_end, weekly_util, stats, bar_w)

    return Panel(
        out,
        title="[bold bright_white]Claude Code Usage[/bold bright_white]",
        border_style="bright_cyan",
        padding=(1, 1),
    )


def build_snapshot(usage: UsageResponse, stats: StatsCache | None) -> UsageSnapshot:
    """Assemble the machine-readable usage state for ``--json`` consumers.

    Mirrors the display: the same buckets, overage, and trailing-week
    breakdown, but as plain counts and limits an agent can read instead of
    the human pacing bars.
    """
    buckets: list[BucketSnapshot] = []  # lup: ignore[empty-collection] — spec fold
    for key, label, window_hours in BUCKET_SPECS:
        bucket = get_bucket(usage, key)
        if not (bucket and bucket.get("resets_at")):
            continue
        resets_at = datetime.fromisoformat(bucket["resets_at"])
        _, ratio = bucket_pace(bucket, window_hours)
        buckets.append(
            BucketSnapshot(
                name=label,
                utilization_pct=bucket["utilization"],
                pace=pace_label(ratio).word,
                resets_at=bucket["resets_at"],
                resets_in_seconds=max(
                    int((resets_at - datetime.now(resets_at.tzinfo)).total_seconds()), 0
                ),
            )
        )

    extra = usage.get("extra_usage")
    overage = (
        OverageSnapshot(
            enabled=extra["is_enabled"],
            used_usd=(extra["used_credits"] or 0) / 100,
            limit_usd=(extra["monthly_limit"] or 0) / 100,
            utilization_pct=extra["utilization"] or 0,
        )
        if extra
        else None
    )

    daily: list[DaySnapshot] = []  # lup: ignore[empty-collection] — window fold
    tally: dict[str, int] = {}  # lup: ignore[dict-str-payload, empty-collection]
    tokens_by_model = tally
    if stats:
        window_end, _ = breakdown_window(usage)
        for day in trailing_week(stats, window_end):
            daily.append(
                DaySnapshot(
                    date=day.date,
                    total_tokens=day.total_tokens,
                    tokens_by_model=day.tokens_by_model,
                    message_count=day.activity.message_count if day.activity else 0,
                )
            )
            for model, tokens in day.tokens_by_model.items():
                tokens_by_model[model] = tokens_by_model.get(model, 0) + tokens

    return UsageSnapshot(
        buckets=buckets,
        overage=overage,
        daily=daily,
        tokens_by_model=tokens_by_model,
        stats_cache_date=stats.last_computed_date if stats else None,
    )


def build_error_panel(message: str) -> Panel:
    out = Text()
    out.append(f"  {message}", style="red")
    out.append("\n  retrying...", style="dim")
    return Panel(
        out,
        title="[bold bright_white]Claude Code Usage[/bold bright_white]",
        border_style="red",
        padding=(1, 1),
    )
