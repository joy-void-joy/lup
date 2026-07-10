# lup: ignore[string-strip, string-split]
# This module IS the parser for the repo's own trace-markdown format (the
# legacy fallback beside the .events.jsonl sidecar) — line surgery here is
# the parse, not a substitute for one.
"""Trace display, search, and analysis implementation.

Provides reusable scanner functions (``scan_for_errors``, ``scan_for_capability_gaps``)
consumed by both trace CLI commands and ``feedback/analyze.py``.

Analysis reads the machine-readable ``.events.jsonl`` sidecar that
:class:`lup.telemetry.trace.TraceLogger` writes beside each ``.md`` trace: typed tool,
error, and capability events, no regex. The line-scan over markdown remains
only as the documented fallback for legacy ``.md`` traces that predate the
sidecar.

Examples::

    $ uv run lup-devtools trace list
    $ uv run lup-devtools trace list --json
    $ uv run lup-devtools trace show my-session-id --full
    $ uv run lup-devtools trace search "confidence.*low" --json
    $ uv run lup-devtools trace capabilities --json
"""

import json
import re  # lup: ignore[import-re] — legacy-markdown fallback patterns
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import typer

from lup.telemetry.blocks import truncate_str
from lup.telemetry.trace import (
    TraceEvent,
    capability_request_from_text,
    read_trace_events,
    tool_result_ok,
)
from lup.workspace.history import (
    iter_session_dirs,
    iter_trace_log_files,
    session_backend,
)
from lup.workspace.paths import parse_timestamp, project_root, traces_path

from lup_template.devtools.utils import output_json

type TraceRef = tuple[str, str, Path]  # lup: ignore[tuple-shape] — source/id/path


# ── types ─────────────────────────────────────────────────


class TraceErrorSession(TypedDict):
    session_id: str
    error_count: int
    errors: list[str]


class CapabilityRequest(TypedDict):
    text: str
    count: int
    session_ids: list[str]


class SearchMatch(TypedDict):
    file: str
    line: int
    context: list[str]


class TraceRow(TypedDict):
    session_id: str
    source: str
    backend: str | None
    files: int
    size_kb: float


# ── event sourcing: structured sidecar, with a legacy-markdown fallback ────


def events_for_trace(trace_file: Path) -> list[TraceEvent]:
    """Return the typed events for one ``.md`` trace.

    Primary path: read the ``.events.jsonl`` sidecar written beside the trace
    — already-typed tool/error/capability records, no parsing of prose. Only
    when no sidecar exists (a legacy trace predating it) does this fall back
    to :func:`events_from_legacy_markdown`.
    """
    sidecar = trace_file.with_suffix(".events.jsonl")
    if sidecar.exists():
        return read_trace_events(sidecar)
    return events_from_legacy_markdown(trace_file.read_text(encoding="utf-8"))


def events_from_legacy_markdown(content: str) -> list[TraceEvent]:
    """Reconstruct :class:`TraceEvent`s from a legacy ``.md`` trace.

    The markdown is structured, not arbitrary prose: ``TraceLogger`` renders
    each block under a ``## <emoji> <label>`` header (``Tool: <name>``,
    ``Result`` with a fenced body, ``Response`` text). This parses that
    structure — pairing each Result with the preceding Tool, and reading
    ``is_error`` from the Result's JSON via :func:`tool_result_ok` — so error
    detection matches the structured path instead of keyword-guessing. The
    one irreducible heuristic, capability phrasing in free-form Response text,
    is shared with the live logger.
    """
    events: list[TraceEvent] = []  # lup: ignore[empty-collection] — block fold
    pending_tool: str | None = None
    now = ""
    for label, body in iter_markdown_blocks(content):
        if label.startswith("Tool:"):
            pending_tool = label.removeprefix("Tool:").strip() or "unknown"
        elif label == "Result":
            name = pending_tool or "unknown"
            pending_tool = None
            ok = tool_result_ok(body)
            brief = truncate_str(body.strip(), 300)
            events.append(
                TraceEvent(
                    kind="tool_call", timestamp=now, tool=name, ok=ok, brief=brief
                )
            )
            if not ok:
                events.append(
                    TraceEvent(kind="error", timestamp=now, tool=name, brief=brief)
                )
        else:
            request = capability_request_from_text(body)
            if request is not None:
                events.append(
                    TraceEvent(kind="capability_request", timestamp=now, brief=request)
                )
    return events


