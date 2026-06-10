"""Feedback state: collection, analysis marks, status, and commit operations.

This is a TEMPLATE script. Run ``/lup:init`` to customize it for your domain.

Examples::

    $ uv run lup-devtools feedback status
    $ uv run lup-devtools feedback collect --all-time
    $ uv run lup-devtools feedback commit --dry-run
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

import sh
import typer
from pydantic import BaseModel

from lup.history import iter_session_dirs, resolve_version
from lup.paths import feedback_path, project_root, traces_path, AGENT_VERSION
from lup_template.devtools.utils import git, output_json

logger = logging.getLogger(__name__)


# =============================================================================
# SESSION JSON TYPES
# =============================================================================


class ToolData(TypedDict, total=False):
    call_count: int
    error_count: int
    avg_duration_ms: float
    total_cost_usd: float


class ToolMetrics(TypedDict, total=False):
    total_tool_calls: int
    total_errors: int
    total_cost_usd: float
    by_tool: dict[str, ToolData]


class TokenUsage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int


class SessionData(TypedDict, total=False):
    """Raw session JSON loaded from disk."""

    timestamp: str
    outcome: object
    tool_metrics: ToolMetrics
    token_usage: TokenUsage
    cost_usd: float
    output: dict[str, str]
    _session_id: str
    _file: str


# =============================================================================
# CUSTOMIZE THESE MODELS FOR YOUR DOMAIN
# =============================================================================


class SessionResult(BaseModel):
    """A session matched with its outcome/feedback.

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
    outcome: object | None = None
    metrics: ToolMetrics | None = None


class FeedbackMetrics(BaseModel):
    """Aggregated metrics from sessions.

    Customize this for your domain.
    """

    collection_timestamp: str
    since_timestamp: str | None = None
    total_sessions: int
    sessions_with_outcomes: int
    results: list[SessionResult] = []


# =============================================================================
# CUSTOMIZE THESE FUNCTIONS FOR YOUR DOMAIN
# =============================================================================


def load_sessions(
    since: datetime | None = None, version: str | None = None
) -> list[SessionData]:
    """Load session data, optionally filtered by version."""
    sessions: list[SessionData] = []

    for session_dir in iter_session_dirs(version=version):
        session_files = sorted(session_dir.glob("*.json"), reverse=True)
        if not session_files:
            continue

        try:
            data = cast(SessionData, json.loads(session_files[0].read_text()))
            data["_session_id"] = session_dir.name
            data["_file"] = str(session_files[0])

            ts = data.get("timestamp")
            if since and ts:
                session_time = datetime.fromisoformat(ts)
                if session_time < since:
                    continue

            sessions.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load session %s: %s", session_dir.name, e)

    return sessions


def load_outcomes() -> dict[str, object]:
    """Load outcome data for sessions.

    Customize this to load outcomes for your domain.
    """
    return {}


def match_outcomes(
    sessions: list[SessionData],
) -> list[SessionResult]:
    """Match sessions to their outcomes/feedback."""
    outcomes = load_outcomes()
    results = []

    for session in sessions:
        session_id = session.get("_session_id", "")
        timestamp = session.get("timestamp", "")

        outcome_data = outcomes.get(session_id)

        result = SessionResult(
            session_id=session_id,
            timestamp=timestamp,
            outcome=outcome_data,
            metrics=session.get("tool_metrics"),
        )
        results.append(result)

    return results


def compute_metrics(results: list[SessionResult]) -> FeedbackMetrics:
    """Compute aggregate metrics from session results."""
    sessions_with_outcomes = sum(1 for r in results if r.outcome is not None)

    return FeedbackMetrics(
        collection_timestamp=datetime.now().isoformat(),
        total_sessions=len(results),
        sessions_with_outcomes=sessions_with_outcomes,
        results=results,
    )


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
    by_tool: dict[str, ToolData]


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


# =============================================================================
# SHARED HELPERS
# =============================================================================


