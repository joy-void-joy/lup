"""Trace display, search, and analysis implementation.

Provides reusable scanner functions (``scan_for_errors``, ``scan_for_capability_gaps``)
consumed by both trace CLI commands and ``feedback/analyze.py``.

Examples::

    $ uv run lup-devtools trace list
    $ uv run lup-devtools trace list --json
    $ uv run lup-devtools trace show my-session-id --full
    $ uv run lup-devtools trace search "confidence.*low" --json
    $ uv run lup-devtools trace capabilities --json
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import typer

from lup.history import iter_session_dirs, iter_trace_log_files, session_backend
from lup.paths import parse_timestamp, project_root, traces_path

from lup_template.devtools.utils import output_json


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


# ── shared scanners ───────────────────────────────────────

ERROR_PATTERNS = re.compile(
    r"error|failed|exception|traceback|couldn't|unable to|not found|timeout",  # claude: Gosh this is extremely bad, this is exactly why re should be on the banned list
    # claude: Yeah, this seems useless and not principled at all.
    re.IGNORECASE,
)

# Trace files are free-form markdown (prose + truncated JSON fragments +
# code), not parseable JSON documents — a line scan is the right tool here.
# Successful-result lines often contain "error" as a falsy field
# (e.g. ``"is_error": false``, ``"status": "reviewed"``); suppress those so
# the error view shows real failures, not healthy JSON blobs.
SUCCESS_PATTERNS = re.compile(  # claude: ignore  # keyword scan over markdown, not JSON parsing
    # claude: Same here. The previous agent decided to "claude: ignore" where it really shouldn't have
    r'"(is_error|error)"\s*:\s*(false|null|0|""|\[\])'
    r'|"error_count"\s*:\s*0'
    r'|"status"\s*:\s*"(ok|success|succeeded|reviewed|passed|complete[d]?)"',
    re.IGNORECASE,
)


def keyword_window(line: str, width: int = 80) -> str:
    """Return a window of *line* centered on the first error keyword."""
    line = line.strip()
    match = ERROR_PATTERNS.search(line)
    if match is None or len(line) <= width:
        return line if len(line) <= width else line[:width] + "..."

    start = max(0, match.start() - width // 2)
    end = min(len(line), start + width)
    snippet = line[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(line):
        snippet = snippet + "..."
    return snippet


CAPABILITY_PATTERNS = re.compile(
    r"would be useful|would have helped|would benefit from|wish I had|"
    r"if I could|tool that|need.* access to|cannot .* because",
    re.IGNORECASE,
)  # claude: Again, same. We really need to have the agent output in a more parseable way so we don't have to deal with this.


def resolve_trace_paths(effective: list[str] | None) -> list[Path]:
    """Collect .md trace files, optionally filtered by version list."""
    if not traces_path().exists():
        return []
    if effective:
        paths: list[Path] = []
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
    """Scan trace markdown files for error-like lines, grouped by session."""
    errors_by_session: dict[str, list[str]] = {}

    for trace_file in resolve_trace_paths(effective):
        try:
            content = trace_file.read_text(encoding="utf-8")
            session_id = session_id_from_path(trace_file)

            for line in content.split("\n"):
                if not ERROR_PATTERNS.search(line):
                    continue
                if SUCCESS_PATTERNS.search(line):
                    continue
                if session_id not in errors_by_session:
                    errors_by_session[session_id] = []
                errors_by_session[session_id].append(keyword_window(line))
        except OSError:
            pass

    result: list[TraceErrorSession] = []
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
    """Scan trace markdown files for capability requests, deduplicated by text."""
    requests_by_text: dict[str, list[str]] = defaultdict(list)

    for trace_file in resolve_trace_paths(effective):
        try:
            content = trace_file.read_text(encoding="utf-8")
            session_id = session_id_from_path(trace_file)

            for line in content.split("\n"):
                if CAPABILITY_PATTERNS.search(line):
                    text = line.strip()[:120]
                    if text:
                        requests_by_text[text].append(session_id)
        except OSError:
            pass

    result: list[CapabilityRequest] = []
    for text, session_ids in sorted(requests_by_text.items(), key=lambda x: -len(x[1])):
        result.append(
            {
                "text": text,
                "count": len(session_ids),
                "session_ids": sorted(set(session_ids)),
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
        contents = []
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


TOOL_CALL_PATTERNS = re.compile(
    r"tool_use|tool_result|^#{2,3}\s+\S+\s+Tool:|^#{2,3}\s+\S+\s+Result\b",
    re.IGNORECASE,
)  # claude: Yeah, most of this file is just regex matches and should be completely refactored


def filter_tool_calls(content: str, context_lines: int = 3) -> str:
    """Extract lines matching tool call patterns with surrounding context."""
    lines = content.split("\n")
    matched_indices: set[int] = set()

    for i, line in enumerate(lines):
        if TOOL_CALL_PATTERNS.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            matched_indices.update(range(start, end))

    if not matched_indices:
        return "(no tool call lines found)"

    result: list[str] = []
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

    regex = re.compile(pattern, re.IGNORECASE)
    matches: list[SearchMatch] = []

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
        names = []
    stamps: list[datetime] = []
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
    raw: list[tuple[str, str, Path]] = []

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

    seen: dict[str, tuple[str, str, Path]] = {}
    for source, session_id, path in raw:
        if session_id not in seen or source == "logs":
            seen[session_id] = (source, session_id, path)

    unique = sorted(seen.values(), key=lambda row: entry_recency(row[2]), reverse=True)
    entries: list[TraceRow] = []
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