def iter_markdown_blocks(
    content: str,
) -> list[tuple[str, str]]:  # lup: ignore[tuple-shape] — (label, body)
    """Split a trace markdown document into ``(label, body)`` blocks.

    A block starts at a ``## <emoji> <label>`` header and runs to the next
    header. The body has any surrounding ``` ``` fences stripped, so a Result
    body is the raw JSON the logger fenced — ready to parse.
    """
    blocks: list[tuple[str, str]] = []  # lup: ignore[tuple-shape, empty-collection]
    label: str | None = None
    body_lines: list[str] = []  # lup: ignore[empty-collection] — block fold

    def flush() -> None:
        if label is not None:
            blocks.append((label, strip_code_fence("\n".join(body_lines))))

    for line in content.split("\n"):
        if line.startswith("## "):
            flush()
            # "## 🔧 Tool: search" -> "Tool: search"; emoji is the first token.
            heading = line.removeprefix("## ").strip()
            parts = heading.split(" ", 1)
            label = parts[1].strip() if len(parts) > 1 else heading
            body_lines = []  # lup: ignore[empty-collection] — next block begins
        elif label is not None:
            body_lines.append(line)
    flush()
    return blocks


def strip_code_fence(body: str) -> str:
    """Drop a leading ``` (or ```json) fence and its closing ``` from *body*."""
    lines = body.strip().split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def resolve_trace_paths(effective: list[str] | None) -> list[Path]:
    """Collect .md trace files, optionally filtered by version list."""
    if not traces_path().exists():
        return []
    if effective:
        paths: list[Path] = []  # lup: ignore[empty-collection] — per-version fold
        for v in effective:
            ver_dir = traces_path() / v
            if ver_dir.exists():
                paths.extend(ver_dir.rglob("*.md"))
        return paths
    return list(traces_path().rglob("*.md"))


def display_path(path: Path) -> str:
    """Project-relative path for display, absolute when outside the project."""
    try:
        return str(path.relative_to(project_root()))
    except ValueError:
        return str(path)


def session_id_from_path(trace_file: Path) -> str:
    """Extract session ID from a trace file path."""
    try:
        rel = trace_file.relative_to(traces_path())
        return rel.parts[2] if len(rel.parts) > 2 else rel.stem
    except ValueError:
        return trace_file.stem


def scan_for_errors(
    effective: list[str] | None = None,
) -> list[TraceErrorSession]:
    """Report failing tool calls per session from structured trace events.

    Reads each trace's typed events (sidecar, or legacy-markdown fallback)
    and keeps the ``error`` ones — real tool failures, distinguished by the
    logged ``is_error`` flag rather than by keyword-scanning prose.
    """
    errors_by_session: dict[str, list[str]] = {}  # lup: ignore[empty-collection]

    for trace_file in resolve_trace_paths(effective):
        try:
            events = events_for_trace(trace_file)
        except OSError:
            continue
        session_id = session_id_from_path(trace_file)
        for event in events:
            if event.kind != "error":
                continue
            errors_by_session.setdefault(session_id, []).append(
                f"{event.tool or 'unknown'}: {event.brief}"
            )

    result: list[TraceErrorSession] = []  # lup: ignore[empty-collection] — fold
    for session_id, errors in sorted(
        errors_by_session.items(), key=lambda x: len(x[1]), reverse=True
    ):
        result.append(
            {
                "session_id": session_id,
                "error_count": len(errors),
                "errors": errors,
            }
        )
    return result


def scan_for_capability_gaps(
    effective: list[str] | None = None,
) -> list[CapabilityRequest]:
    """Report capability requests across traces, deduplicated by text.

    Reads each trace's typed ``capability_request`` events (sidecar, or
    legacy-markdown fallback) and groups identical wishes, most-requested
    first.
    """
    requests_by_text: dict[str, list[str]] = defaultdict(list)

    for trace_file in resolve_trace_paths(effective):
        try:
            events = events_for_trace(trace_file)
        except OSError:
            continue
        session_id = session_id_from_path(trace_file)
        for event in events:
            if event.kind == "capability_request" and event.brief:
                requests_by_text[event.brief].append(session_id)

    result: list[CapabilityRequest] = []  # lup: ignore[empty-collection] — fold
    for text, session_ids in sorted(requests_by_text.items(), key=lambda x: -len(x[1])):
        result.append(
            {
                "text": text,
                "count": len(session_ids),
                "session_ids": sorted(set(session_ids)),  # lup: ignore[set-shape]
            }
        )
    return result


# ── helpers ───────────────────────────────────────────────