def load_sessions_for_versions(
    versions: list[str] | None,
) -> list[SessionData]:
    """Load sessions for a resolved version list (None = all)."""
    if versions is None:
        return load_sessions()
    results: list[SessionData] = []
    for v in versions:
        results.extend(load_sessions(version=v))
    return results


def collect_session_ids(effective: list[str] | None) -> set[str]:
    """Collect all session IDs for the given version list."""
    all_session_ids: set[str] = set()
    if effective:
        for v in effective:
            for d in iter_session_dirs(version=v):
                all_session_ids.add(d.name)
    else:
        for d in iter_session_dirs():
            all_session_ids.add(d.name)
    return all_session_ids


# =============================================================================
# ANALYSIS STATE TRACKING
# =============================================================================


def analyzed_file() -> Path:
    """Return path to the analyzed sessions tracking file."""
    return feedback_path() / "analyzed.json"


def load_analyzed() -> set[str]:
    """Load the set of already-analyzed session IDs."""
    path = analyzed_file()
    if not path.exists():
        return set()
    data: dict[str, list[str]] = json.loads(path.read_text())
    return set(data.get("analyzed", []))


def save_analyzed(session_ids: set[str]) -> None:
    """Save the set of analyzed session IDs."""
    feedback_path().mkdir(parents=True, exist_ok=True)
    analyzed_file().write_text(
        json.dumps({"analyzed": sorted(session_ids)}, indent=2) + "\n"
    )


# =============================================================================
# SESSION COMMIT OPERATIONS
# =============================================================================


def get_uncommitted_session_ids() -> set[str]:
    """Find session IDs with uncommitted result files.

    Parses ``git status --porcelain -z``: NUL-separated entries are never
    quoted, so paths containing spaces survive intact. Rename and copy
    entries carry the origin path as an extra NUL-separated field.
    """
    session_ids: set[str] = set()

    status = str(git.status("--porcelain", "-z", "--", "notes/", _ok_code=[0]))
    entries = status.split("\0")  # claude: ignore

    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        file_path = entry[3:]
        if "R" in code or "C" in code:
            index += 1  # skip the rename/copy origin path that follows

        parts = Path(file_path).parts
        if (
            len(parts) >= 5
            and parts[0] == "notes"
            and parts[1] == "traces"
            and parts[3] in ("sessions", "logs")
        ):
            session_ids.add(parts[4])

    return session_ids


def get_session_summary(session_id: str) -> str:
    """Read summary from the latest session JSON across all versions."""
    all_json: list[Path] = []
    for session_dir in iter_session_dirs(session_id=session_id):
        all_json.extend(session_dir.glob("*.json"))

    if not all_json:
        return f"session {session_id}"

    latest = sorted(all_json)[-1]
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            output = raw.get("output", {})
            if isinstance(output, dict):
                summary = output.get("summary")
                if isinstance(summary, str):
                    return summary[:50]
        return f"session {session_id}"
    except (json.JSONDecodeError, OSError):
        return f"session {session_id}"


def commit_session(session_id: str, *, dry_run: bool = False) -> bool:
    """Stage and commit files for a single session ID."""
    paths: list[str] = []

    for session_dir in iter_session_dirs(session_id=session_id):
        paths.append(str(session_dir))

    if traces_path().exists():
        for ver_dir in traces_path().iterdir():
            if not ver_dir.is_dir():
                continue
            log_dir = ver_dir / "logs" / session_id
            if log_dir.exists():
                paths.append(str(log_dir))

    if not paths:
        return False

    if dry_run:
        summary = get_session_summary(session_id)
        typer.echo(f"  Would commit {session_id}: {summary}")
        for p in paths:
            typer.echo(f"    {p}")
        return True

    for path in paths:
        try:
            git.add(path)
        except sh.ErrorReturnCode as e:
            logger.warning("Failed to stage %s: %s", path, e)

    diff = str(git.diff("--cached", "--stat", _ok_code=[0, 1])).strip()
    if not diff:
        return False

    summary = get_session_summary(session_id)
    slug = summary[:50].strip().rstrip(".")
    git.commit("-m", f"data(sessions): {slug}")
    typer.echo(f"  Committed {session_id}: {slug}")
    return True


