"""Collect feedback data from agent sessions.

This is a TEMPLATE script. Run `/lup:init` to customize it for your domain.

The script should:
1. Load session data from notes/sessions/
2. Match sessions to their outcomes/feedback
3. Compute aggregate metrics
4. Save results to notes/feedback_loop/

Examples::

    $ uv run lup-devtools feedback collect
    $ uv run lup-devtools feedback collect --all-time
    $ uv run lup-devtools feedback collect --since 2026-01-01
    $ uv run lup-devtools feedback collect --all-versions -o results.json
    $ uv run lup-devtools feedback check
    $ uv run lup-devtools feedback check --all-versions
"""

import json
import logging
from datetime import datetime
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
# CLI COMMANDS
# =============================================================================


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

    sessions: list[dict[str, Any]] = []
    if effective is None:
        sessions = load_sessions(since_dt)
    else:
        for v in effective:
            sessions.extend(load_sessions(since_dt, version=v))
    logger.info("Found %d sessions", len(sessions))

    results = match_outcomes(sessions)
    metrics = compute_metrics(results)

    if output is None:
        feedback_path().mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output = feedback_path() / f"{timestamp}_metrics.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(metrics.model_dump_json(indent=2))
    logger.info("Saved metrics to %s", output)

    print("\n" + "=" * 60)
    print("FEEDBACK COLLECTION SUMMARY")
    print("=" * 60)
    print(f"Total sessions: {metrics.total_sessions}")
    print(f"Sessions with outcomes: {metrics.sessions_with_outcomes}")
    print(f"\nMetrics saved to: {output}")


@app.command("check")
def check(
    version: Annotated[
        str | None,
        typer.Option("--version", "-v", help="Agent version (default: current)"),
    ] = AGENT_VERSION,
    all_versions: Annotated[
        bool,
        typer.Option("--all-versions", help="Include all versions"),
    ] = False,
) -> None:
    """Check what data is available for feedback collection."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    print("\n=== Feedback Data Check ===\n")

    if effective:
        session_count = sum(
            sum(1 for _ in iter_session_dirs(version=v)) for v in effective
        )
        print(f"Sessions: {session_count} (versions: {effective})")
    else:
        session_count = sum(1 for _ in iter_session_dirs())
        print(f"Sessions: {session_count} (all versions in {traces_path()})")

    if traces_path().exists():
        version_count = sum(1 for d in traces_path().iterdir() if d.is_dir())
        print(f"Versions: {version_count} in {traces_path()}")
    else:
        print(f"Traces: No directory at {traces_path()}")

    if feedback_path().exists():
        feedback_files = list(feedback_path().glob("*_metrics.json"))
        print(f"Previous feedback collections: {len(feedback_files)}")
        if feedback_files:
            latest = sorted(feedback_files)[-1]
            print(f"  Latest: {latest.name}")
    else:
        print("Previous feedback collections: None")

    print("\nTo collect feedback, run:")
    print("  uv run lup-devtools feedback collect")


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
    """Show analysis state: which sessions have been analyzed."""
    effective, ver_warning = resolve_version(version, all_versions)
    if ver_warning:
        typer.echo(ver_warning)

    analyzed = load_analyzed()

    all_session_ids: set[str] = set()
    if effective:
        for v in effective:
            for d in iter_session_dirs(version=v):
                all_session_ids.add(d.name)
    else:
        for d in iter_session_dirs():
            all_session_ids.add(d.name)

    unanalyzed = sorted(all_session_ids - analyzed)

    print("\n=== Analysis Status ===\n")
    print(f"Total sessions: {len(all_session_ids)}")
    print(f"Analyzed: {len(analyzed & all_session_ids)}")
    print(f"Unanalyzed: {len(unanalyzed)}")

    if unanalyzed:
        preview = ", ".join(unanalyzed[:10])
        print(f"\nUnanalyzed: {preview}")
        if len(unanalyzed) > 10:
            print(f"  ... and {len(unanalyzed) - 10} more")


# =============================================================================
# PROMPT HEALTH
# =============================================================================


@app.command("prompt-health")
def prompt_health() -> None:
    """Analyze the agent prompt for size and patch accumulation."""
    prompts_file = Path("src/lup/agent/prompts.py")
    if not prompts_file.exists():
        typer.echo("prompts.py not found")
        raise typer.Exit(1)

    content = prompts_file.read_text()
    lines = content.split("\n")

    section_count = sum(1 for line in lines if "## " in line or "### " in line)

    print("\n=== Prompt Health ===\n")
    print(f"File: {prompts_file}")
    print(f"Total lines: {len(lines)}")
    print(f"Sections: ~{section_count}")
