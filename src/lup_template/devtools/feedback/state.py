# lup: ignore[dict-get]
# The loaders probe SessionData payloads whose keys are all optional, so
# dict-get is opted out file-wide (mirrors reports.py).
"""Feedback state: session loading, outcome matching, and analysis marks.

This is a TEMPLATE script. Run ``/lup:init`` to customize it for your domain.
The data shapes live in ``models``, aggregation in ``metrics``, git commits
in ``commits``, and the CLI command bodies in ``reports``.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import cast

import typer

from lup.types import JsonValue
from lup.workspace.history import iter_session_dirs, list_all_session_ids
from lup.workspace.paths import feedback_path
from lup_template.devtools.feedback.models import SessionData, SessionResult

logger = logging.getLogger(__name__)


def load_sessions(
    since: datetime | None = None, version: str | None = None
) -> list[SessionData]:
    """Load session data, optionally filtered by version."""
    sessions: list[SessionData] = []  # lup: ignore[empty-collection] — tolerant fold

    for session_dir in iter_session_dirs(version=version):
        session_files = sorted(session_dir.glob("*.json"), reverse=True)
        if not session_files:
            continue

        try:
            raw = json.loads(session_files[0].read_text())
            data = cast(SessionData, raw)  # lup: ignore[cast] — TypedDict from JSON
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


def load_outcomes() -> dict[str, JsonValue]:
    """Load outcome data for sessions.

    TEMPLATE: implement your domain's outcome loading (customization step 9).
    This stub raises so callers can tell "not implemented" from
    "implemented, no outcomes yet" instead of silently aggregating
    nothing.
    """
    raise NotImplementedError(
        "load_outcomes() is a template stub — implement it for your domain "
        "(CLAUDE.md customization step 9)"
    )


def match_outcomes(
    sessions: list[SessionData],
) -> list[SessionResult]:
    """Match sessions to their outcomes/feedback.

    A stub ``load_outcomes`` (NotImplementedError) degrades to no
    outcomes with a visible warning rather than failing collection.
    """
    try:
        outcomes = load_outcomes()
    except NotImplementedError as e:
        typer.echo(f"note: collecting without outcomes — {e}", err=True)
        outcomes = {}  # lup: ignore[empty-collection] — degrade to no outcomes
    results = []  # lup: ignore[empty-collection] — per-session fold

    for session in sessions:
        session_id = session.get("_session_id", "")
        timestamp = session.get("timestamp", "")

        outcome_data = outcomes.get(session_id)

        result = SessionResult(
            session_id=session_id,
            timestamp=timestamp,
            agent_sdk=session.get("agent_sdk"),
            outcome=outcome_data,
            metrics=session.get("tool_metrics"),
        )
        results.append(result)

    return results


def load_sessions_for_versions(
    versions: list[str] | None,
) -> list[SessionData]:
    """Load sessions for a resolved version list (None = all)."""
    if versions is None:
        return load_sessions()
    return [s for v in versions for s in load_sessions(version=v)]


def collect_session_ids(
    effective: list[str] | None,
) -> set[str]:  # lup: ignore[set-shape] — deduplicated ids
    """Collect all session IDs for the given version list (None = all)."""
    if not effective:
        return set(list_all_session_ids())  # lup: ignore[set-shape]
    return {
        session_id for v in effective for session_id in list_all_session_ids(version=v)
    }


# =============================================================================
# ANALYSIS STATE TRACKING
# =============================================================================


def analyzed_file() -> Path:
    """Return path to the analyzed sessions tracking file."""
    return feedback_path() / "analyzed.json"


def load_analyzed() -> set[str]:  # lup: ignore[set-shape] — id membership
    """Load the set of already-analyzed session IDs."""
    path = analyzed_file()
    if not path.exists():
        return set()  # lup: ignore[set-shape]
    data: dict[str, list[str]] = json.loads(path.read_text())
    return set(data.get("analyzed", []))  # lup: ignore[set-shape]


def save_analyzed(
    session_ids: set[str],  # lup: ignore[set-shape] — id membership
) -> None:
    """Save the set of analyzed session IDs."""
    feedback_path().mkdir(parents=True, exist_ok=True)
    analyzed_file().write_text(
        json.dumps({"analyzed": sorted(session_ids)}, indent=2) + "\n"
    )