# =============================================================================
# CLI COMMANDS
# =============================================================================


def print_version_info(effective: list[str] | None) -> None:
    typer.echo("\n=== Agent Version ===\n")
    typer.echo(f"Current: {AGENT_VERSION}")
    if effective:
        typer.echo(f"Showing: {', '.join(effective)}")


def print_data_availability(effective: list[str] | None, session_count: int) -> None:
    typer.echo("\n=== Data Availability ===\n")

    if effective:
        typer.echo(f"Sessions: {session_count} (versions: {effective})")
    else:
        typer.echo(f"Sessions: {session_count} (all versions in {traces_path()})")

    if traces_path().exists():
        version_count = sum(1 for d in traces_path().iterdir() if d.is_dir())
        typer.echo(f"Versions: {version_count} in {traces_path()}")
    else:
        typer.echo(f"Traces: No directory at {traces_path()}")

    if feedback_path().exists():
        feedback_files = list(feedback_path().glob("*_metrics.json"))
        typer.echo(f"Previous feedback collections: {len(feedback_files)}")
        if feedback_files:
            latest = sorted(feedback_files)[-1]
            typer.echo(f"  Latest: {latest.name}")
    else:
        typer.echo("Previous feedback collections: None")


def print_aggregate_stats(sessions: list[SessionData]) -> None:
    total = len(sessions)
    with_metrics = sum(1 for s in sessions if s.get("tool_metrics"))
    with_tokens = sum(1 for s in sessions if s.get("token_usage"))
    with_outcome = sum(1 for s in sessions if s.get("outcome") is not None)

    typer.echo(f"\n=== Aggregate Stats ({total} sessions) ===\n")
    typer.echo(f"With metrics: {with_metrics} ({100 * with_metrics / total:.0f}%)")
    typer.echo(f"With tokens:  {with_tokens} ({100 * with_tokens / total:.0f}%)")
    typer.echo(f"With outcome: {with_outcome} ({100 * with_outcome / total:.0f}%)")

    total_cost = 0.0
    for s in sessions:
        cost = s.get("cost_usd") or 0
        if not cost:
            metrics = s.get("tool_metrics")
            if metrics:
                cost = metrics.get("total_cost_usd", 0) or 0
        if cost:
            total_cost += cost

    if total_cost > 0:
        typer.echo(f"\nTotal cost: ${total_cost:.2f}")
        typer.echo(f"Avg cost/session: ${total_cost / total:.4f}")

    total_input = 0
    total_output = 0
    for s in sessions:
        usage = s.get("token_usage")
        if usage:
            total_input += usage.get("input_tokens", 0) or 0
            total_output += usage.get("output_tokens", 0) or 0

    if total_input or total_output:
        typer.echo("\nTokens:")
        typer.echo(f"  Input:  {total_input:,}")
        typer.echo(f"  Output: {total_output:,}")
        typer.echo(f"  Total:  {total_input + total_output:,}")


