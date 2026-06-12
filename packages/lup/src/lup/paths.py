"""Centralized path constants and helpers for agent session data.

Pure path layout — where things go on disk. No data discovery or disk
iteration; see :mod:`lup.history` for cross-version queries.

Paths auto-detect the project root (walking up to ``pyproject.toml``)
on first access, but can be overridden via :func:`configure`::

    from lup.paths import configure
    configure(root=Path("/my/project"), notes_dir=Path("/my/data/notes"))

Resolution is lazy and cached: importing this module never touches the
filesystem, so ``lup`` is importable outside a ``[tool.lup]`` project
(e.g. when pip-installed). Auto-detection runs on the first accessor
call; calling :func:`configure` first skips it entirely.

Layout:
    notes/traces/<version>/sessions/<session_id>/<timestamp>.json
    notes/traces/<version>/outputs/<task_id>/<timestamp>/
    notes/traces/<version>/logs/<session_id>/<timestamp>.md
    notes/feedback_loop/

Examples:
    Override paths for testing (the root does not need a pyproject.toml;
    the version falls back to "0.0.0" unless given explicitly)::

        >>> from lup.paths import configure, sessions_dir, project_root
        >>> configure(root=Path("/tmp/test-project"))
        >>> project_root()
        PosixPath('/tmp/test-project')
        >>> sessions_dir()
        PosixPath('/tmp/test-project/notes/traces/0.0.0/sessions')

    Check if a path is within allowed directories::

        >>> path_is_under("/data/sessions/12345/out.json", [Path("/data/sessions")])
        True
        >>> path_is_under("/etc/passwd", [Path("/data/sessions")])
        False

    Extract the directory prefix from a glob pattern::

        >>> extract_glob_dir("/tmp/foo/**/*.py")
        '/tmp/foo'
        >>> extract_glob_dir("**/*.py")
        ''
"""

import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import tomllib
from pydantic import BaseModel


def find_project_root() -> Path:
    """Find project root by walking up to the pyproject.toml with [tool.lup]."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as f:
                data = tomllib.load(f)
            if "lup" in data.get("tool", {}):
                return parent
    raise RuntimeError(
        "Could not find project root (no pyproject.toml with [tool.lup] found)"
    )


def read_agent_version(root: Path) -> str:
    """Read agent_version from [tool.lup] in pyproject.toml.

    Returns "0.0.0" when the file or the [tool.lup] table is absent, so
    :func:`configure` accepts roots that are not lup projects (e.g. test
    fixtures or scratch directories).
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    return data.get("tool", {}).get("lup", {}).get("agent_version", "0.0.0")


# -- Mutable path state -------------------------------------------------------
# Resolved lazily on first accessor call; overridable via configure().
# Internal — read it through the accessor functions, never import it by name.


class PathConfig(BaseModel):
    """Resolved path state: project root, agent version, base directories."""

    root: Path
    version: str
    notes_dir: Path
    logs_dir: Path


state: PathConfig | None = None


def resolve_state() -> PathConfig:
    """Return the cached path state, auto-detecting the project root on first use."""
    global state  # noqa: PLW0603
    if state is None:
        root = find_project_root()
        state = PathConfig(
            root=root,
            version=read_agent_version(root),
            notes_dir=root / "notes",
            logs_dir=root / "logs",
        )
    return state


def configure(
    *,
    root: Path | None = None,
    notes_dir: Path | None = None,
    logs_dir: Path | None = None,
    version: str | None = None,
) -> None:
    """Override auto-detected paths.

    Call before any session operations. All derived paths
    (``traces_path``, ``feedback_path``, etc.)
    update automatically since they read from this state.

    ``pyproject.toml`` is consulted only when ``root`` is given without
    ``version``, and even then it does not have to exist — a missing
    file or missing ``[tool.lup]`` table falls back to version "0.0.0".

    Args:
        root: Project root directory. Resets ``notes_dir``,
            ``logs_dir``, and ``version`` to values derived from
            the new root unless they are also specified.
        notes_dir: Override notes directory independently.
        logs_dir: Override runtime logs directory independently.
        version: Override agent version (read from [tool.lup] by default).
    """
    global state  # noqa: PLW0603

    if root is not None:
        state = PathConfig(
            root=root,
            version=version if version is not None else read_agent_version(root),
            notes_dir=notes_dir if notes_dir is not None else root / "notes",
            logs_dir=logs_dir if logs_dir is not None else root / "logs",
        )
        return

    updates: dict[str, Path | str] = {}
    if notes_dir is not None:
        updates["notes_dir"] = notes_dir
    if logs_dir is not None:
        updates["logs_dir"] = logs_dir
    if version is not None:
        updates["version"] = version
    if updates:
        state = resolve_state().model_copy(update=updates)


# -- Public path accessors ----------------------------------------------------


def project_root() -> Path:
    """Return the project root directory."""
    return resolve_state().root


def agent_version() -> str:
    """Return the agent version ([tool.lup] in pyproject.toml unless overridden)."""
    return resolve_state().version


def notes_path() -> Path:
    """Return the notes directory (``<root>/notes`` by default)."""
    return resolve_state().notes_dir


def runtime_logs_path() -> Path:
    """Return the runtime logs directory (``<root>/logs`` by default)."""
    return resolve_state().logs_dir


def traces_path() -> Path:
    """Return ``notes/traces/``."""
    return notes_path() / "traces"


def feedback_path() -> Path:
    """Return ``notes/feedback_loop/``."""
    return notes_path() / "feedback_loop"


