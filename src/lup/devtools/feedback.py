"""Collect feedback data from agent sessions and view aggregate metrics.

This is a TEMPLATE script. Run `/lup:init` to customize it for your domain.

The script should:
1. Load session data from notes/sessions/
2. Match sessions to their outcomes/feedback
3. Compute aggregate metrics
4. Save results to notes/feedback_loop/

Examples::

    $ uv run lup-devtools feedback status
    $ uv run lup-devtools feedback collect --all-time
    $ uv run lup-devtools feedback tools
    $ uv run lup-devtools feedback errors
    $ uv run lup-devtools feedback version
    $ uv run lup-devtools feedback unanalyzed
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from lup.lib.history import iter_session_dirs, resolve_version
from lup.lib.paths import feedback_path, traces_path
from lup.version import AGENT_VERSION

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


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
    outcome: Any | None = None
    metrics: dict[str, Any] | None = None


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
) -> list[dict[str, Any]]:
    """Load session data, optionally filtered by version."""
    sessions: list[dict[str, Any]] = []

    for session_dir in iter_session_dirs(version=version):
        session_files = sorted(session_dir.glob("*.json"), reverse=True)
        if not session_files:
            continue

        try:
            data: dict[str, Any] = json.loads(session_files[0].read_text())
            data["_session_id"] = session_dir.name
            data["_file"] = str(session_files[0])

            if since and data.get("timestamp"):
                session_time = datetime.fromisoformat(data["timestamp"])
                if session_time < since:
                    continue

            sessions.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load session %s: %s", session_dir.name, e)

    return sessions


def load_outcomes() -> dict[str, Any]:
    """Load outcome data for sessions.

    Customize this to load outcomes for your domain.
    """
    return {}


def match_outcomes(sessions: list[dict[str, Any]]) -> list[SessionResult]:
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
# SHARED HELPERS
# =============================================================================


def load_sessions_for_versions(versions: list[str] | None) -> list[dict[str, Any]]:
    """Load sessions for a resolved version list (None = all)."""
    if versions is None:
        return load_sessions()
    results: list[dict[str, Any]] = []
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

ANALYZED_FILE = feedback_path() / "analyzed.json"


def load_analyzed() -> set[str]:
    """Load the set of already-analyzed session IDs."""
    if not ANALYZED_FILE.exists():
        return set()
    data: dict[str, list[str]] = json.loads(ANALYZED_FILE.read_text())
    return set(data.get("analyzed", []))


def save_analyzed(session_ids: set[str]) -> None:
    """Save the set of analyzed session IDs."""
    feedback_path().mkdir(parents=True, exist_ok=True)
    ANALYZED_FILE.write_text(
        json.dumps({"analyzed": sorted(session_ids)}, indent=2) + "\n"
    )


# =============================================================================
# CLI COMMANDS
# =============================================================================


@app.command("status")
def status(
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """Show feedback status: version, data, analysis state, and aggregate stats."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    # --- Agent Version ---
    typer.echo("\n=== Agent Version ===\n")
    typer.echo(f"Current: {AGENT_VERSION}")
    if effective:
        typer.echo(f"Showing: {', '.join(effective)}")

    # --- Data Availability ---
    typer.echo("\n=== Data Availability ===\n")

    all_session_ids = collect_session_ids(effective)
    session_count = len(all_session_ids)

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

    # --- Analysis State ---
    analyzed = load_analyzed()
    unanalyzed = sorted(all_session_ids - analyzed)

    typer.echo("\n=== Analysis State ===\n")
    typer.echo(f"Total sessions: {session_count}")
    typer.echo(f"Analyzed: {len(analyzed & all_session_ids)}")
    typer.echo(f"Unanalyzed: {len(unanalyzed)}")

    # --- Aggregate Stats ---
    sessions = load_sessions_for_versions(effective)

    if sessions:
        total = len(sessions)
        with_metrics = sum(1 for s in sessions if s.get("tool_metrics"))
        with_tokens = sum(1 for s in sessions if s.get("token_usage"))
        with_outcome = sum(1 for s in sessions if s.get("outcome") is not None)

        typer.echo(f"\n=== Aggregate Stats ({total} sessions) ===\n")
        typer.echo(
            f"With metrics: {with_metrics} ({100 * with_metrics / total:.0f}%)"
        )
        typer.echo(
            f"With tokens:  {with_tokens} ({100 * with_tokens / total:.0f}%)"
        )
        typer.echo(
            f"With outcome: {with_outcome} ({100 * with_outcome / total:.0f}%)"
        )

        total_cost = 0.0
        for s in sessions:
            cost = s.get("cost_usd") or s.get("tool_metrics", {}).get(
                "total_cost_usd", 0
            )
            if cost:
                total_cost += cost

        if total_cost > 0:
            typer.echo(f"\nTotal cost: ${total_cost:.2f}")
            typer.echo(f"Avg cost/session: ${total_cost / total:.4f}")

        total_input = 0
        total_output = 0
        for s in sessions:
            usage = s.get("token_usage", {})
            if usage:
                total_input += usage.get("input_tokens", 0) or 0
                total_output += usage.get("output_tokens", 0) or 0

        if total_input or total_output:
            typer.echo("\nTokens:")
            typer.echo(f"  Input:  {total_input:,}")
            typer.echo(f"  Output: {total_output:,}")
            typer.echo(f"  Total:  {total_input + total_output:,}")

    # --- Unanalyzed Session IDs ---
    if unanalyzed:
        typer.echo("\n=== Unanalyzed Sessions ===\n")
        for sid in unanalyzed[:20]:
            typer.echo(f"  {sid}")
        if len(unanalyzed) > 20:
            typer.echo(f"  ... and {len(unanalyzed) - 20} more")
        typer.echo(
            "\nTo list all unanalyzed IDs: uv run lup-devtools feedback unanalyzed"
        )