def status(
    version: str | None,
    all_versions: bool,
) -> None:
    """Show feedback status: version, data, analysis state, and aggregate stats."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    print_version_info(effective)

    all_session_ids = collect_session_ids(effective)
    session_count = len(all_session_ids)

    print_data_availability(effective, session_count)

    analyzed = load_analyzed()
    unanalyzed_ids = sorted(all_session_ids - analyzed)

    typer.echo("\n=== Analysis State ===\n")
    typer.echo(f"Total sessions: {session_count}")
    typer.echo(f"Analyzed: {len(analyzed & all_session_ids)}")
    typer.echo(f"Unanalyzed: {len(unanalyzed_ids)}")

    sessions = load_sessions_for_versions(effective)

    if sessions:
        print_aggregate_stats(sessions)

    if unanalyzed_ids:
        typer.echo("\n=== Unanalyzed Sessions ===\n")
        for sid in unanalyzed_ids[:20]:
            typer.echo(f"  {sid}")
        if len(unanalyzed_ids) > 20:
            typer.echo(f"  ... and {len(unanalyzed_ids) - 20} more")
        typer.echo(
            "\nTo list all unanalyzed IDs: uv run lup-devtools feedback unanalyzed"
        )


def collect(
    since: str | None,
    all_time: bool,
    version: str | None,
    all_versions: bool,
    output: Path | None,
    *,
    dry_run: bool = False,
) -> None:
    """Collect feedback metrics from sessions."""
    if since and all_time:
        typer.echo("Error: --since and --all-time are mutually exclusive", err=True)
        raise typer.Exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    since_dt: datetime | None = None
    if not all_time and since:
        since_dt = datetime.fromisoformat(since)

    logger.info(
        "Collecting feedback since %s",
        since_dt.isoformat() if since_dt else "all time",
    )

    sessions = load_sessions_for_versions(effective)
    if since_dt:
        sessions = [
            s
            for s in sessions
            if not (ts := s.get("timestamp")) or datetime.fromisoformat(ts) >= since_dt
        ]

    if not sessions:
        typer.echo("No sessions found. Nothing to collect.")
        typer.echo(
            "Run agent sessions first: "
            'uv run python -m lup_template.environment.cli run "task"'
        )
        return

    logger.info("Found %d sessions", len(sessions))

    results = match_outcomes(sessions)
    feedback = compute_metrics(results)

    typer.echo("\n" + "=" * 60)
    typer.echo("FEEDBACK COLLECTION SUMMARY")
    typer.echo("=" * 60)
    typer.echo(f"Total sessions: {feedback.total_sessions}")
    typer.echo(f"Sessions with outcomes: {feedback.sessions_with_outcomes}")

    if dry_run:
        typer.echo("\n(dry run — no files written)")
        return

    if output is None:
        feedback_path().mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output = feedback_path() / f"{timestamp}_metrics.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(feedback.model_dump_json(indent=2))
    typer.echo(f"\nMetrics saved to: {output}")


def tools(version: str | None, all_versions: bool, as_json: bool) -> None:
    """Show tool usage aggregates."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        if as_json:
            output_json([])
        else:
            typer.echo("No sessions found")
        return

    tool_stats: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "total_ms": 0}
    )

    for s in sessions:
        metrics = s.get("tool_metrics")
        if not metrics:
            continue
        by_tool = metrics.get("by_tool", {})
        for tool_name, data in by_tool.items():
            tool_stats[tool_name]["calls"] += data.get("call_count", 0)
            tool_stats[tool_name]["errors"] += data.get("error_count", 0)
            avg_ms = data.get("avg_duration_ms", 0) or 0
            count = data.get("call_count", 0)
            tool_stats[tool_name]["total_ms"] += avg_ms * count

    if not tool_stats:
        if as_json:
            output_json([])
        else:
            typer.echo("No tool metrics found")
        return

    entries: list[ToolUsageEntry] = []
    for tool_name in sorted(tool_stats.keys(), key=lambda t: -tool_stats[t]["calls"]):
        stats = tool_stats[tool_name]
        calls = int(stats["calls"])
        errs = int(stats["errors"])
        entries.append(
            {
                "name": tool_name,
                "calls": calls,
                "errors": errs,
                "error_rate": (errs / calls) if calls > 0 else 0.0,
                "avg_ms": stats["total_ms"] / calls if calls > 0 else 0.0,
            }
        )

    if as_json:
        output_json(entries)
        return

    typer.echo("\n=== Tool Usage Summary ===\n")
    typer.echo(f"{'Tool':<35} {'Calls':>8} {'Errors':>8} {'Err%':>8} {'Avg ms':>10}")
    typer.echo("-" * 75)

    for e in entries:
        err_pct = e["error_rate"] * 100
        err_indicator = " !" if err_pct > 10 else ""
        typer.echo(
            f"{e['name']:<35} {e['calls']:>8} {e['errors']:>8} "
            f"{err_pct:>7.1f}%{err_indicator} {e['avg_ms']:>9.0f}"
        )