def find_trace(session_id: str) -> Path | None:
    """Find a showable trace for a session across all versions.

    Prefers a markdown reasoning log, then any ``.md`` in the session dir,
    then the session dir itself — whose JSON ``trace list`` enumerates, so
    every listed id is showable (rendered readably by :func:`load_trace`).
    """
    log_files = list(iter_trace_log_files(session_id=session_id))
    if log_files:
        return sorted(log_files)[-1]

    session_dirs = list(iter_session_dirs(session_id=session_id))
    for session_dir in session_dirs:
        md_files = list(session_dir.glob("*.md"))
        if md_files:
            return sorted(md_files)[-1]

    if session_dirs:
        return sorted(session_dirs)[-1]

    return None


def render_json_trace(path: Path) -> str:
    """Render a session JSON file as readable, pretty-printed text."""
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(parsed, indent=2, ensure_ascii=False)


def load_trace(trace_path: Path) -> str:
    """Load trace content from a file or directory, rendering JSON readably."""
    if trace_path.is_file():
        if trace_path.suffix == ".json":
            return render_json_trace(trace_path)
        return trace_path.read_text(encoding="utf-8")

    if trace_path.is_dir():
        contents = []  # lup: ignore[empty-collection] — per-file fold
        for f in sorted(trace_path.glob("*")):
            if not f.is_file():
                continue
            body = (
                render_json_trace(f)
                if f.suffix == ".json"
                else f.read_text(encoding="utf-8")
            )
            contents.append(f"--- {f.name} ---\n{body}")
        return "\n\n".join(contents)

    return ""


TOOL_CALL_PATTERNS = re.compile(  # lup: ignore[re-call] — legacy-markdown scan
    r"tool_use|tool_result|^#{2,3}\s+\S+\s+Tool:|^#{2,3}\s+\S+\s+Result\b",
    re.IGNORECASE,
)


def filter_tool_calls(content: str, context_lines: int = 3) -> str:
    """Extract lines matching tool call patterns with surrounding context."""
    lines = content.split("\n")
    matched_indices: set[int] = set()  # lup: ignore[set-shape, empty-collection]

    for i, line in enumerate(lines):
        if TOOL_CALL_PATTERNS.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            matched_indices.update(range(start, end))

    if not matched_indices:
        return "(no tool call lines found)"

    result: list[str] = []  # lup: ignore[empty-collection] — context-window fold
    prev_idx = -2
    for idx in sorted(matched_indices):
        if idx > prev_idx + 1:
            if result:
                result.append("---")
        result.append(lines[idx])
        prev_idx = idx

    return "\n".join(result)


# ── CLI commands ──────────────────────────────────────────


def show(session_id: str, full: bool, tool_calls: bool, as_json: bool) -> None:
    """Show trace for a session."""
    trace_path = find_trace(session_id)

    if not trace_path:
        typer.echo(f"No trace found for session {session_id}", err=True)
        typer.echo(f"Checked: {traces_path()}", err=True)
        raise typer.Exit(1)

    content = load_trace(trace_path)

    if tool_calls:
        content = filter_tool_calls(content)
    elif not full:
        lines = content.split("\n")
        if len(lines) > 100:
            content = "\n".join(lines[:100])

    if as_json:
        output_json(
            {
                "session_id": session_id,
                "path": str(trace_path),
                "content": content,
            }
        )
        return

    typer.echo(f"\n=== Trace for {session_id} ===")
    typer.echo(f"Path: {trace_path}\n")
    typer.echo(content)
    if not full and not tool_calls:
        lines = load_trace(trace_path).split("\n")
        if len(lines) > 100:
            typer.echo(f"\n... ({len(lines) - 100} more lines)")
            typer.echo("Use --full to see complete trace")


def search(pattern: str, context: int, as_json: bool) -> None:
    """Search traces for a pattern."""
    if not traces_path().exists():
        if as_json:
            output_json({"matches": [], "total": 0})
        else:
            typer.echo("0 matches found")
        return

    regex = re.compile(pattern, re.IGNORECASE)  # lup: ignore[re-call] — user query
    matches: list[SearchMatch] = []  # lup: ignore[empty-collection] — match fold

    trace_files = list(traces_path().rglob("*.md")) + list(
        traces_path().rglob("*.json")
    )
    for trace_file in trace_files:
        try:
            content = trace_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context)
                    end = min(len(lines), i + context + 1)
                    matches.append(
                        {
                            "file": display_path(trace_file),
                            "line": i + 1,
                            "context": lines[start:end],
                        }
                    )
        except OSError as e:
            typer.echo(f"Error reading {trace_file}: {e}", err=True)

    if as_json:
        output_json({"matches": matches, "total": len(matches)})
        return

    for m in matches:
        typer.echo(f"\n--- {m['file']}:{m['line']} ---")
        match_idx = m["line"] - 1
        start_line = match_idx - context
        for j, ctx_line in enumerate(m["context"]):
            actual_line = start_line + j
            prefix = ">>> " if actual_line == match_idx else "    "
            typer.echo(f"{prefix}{ctx_line}")

    typer.echo(f"\n{len(matches)} matches found")


