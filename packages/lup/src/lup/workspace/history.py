# lup: ignore[import-re, re-call]
# The semver parser is a three-integer pattern over version directory names —
# regex is the tool, so those rules are opted out file-wide.
"""Session history storage, retrieval, and cross-version data discovery.

This module handles:
1. Saving session results to notes/traces/<version>/sessions/
2. Loading past sessions for context or analysis (across versions)
3. Tracking session metadata (submitted, outcome, etc.)
4. Cross-version iteration over sessions, outputs, and trace logs
5. Version scope resolution with progressive semver fallback

The feedback loop scripts read from this storage.

All functions accept :class:`pydantic.BaseModel` instances and work
with raw JSON dicts — no dependency on domain-specific models.
The ``format_history_for_context`` function accepts a pluggable
formatter so downstream projects can display domain-specific fields
without modifying this module.

Examples:
    Save and load session results::

        >>> from pydantic import BaseModel
        >>> class MyResult(BaseModel):
        ...     summary: str
        ...     confidence: float
        >>> path = save_session(MyResult(summary="done", confidence=0.9), session_id="s1")
        >>> path.exists()
        True

    Load past sessions for analysis::

        >>> sessions = load_sessions_json("s1")
        >>> len(sessions)
        1
        >>> sessions[0]["summary"]
        'done'

    Iterate sessions across versions::

        >>> for session_dir in iter_session_dirs(session_id="my-session"):
        ...     print(session_dir)
        PosixPath('.../notes/traces/0.1.0/sessions/my-session')

    Resolve version scope with progressive fallback::

        >>> versions, warning = resolve_version("0.1.0")
        >>> versions
        ['0.1.0']
"""

import json
import logging
import re
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, Field, SerializeAsAny

from lup.types import JsonValue, Usage
from lup.telemetry.metrics import MetricsSummary
from lup.workspace.paths import (
    TIMESTAMP_FMT,
    agent_version,
    parse_timestamp,
    sessions_dir,
    traces_path,
)

logger = logging.getLogger(__name__)

# Type alias for raw session JSON — schema varies by domain
type SessionData = dict[str, JsonValue]


class SessionResult[OutputT: BaseModel](BaseModel):
    """Complete result of an agent session.

    Generic over the output type so domain-specific agent output
    models can be used without modifying this module.

    This captures everything needed for the feedback loop:
    - The structured output
    - Metadata (timing, cost, token usage)
    - Tool metrics for analysis
    """

    session_id: str
    task_id: str | None = Field(default=None, description="Domain-specific task ID")
    agent_version: str = Field(
        default="", description="Agent version that produced this result"
    )
    agent_sdk: str | None = Field(
        default=None,
        description="Engine that ran the session (its engine id); "
        "None on results predating the stamp",
    )
    sdk_session_id: str | None = Field(
        default=None,
        description="Engine-native session id — the resume token for "
        "Client.session(resume=...); None when the engine reported none",
    )
    timestamp: str
    output: OutputT
    reasoning: str = Field(default="", description="Raw reasoning text")
    sources_consulted: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
    cost_usd: float | None = None
    token_usage: SerializeAsAny[Usage] | None = None
    tool_metrics: MetricsSummary | None = None
    outcome: str | None = Field(default=None, description="Outcome after resolution")


def save_session(
    result: BaseModel,  # lup: ignore[bare-basemodel] — any domain's result model
    *,
    session_id: str,
) -> Path:
    """Save a session result to disk.

    Args:
        result: Any Pydantic model representing a session result.
        session_id: Unique session identifier.

    Returns:
        Path to the saved file.
    """
    session_dir = sessions_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime(TIMESTAMP_FMT)
    filepath = session_dir / f"{timestamp}.json"

    filepath.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved session %s to %s", session_id, filepath)

    return filepath