def errors(
    limit: int,
    version: str | None,
    all_versions: bool,
    as_json: bool,
) -> None:
    """Show sessions with high error rates from structured metrics."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        if as_json:
            output_json([])
        else:
            typer.echo("No sessions found")
        return

    with_errors: list[ErrorSessionEntry] = []
    for s in sessions:
        metrics = s.get("tool_metrics")
        if not metrics:
            continue
        total_errors = metrics.get("total_errors", 0)
        if total_errors and total_errors > 0:
            with_errors.append(
                {
                    "session_id": s.get("_session_id", ""),
                    "errors": total_errors,
                    "by_tool": metrics.get("by_tool", {}),
                }
            )

    if not with_errors:
        if as_json:
            output_json([])
        else:
            typer.echo("No sessions with errors found")
        return

    with_errors.sort(key=lambda x: -x["errors"])

    if as_json:
        output_json(with_errors[:limit])
        return

    typer.echo(f"\n=== Sessions with Errors ({len(with_errors)} total) ===\n")

    for item in with_errors[:limit]:
        typer.echo(f"Session {item['session_id']}: {item['errors']} errors")
        for tool_name, tool_data in item["by_tool"].items():
            errs = tool_data.get("error_count", 0)
            if errs and int(errs) > 0:
                typer.echo(f"  - {tool_name}: {errs}")


def trends(window: int, version: str | None, all_versions: bool, as_json: bool) -> None:
    """Show metric trends over time."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        if as_json:
            output_json([])
        else:
            typer.echo("No sessions found")
        return

    sessions_with_ts = [s for s in sessions if s.get("timestamp")]
    sessions_with_ts.sort(key=lambda s: s.get("timestamp", ""))

    if len(sessions_with_ts) < window:
        if as_json:
            output_json([])
        else:
            typer.echo(f"Need at least {window} sessions for trend analysis")
            typer.echo(f"Have: {len(sessions_with_ts)}")
        return

    entries: list[TrendEntry] = []
    for i in range(window - 1, len(sessions_with_ts)):
        window_sessions = sessions_with_ts[i - window + 1 : i + 1]

        total_calls = 0
        total_errs = 0
        for ws in window_sessions:
            m = ws.get("tool_metrics")
            if m:
                total_calls += m.get("total_tool_calls", 0) or 0
                total_errs += m.get("total_errors", 0) or 0
        avg_calls = total_calls / window
        error_rate = total_errs / max(1, total_calls)

        total_cost = sum(s.get("cost_usd", 0) or 0 for s in window_sessions)
        avg_cost = total_cost / window

        latest_ts = window_sessions[-1].get("timestamp", "")[:10]
        entries.append(
            {
                "date": latest_ts,
                "avg_calls": round(avg_calls, 1),
                "error_rate": round(error_rate, 4),
                "avg_cost": round(avg_cost, 4),
            }
        )

    if as_json:
        output_json(entries)
        return

    typer.echo(f"\n=== Trends (rolling {window}-session window) ===\n")
    for e in entries:
        typer.echo(
            f"{e['date']}: calls={e['avg_calls']:.1f}/session, "
            f"errors={e['error_rate']:.1%}, cost=${e['avg_cost']:.4f}/session"
        )