def errors_in_traces(
    limit: int,
    effective: list[str] | None,
    as_json: bool,
) -> None:
    """Show sessions with errors found by regex in trace markdown files."""
    results = scan_for_errors(effective)

    if as_json:
        output_json({"sessions": results[:limit], "total": len(results)})
        return

    if not results:
        typer.echo("No errors found in traces")
        return

    typer.echo(f"\n=== Trace Errors ({len(results)} sessions) ===\n")

    for entry in results[:limit]:
        typer.echo(f"{entry['session_id']}: {entry['error_count']} errors")
        for line in entry["errors"][:3]:
            typer.echo(f"  - {line}")
        if len(entry["errors"]) > 3:
            typer.echo(f"  ... and {len(entry['errors']) - 3} more")
        typer.echo()


def entry_recency(path: Path) -> datetime:
    """Newest timestamp parsed from contained filenames, falling back to mtime."""
    try:
        names = [f.name for f in path.iterdir()]
    except OSError:
        names = []  # lup: ignore[empty-collection] — unreadable dir: no entries
    stamps: list[datetime] = []  # lup: ignore[empty-collection] — parse fold
    for name in names:
        try:
            stamps.append(parse_timestamp(name))
        except ValueError:
            continue
    if stamps:
        return max(stamps)
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.min


def list_traces(limit: int, effective: list[str] | None, as_json: bool) -> None:
    """List available traces, most recent first."""
    raw: list[TraceRef] = []  # lup: ignore[empty-collection] — discovery fold

    versions_iter = effective if effective else [None]
    for ver in versions_iter:
        for session_dir in iter_session_dirs(version=ver):
            raw.append(("sessions", session_dir.name, session_dir))
        for log_file in iter_trace_log_files(version=ver):
            raw.append(("logs", log_file.parent.name, log_file.parent))

    if not raw:
        if as_json:
            output_json({"traces": [], "total": 0})
        else:
            typer.echo("No traces found")
            typer.echo(f"Checked: {traces_path()}")
        return

    seen: dict[str, TraceRef] = {}  # lup: ignore[empty-collection] — dedup fold
    for source, session_id, path in raw:
        if session_id not in seen or source == "logs":
            seen[session_id] = (source, session_id, path)

    unique = sorted(seen.values(), key=lambda row: entry_recency(row[2]), reverse=True)
    entries: list[TraceRow] = []  # lup: ignore[empty-collection] — display fold
    for source, session_id, path in unique[:limit]:
        files = list(path.glob("*"))
        size = sum(f.stat().st_size for f in files if f.is_file())
        entries.append(
            {
                "session_id": session_id,
                "source": source,
                "backend": session_backend(path),
                "files": len(files),
                "size_kb": round(size / 1024, 1),
            }
        )

    if as_json:
        output_json({"traces": entries, "total": len(unique)})
        return

    typer.echo(f"\n=== Available Traces ({len(unique)} total) ===\n")
    for e in entries:
        backend = e["backend"] or "—"
        typer.echo(
            f"{e['session_id']} ({e['source']}, {backend}): "
            f"{e['files']} files, {e['size_kb']}KB"
        )


def capabilities(as_json: bool) -> None:
    """Surface the tools and capabilities the agent wished it had.

    Scans trace logs for moments where the agent reached for something it
    could not do ("would be useful", "if I could", "tool that ...", "need
    access to ...") and reports them deduplicated, most-requested first.

    This is the feedback loop's primary lever: the Bitter Lesson says the agent
    improves by gaining tools, not rules (CLAUDE.md), so a recurring capability
    request across sessions is the strongest signal of a missing tool to build.
    The phrasing scan is heuristic; treat the output as leads to read in full
    via ``trace show``, not a finished backlog.
    """
    results = scan_for_capability_gaps()

    if as_json:
        output_json({"requests": results, "total": len(results)})
        return

    if not results:
        typer.echo("No capability requests found in traces")
        return

    typer.echo(f"\n=== Capability Requests ({len(results)} found) ===\n")

    for req in results:
        typer.echo(f"- {req['text']}")