# -- Timestamp helpers --------------------------------------------------------

TIMESTAMP_FMT = "%Y%m%d_%H%M%S"
TIMESTAMP_RE = re.compile(r"\d{8}_\d{6}")


def parse_timestamp(name: str) -> datetime:
    """Parse the last YYYYMMDD_HHMMSS occurrence from a filename or string."""
    matches = TIMESTAMP_RE.findall(Path(name).stem)
    if not matches:
        raise ValueError(f"No YYYYMMDD_HHMMSS timestamp found in: {name}")
    return datetime.strptime(matches[-1], TIMESTAMP_FMT)


# -- Write paths (version-specific) ------------------------------------------


def sessions_dir(version: str | None = None) -> Path:
    """Directory for session JSONs: notes/traces/<version>/sessions/"""
    return traces_path() / (version or agent_version()) / "sessions"


def outputs_dir(version: str | None = None) -> Path:
    """Directory for agent outputs: notes/traces/<version>/outputs/"""
    return traces_path() / (version or agent_version()) / "outputs"


def trace_logs_dir(version: str | None = None) -> Path:
    """Directory for reasoning logs: notes/traces/<version>/logs/"""
    return traces_path() / (version or agent_version()) / "logs"


# -- Path utilities -----------------------------------------------------------


def extract_glob_dir(pattern: str) -> str:
    """Extract the directory prefix from a glob pattern.

    Strips everything from the first glob wildcard character onward,
    returning the longest non-glob directory prefix.

    Used by permission hooks to validate Glob tool calls where the
    agent puts the full path in the ``pattern`` parameter instead of
    using the separate ``path`` parameter.

    Examples:
        >>> extract_glob_dir("/tmp/foo/**/*.py")
        '/tmp/foo'
        >>> extract_glob_dir("**/*.py")
        ''
        >>> extract_glob_dir("/tmp/foo/bar")
        '/tmp/foo/bar'
    """
    for i, c in enumerate(pattern):
        if c in "*?[":
            return pattern[:i].rstrip("/")
    return pattern


def path_is_under(file_path: str | Path, allowed_dirs: list[Path]) -> bool:
    """Check if a file path is under one of the allowed directories.

    Used by permission hooks to enforce RW/RO access.

    Args:
        file_path: Path to check.
        allowed_dirs: List of allowed parent directories.

    Returns:
        True if the path is under one of the allowed directories.
    """
    try:
        path = Path(file_path).resolve()
    except (OSError, ValueError):
        return False

    for allowed in allowed_dirs:
        try:
            path.relative_to(allowed.resolve())
            return True
        except ValueError:
            continue
    return False


# ---------------------------------------------------------------------------
# Session context relay (parent process → tool-serving subprocess)
# ---------------------------------------------------------------------------

SESSION_DIR_ENV = "LUP_SESSION_DIR"
OUTPUTS_DIR_ENV = "LUP_OUTPUTS_DIR"
GATE_FLAG_ENV = "LUP_GATE_FLAG"
SESSION_ID_ENV = "LUP_SESSION_ID"
TASK_ID_ENV = "LUP_TASK_ID"
REALTIME_DIR_ENV = "LUP_REALTIME_DIR"


class SessionContext(BaseModel):
    """Session context relayed to tool-serving subprocesses via env vars.

    The Codex/OpenAI adapters expose lup's MCP tools through an external
    stdio subprocess (``lup-devtools agent serve-tools``). Tools that
    need session state — reflect, submit_output, sandbox — receive it
    through this contract. The producer (the adapter builder) and the
    consumer (serve-tools) share this one definition, so the env vars
    cannot drift apart.
    """

    session_dir: Path
    outputs_dir: Path | None = None
    gate_flag: Path | None = None
    session_id: str | None = None
    task_id: str | None = None
    realtime_dir: Path | None = None

    def to_env(self) -> dict[str, str]:
        """Serialize to the env vars consumed by read_session_context()."""
        env = {SESSION_DIR_ENV: str(self.session_dir)}
        if self.outputs_dir is not None:
            env[OUTPUTS_DIR_ENV] = str(self.outputs_dir)
        if self.gate_flag is not None:
            env[GATE_FLAG_ENV] = str(self.gate_flag)
        if self.session_id:
            env[SESSION_ID_ENV] = self.session_id
        if self.task_id:
            env[TASK_ID_ENV] = self.task_id
        if self.realtime_dir is not None:
            env[REALTIME_DIR_ENV] = str(self.realtime_dir)
        return env


def read_session_context(
    environ: Mapping[str, str] | None = None,
) -> SessionContext | None:
    """Read a SessionContext from env vars, or None when not in a session.

    Returns None when ``LUP_SESSION_DIR`` is unset — the marker that the
    process was not launched by an adapter (e.g. plain devtools usage).
    """
    env = os.environ if environ is None else environ
    session_dir = env.get(SESSION_DIR_ENV)
    if not session_dir:
        return None

    def path_or_none(key: str) -> Path | None:
        value = env.get(key)
        return Path(value) if value else None

    return SessionContext(
        session_dir=Path(session_dir),
        outputs_dir=path_or_none(OUTPUTS_DIR_ENV),
        gate_flag=path_or_none(GATE_FLAG_ENV),
        session_id=env.get(SESSION_ID_ENV) or None,
        task_id=env.get(TASK_ID_ENV) or None,
        realtime_dir=path_or_none(REALTIME_DIR_ENV),
    )