def session_backend(session_dir: Path) -> str | None:
    """Read the ``agent_sdk`` stamp from a session dir's newest result JSON.

    Returns None when no result JSON exists or none carries the stamp
    (sessions predating it) — display code renders that as unknown
    rather than guessing a backend.
    """
    for filepath in sorted(session_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            sdk = data.get("agent_sdk")  # lup: ignore[dict-get] — payload probe
            if isinstance(sdk, str):
                return sdk
    return None


def load_sessions_json(session_id: str) -> list[SessionData]:
    """Load all session JSON dicts for a given ID across all versions.

    Returns raw dicts rather than typed models, so this function has
    no dependency on domain-specific model classes.

    Args:
        session_id: The session identifier.

    Returns:
        List of session dicts, sorted by timestamp field (oldest first).
    """
    sessions: list[SessionData] = []  # lup: ignore[empty-collection] — tolerant fold

    for session_dir in iter_session_dirs(session_id=session_id):
        for filepath in sorted(session_dir.glob("*.json")):
            try:
                data: SessionData = json.loads(filepath.read_text(encoding="utf-8"))
                sessions.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load session from %s: %s", filepath, e)

    sessions.sort(key=lambda s: str(s.get("timestamp", "")))  # lup: ignore[dict-get]
    return sessions


def get_latest_session_json(session_id: str) -> SessionData | None:
    """Get the most recent session dict for an ID.

    Args:
        session_id: The session identifier.

    Returns:
        The most recent session dict, or None if no sessions exist.
    """
    sessions = load_sessions_json(session_id)
    return sessions[-1] if sessions else None


def update_session_metadata(
    session_id: str,
    *,
    outcome: str | None = None,
    submitted_at: str | None = None,
) -> bool:
    """Update metadata for the latest session.

    Args:
        session_id: The session identifier.
        outcome: Outcome value to set (e.g., "success", "failure").
        submitted_at: ISO timestamp when submitted.

    Returns:
        True if a session was updated, False if not found.
    """
    all_files = [
        filepath
        for session_dir in iter_session_dirs(session_id=session_id)
        for filepath in session_dir.glob("*.json")
    ]

    if not all_files:
        return False

    def file_timestamp(path: Path) -> datetime:
        """Sort key: parsed filename timestamp (non-timestamped names sort first)."""
        try:
            return parse_timestamp(path.name)
        except ValueError:
            return datetime.min

    # Latest by parsed timestamp — a lexicographic full-path sort would
    # order version directories wrong (0.10.0 < 0.9.0).
    latest_file = max(all_files, key=file_timestamp)

    try:
        data: SessionData = json.loads(latest_file.read_text(encoding="utf-8"))

        if outcome is not None:
            data["outcome"] = outcome
        if submitted_at is not None:
            data["submitted_at"] = submitted_at

        latest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Updated metadata for session %s", session_id)
        return True

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to update session %s: %s", session_id, e)
        return False


# -- Default formatter for format_history_for_context -------------------------


def default_session_formatter(session: SessionData) -> str:
    """Format a session dict as a markdown summary.

    Extracts common fields that most domains will have. Downstream
    projects can provide a custom formatter for domain-specific display.
    """
    stamp = session.get("timestamp", "unknown")  # lup: ignore[dict-get]
    lines: list[str] = [f"### {stamp}"]

    output = session.get("output", {})  # lup: ignore[dict-get] — optional key
    if isinstance(output, dict):
        if "summary" in output:
            lines.append(f"**Summary**: {str(output['summary'])[:200]}...")
        if "confidence" in output:
            confidence = output["confidence"]
            if isinstance(confidence, (int, float)):
                lines.append(f"**Confidence**: {confidence:.1%}")

    if session.get("outcome"):  # lup: ignore[dict-get] — optional key
        lines.append(f"**Outcome**: {session['outcome']}")

    lines.append("")
    return "\n".join(lines)


def format_history_for_context(
    sessions: list[SessionData],
    *,
    max_sessions: int = 5,
    formatter: Callable[[SessionData], str] | None = None,
) -> str:
    """Format past sessions as context for the agent.

    Args:
        sessions: List of session dicts (from :func:`load_sessions_json`).
        max_sessions: Maximum number of sessions to include.
        formatter: Callable that formats a single session dict into
            a markdown string. Uses a default formatter if ``None``.

    Returns:
        Markdown-formatted summary of past sessions.
    """
    if not sessions:
        return ""

    fmt = formatter or default_session_formatter

    lines = ["## Past Sessions\n"]
    for session in sessions[-max_sessions:]:
        lines.append(fmt(session))

    return "\n".join(lines)


# -- Cross-version data discovery ---------------------------------------------


def version_dirs() -> list[Path]:
    """Return all version directories under notes/traces/, sorted."""
    tp = traces_path()
    if not tp.exists():
        return []
    return sorted(d for d in tp.iterdir() if d.is_dir() and not d.name.startswith("."))


def iter_session_dirs(
    session_id: str | None = None,
    version: str | None = None,
) -> Iterator[Path]:
    """Iterate over session directories across all (or filtered) versions.

    Yields paths like: notes/traces/0.1.0/sessions/my-session/
    """
    ver_dirs = [traces_path() / version] if version else version_dirs()

    for ver_dir in ver_dirs:
        sessions_base = ver_dir / "sessions"
        if not sessions_base.exists():
            continue
        if session_id is not None:
            candidate = sessions_base / session_id
            if candidate.exists() and candidate.is_dir():
                yield candidate
        else:
            for d in sessions_base.iterdir():
                if d.is_dir():
                    yield d


def iter_output_dirs(
    task_id: str | None = None,
    version: str | None = None,
) -> Iterator[Path]:
    """Iterate over output directories across all (or filtered) versions.

    Yields paths like: notes/traces/0.1.0/outputs/my-task/
    """
    ver_dirs = [traces_path() / version] if version else version_dirs()

    for ver_dir in ver_dirs:
        outputs_base = ver_dir / "outputs"
        if not outputs_base.exists():
            continue
        if task_id is not None:
            candidate = outputs_base / task_id
            if candidate.exists() and candidate.is_dir():
                yield candidate
        else:
            for d in outputs_base.iterdir():
                if d.is_dir():
                    yield d


def iter_trace_log_files(
    session_id: str | None = None,
    version: str | None = None,
) -> Iterator[Path]:
    """Iterate reasoning log files across all (or filtered) versions."""
    ver_dirs = [traces_path() / version] if version else version_dirs()

    for ver_dir in ver_dirs:
        logs_base = ver_dir / "logs"
        if not logs_base.exists():
            continue
        if session_id is not None:
            session_logs = logs_base / session_id
            if session_logs.exists():
                yield from session_logs.glob("*.md")
        else:
            yield from logs_base.rglob("*.md")


def list_all_session_ids(version: str | None = None) -> list[str]:
    """Return all session IDs across versions, deduplicated."""
    return sorted({d.name for d in iter_session_dirs(version=version)})


# -- Version scope resolution ------------------------------------------------

MIN_VERSION_DATAPOINTS = 10

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class Semver(NamedTuple):
    """A parsed X.Y.Z version."""

    major: int
    minor: int
    patch: int


def parse_semver(version: str) -> Semver | None:
    """Parse 'X.Y.Z' into a :class:`Semver`, or None if invalid."""
    m = SEMVER_RE.match(version)
    if not m:
        return None
    return Semver(int(m.group(1)), int(m.group(2)), int(m.group(3)))


class VersionScope(NamedTuple):
    """A resolved version scope: the versions to include (None = all), and the
    widening warning to show, if the requested scope was too sparse."""

    versions: list[str] | None
    warning: str | None


def count_sessions_for_versions(versions: list[str]) -> int:
    """Count total session directories across a set of version directories."""
    return sum(sum(1 for _ in iter_session_dirs(version=v)) for v in versions)


def resolve_version(
    version: str | None,
    all_versions: bool = False,
    min_datapoints: int = MIN_VERSION_DATAPOINTS,
) -> VersionScope:
    """Resolve effective version scope with progressive semver fallback.

    Fallback chain: exact version → X.Y.* → X.* → all versions.
    Widens when the narrower scope has fewer than ``min_datapoints`` sessions.

    Returns ``(version_list, warning_message)``.
    ``version_list`` is ``None`` when all versions should be included.
    """
    if all_versions:
        return VersionScope(None, None)

    effective = version if version is not None else agent_version()
    semver = parse_semver(effective)
    available = [d.name for d in version_dirs()]

    # Level 1: exact version
    exact = [effective] if effective in available else []
    exact_count = count_sessions_for_versions(exact)
    if exact_count >= min_datapoints:
        return VersionScope(exact, None)

    if semver is None:
        all_count = count_sessions_for_versions(available)
        if all_count == 0:
            return VersionScope(None, None)
        return VersionScope(
            None,
            f"v{effective} has only {exact_count} sessions "
            f"(need {min_datapoints}) — including all versions",
        )

    major, minor, _ = semver

    # Level 2: same minor (X.Y.*)
    minor_matches = [
        v
        for v in available
        if (sv := parse_semver(v)) is not None
        and sv.major == major
        and sv.minor == minor
    ]
    minor_count = count_sessions_for_versions(minor_matches)
    if minor_count >= min_datapoints:
        return VersionScope(
            minor_matches,
            f"v{effective} has only {exact_count} sessions "
            f"— widening to v{major}.{minor}.* ({minor_count} sessions)",
        )

    # Level 3: same major (X.*)
    major_matches = [
        v
        for v in available
        if (sv := parse_semver(v)) is not None and sv.major == major
    ]
    major_count = count_sessions_for_versions(major_matches)
    if major_count >= min_datapoints:
        return VersionScope(
            major_matches,
            f"v{major}.{minor}.* has only {minor_count} sessions "
            f"— widening to v{major}.* ({major_count} sessions)",
        )

    # Level 4: all versions
    all_count = count_sessions_for_versions(available)
    if all_count == 0:
        return VersionScope(None, None)
    return VersionScope(
        None,
        f"v{major}.* has only {major_count} sessions "
        f"(need {min_datapoints}) — including all versions",
    )