def history(limit: int) -> None:
    """Show previous feedback collection runs."""
    if not feedback_path().exists():
        typer.echo("No feedback history found")
        return

    metrics_files = sorted(feedback_path().glob("*_metrics.json"), reverse=True)
    if not metrics_files:
        typer.echo("No metrics files found")
        return

    typer.echo("\n=== Feedback Collection History ===\n")

    for f in metrics_files[:limit]:
        try:
            raw = json.loads(f.read_text())
            if isinstance(raw, dict):
                total = raw.get("total_sessions", 0)
                with_outcomes = raw.get("sessions_with_outcomes", 0)
                typer.echo(f"{f.name}: {total} sessions, {with_outcomes} with outcomes")
            else:
                typer.echo(f"{f.name}: (unexpected format)")
        except (json.JSONDecodeError, OSError):
            typer.echo(f"{f.name}: (error reading)")


def mark(session_ids: list[str]) -> None:
    """Mark sessions as analyzed in the feedback loop."""
    analyzed = load_analyzed()
    new_ids = set(session_ids) - analyzed
    if not new_ids:
        typer.echo("All specified sessions already marked")
        return
    analyzed.update(new_ids)
    save_analyzed(analyzed)
    typer.echo(f"Marked {len(new_ids)} sessions as analyzed")


def unmark(session_ids: list[str]) -> None:
    """Remove analysis marks from sessions."""
    analyzed = load_analyzed()
    removed = analyzed & set(session_ids)
    if not removed:
        typer.echo("None of the specified sessions were marked")
        return
    analyzed -= removed
    save_analyzed(analyzed)
    typer.echo(f"Unmarked {len(removed)} sessions")


def prompt_health(as_json: bool) -> None:
    """Analyze the agent prompt structure and size.

    Renders the prompt via get_system_prompt() and analyzes the actual
    output — not the source file. Breaks down by named section.
    """
    from lup_template.agent.prompts import SECTIONS, get_system_prompt

    prompts_candidates = sorted(project_root().glob("src/*/agent/prompts.py"))
    prompts_file = prompts_candidates[0] if prompts_candidates else None
    rendered = get_system_prompt()
    char_count = len(rendered)
    estimated_tokens = char_count // 4

    section_reports: list[PromptSection] = []
    for section_text in SECTIONS:
        first_line = (
            section_text.strip().splitlines()[0] if section_text.strip() else "(empty)"
        )
        section_reports.append(
            {
                "name": first_line[:60],
                "lines": len(section_text.splitlines()),
                "characters": len(section_text),
            }
        )

    report: PromptHealthReport = {
        "file": str(prompts_file) if prompts_file else "unknown",
        "rendered_characters": char_count,
        "estimated_tokens": estimated_tokens,
        "sections": section_reports,
    }

    if as_json:
        output_json(report)
        return

    typer.echo("\n=== Prompt Health ===\n")
    if prompts_file:
        typer.echo(f"File: {prompts_file}")
    typer.echo(f"Rendered: {char_count:,} chars (~{estimated_tokens:,} tokens)")
    typer.echo(f"Sections: {len(section_reports)}")

    typer.echo(f"\n{'Section':<50} {'Lines':>6} {'Chars':>8}")
    typer.echo("-" * 68)
    for s in section_reports:
        typer.echo(f"{s['name']:<50} {s['lines']:>6} {s['characters']:>8}")


def unanalyzed(version: str | None, all_versions: bool) -> None:
    """List unanalyzed session IDs, one per line."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    all_session_ids = collect_session_ids(effective)
    analyzed = load_analyzed()

    for sid in sorted(all_session_ids - analyzed):
        typer.echo(sid)


def commit(dry_run: bool) -> None:
    """Commit all uncommitted session result files, one commit per session."""
    session_ids = get_uncommitted_session_ids()

    if not session_ids:
        typer.echo("Nothing to commit.")
        return

    typer.echo(f"Found {len(session_ids)} session(s) with uncommitted files")

    committed = 0
    for session_id in sorted(session_ids):
        try:
            if commit_session(session_id, dry_run=dry_run):
                committed += 1
        except sh.ErrorReturnCode as e:
            typer.echo(f"  Failed {session_id}: {e}", err=True)

    if dry_run:
        typer.echo(f"\nWould commit {committed} session(s)")
    else:
        typer.echo(f"\nCommitted {committed} session(s)")