@app.command("collect")
def collect(
    since: Annotated[
        str | None,
        typer.Option(
            "--since", "-s", help="Only sessions after this date (YYYY-MM-DD)"
        ),
    ] = None,
    all_time: Annotated[
        bool,
        typer.Option("--all-time", help="Include all sessions regardless of date"),
    ] = False,
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path"),
    ] = None,
) -> None:
    """Collect feedback metrics from sessions."""
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
            if not s.get("timestamp")
            or datetime.fromisoformat(s["timestamp"]) >= since_dt
        ]
    logger.info("Found %d sessions", len(sessions))

    results = match_outcomes(sessions)
    feedback = compute_metrics(results)

    if output is None:
        feedback_path().mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output = feedback_path() / f"{timestamp}_metrics.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(feedback.model_dump_json(indent=2))
    logger.info("Saved metrics to %s", output)

    print("\n" + "=" * 60)
    print("FEEDBACK COLLECTION SUMMARY")
    print("=" * 60)
    print(f"Total sessions: {feedback.total_sessions}")
    print(f"Sessions with outcomes: {feedback.sessions_with_outcomes}")
    print(f"\nMetrics saved to: {output}")


@app.command("tools")
def tools(
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """Show tool usage aggregates."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        typer.echo("No sessions found")
        raise typer.Exit(1)

    tool_stats: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "total_ms": 0}
    )

    for s in sessions:
        metrics = s.get("tool_metrics", {})
        by_tool = metrics.get("by_tool", {})
        for tool_name, data in by_tool.items():
            tool_stats[tool_name]["calls"] += data.get("call_count", 0)
            tool_stats[tool_name]["errors"] += data.get("error_count", 0)
            avg_ms = data.get("avg_duration_ms", 0)
            count = data.get("call_count", 0)
            tool_stats[tool_name]["total_ms"] += avg_ms * count

    if not tool_stats:
        typer.echo("No tool metrics found")
        return

    typer.echo("\n=== Tool Usage Summary ===\n")
    typer.echo(
        f"{'Tool':<35} {'Calls':>8} {'Errors':>8} {'Err%':>8} {'Avg ms':>10}"
    )
    typer.echo("-" * 75)

    for tool_name in sorted(tool_stats.keys(), key=lambda t: -tool_stats[t]["calls"]):
        stats = tool_stats[tool_name]
        calls = int(stats["calls"])
        errs = int(stats["errors"])
        err_pct = (100 * errs / calls) if calls > 0 else 0
        avg_ms = stats["total_ms"] / calls if calls > 0 else 0
        err_indicator = " !" if err_pct > 10 else ""
        typer.echo(
            f"{tool_name:<35} {calls:>8} {errs:>8} {err_pct:>7.1f}%{err_indicator} {avg_ms:>9.0f}"
        )


@app.command("errors")
def errors(
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Max sessions to show"),
    ] = 20,
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """Show sessions with high error rates."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        typer.echo("No sessions found")
        raise typer.Exit(1)

    with_errors: list[dict[str, Any]] = []
    for s in sessions:
        metrics = s.get("tool_metrics", {})
        total_errors = metrics.get("total_errors", 0)
        if total_errors and total_errors > 0:
            with_errors.append(
                {
                    "session_id": s.get("_session_id"),
                    "errors": total_errors,
                    "by_tool": metrics.get("by_tool", {}),
                }
            )

    if not with_errors:
        typer.echo("No sessions with errors found")
        return

    with_errors.sort(key=lambda x: -x["errors"])

    typer.echo(f"\n=== Sessions with Errors ({len(with_errors)} total) ===\n")

    for item in with_errors[:limit]:
        typer.echo(f"Session {item['session_id']}: {item['errors']} errors")
        for tool_name, tool_data in item["by_tool"].items():
            errs = tool_data.get("error_count", 0)
            if errs > 0:
                typer.echo(f"  - {tool_name}: {errs}")


@app.command("trends")
def trends(
    window: Annotated[
        int,
        typer.Option("-w", "--window", help="Rolling window size"),
    ] = 10,
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """Show metric trends over time."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    sessions = load_sessions_for_versions(effective)
    if not sessions:
        typer.echo("No sessions found")
        raise typer.Exit(1)

    sessions_with_ts = [s for s in sessions if s.get("timestamp")]
    sessions_with_ts.sort(key=lambda x: x["timestamp"])

    if len(sessions_with_ts) < window:
        typer.echo(f"Need at least {window} sessions for trend analysis")
        typer.echo(f"Have: {len(sessions_with_ts)}")
        return

    typer.echo(f"\n=== Trends (rolling {window}-session window) ===\n")

    for i in range(window - 1, len(sessions_with_ts)):
        window_sessions = sessions_with_ts[i - window + 1 : i + 1]

        total_calls = sum(
            s.get("tool_metrics", {}).get("total_tool_calls", 0)
            for s in window_sessions
        )
        avg_calls = total_calls / window

        total_errors = sum(
            s.get("tool_metrics", {}).get("total_errors", 0) for s in window_sessions
        )
        error_rate = total_errors / max(1, total_calls)

        total_cost = sum(s.get("cost_usd", 0) or 0 for s in window_sessions)
        avg_cost = total_cost / window

        latest_ts = window_sessions[-1].get("timestamp", "")[:10]
        typer.echo(
            f"{latest_ts}: calls={avg_calls:.1f}/session, "
            f"errors={error_rate:.1%}, cost=${avg_cost:.4f}/session"
        )


@app.command("history")
def history(
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Max to show"),
    ] = 10,
) -> None:
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
            data = json.loads(f.read_text())
            total = data.get("total_sessions", 0)
            with_outcomes = data.get("sessions_with_outcomes", 0)
            typer.echo(f"{f.name}: {total} sessions, {with_outcomes} with outcomes")
        except (json.JSONDecodeError, OSError):
            typer.echo(f"{f.name}: (error reading)")


@app.command("mark")
def mark(
    session_ids: Annotated[
        list[str], typer.Argument(help="Session IDs to mark as analyzed")
    ],
) -> None:
    """Mark sessions as analyzed in the feedback loop."""
    analyzed = load_analyzed()
    new_ids = set(session_ids) - analyzed
    if not new_ids:
        typer.echo("All specified sessions already marked")
        return
    analyzed.update(new_ids)
    save_analyzed(analyzed)
    typer.echo(f"Marked {len(new_ids)} sessions as analyzed")


@app.command("unmark")
def unmark(
    session_ids: Annotated[
        list[str], typer.Argument(help="Session IDs to unmark")
    ],
) -> None:
    """Remove analysis marks from sessions."""
    analyzed = load_analyzed()
    removed = analyzed & set(session_ids)
    if not removed:
        typer.echo("None of the specified sessions were marked")
        return
    analyzed -= removed
    save_analyzed(analyzed)
    typer.echo(f"Unmarked {len(removed)} sessions")


@app.command("prompt-health")
def prompt_health() -> None:
    """Analyze the agent prompt for size and patch accumulation."""
    matches = glob("src/*/agent/prompts.py")
    if not matches:
        typer.echo("No prompts.py found matching src/*/agent/prompts.py")
        raise typer.Exit(1)

    prompts_file = Path(matches[0])
    content = prompts_file.read_text()
    lines = content.split("\n")

    section_count = sum(1 for line in lines if "## " in line or "### " in line)

    print("\n=== Prompt Health ===\n")
    print(f"File: {prompts_file}")
    print(f"Total lines: {len(lines)}")
    print(f"Sections: ~{section_count}")


@app.command("version")
def version_cmd() -> None:
    """Print the current agent version."""
    typer.echo(AGENT_VERSION)


@app.command("unanalyzed")
def unanalyzed(
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """List unanalyzed session IDs, one per line."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    all_session_ids = collect_session_ids(effective)
    analyzed = load_analyzed()

    for sid in sorted(all_session_ids - analyzed):
        typer.echo(sid)
