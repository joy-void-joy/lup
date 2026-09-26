"""Pure host-side helpers for the sandbox: output, liveness, and deadlines.

Output decoding, process-liveness checks (with PID-reuse protection), and the
host-side request deadline. All operate on the host OS and stdlib alone — no
Docker client — so they are independently testable and importable without the
``docker`` extra.
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

from lup.types import EnvVars


def decode_output(output: bytes | Iterator[bytes] | None) -> str:
    """Decode bytes output to string, handling None and errors."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return b"".join(output).decode("utf-8", errors="replace")


def process_start_token(pid: int) -> str | None:
    """Return a stable creation-time token for ``pid``, or None if unknown.

    Distinguishes a live owner from a reused PID: two processes that
    happen to share a PID number across time get different tokens. On
    Linux this is the ``starttime`` field of ``/proc/<pid>/stat`` (clock
    ticks since boot); elsewhere there is no portable stdlib source, so
    callers fall back to a liveness-only signal.
    """
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    # Fields: "pid (comm) state ppid ...". comm may contain spaces and
    # parentheses, so split on the final ')' — every later field is a
    # plain space-separated token. starttime is field 22 (1-indexed),
    # i.e. index 19 of the post-comm remainder (which begins at field 3).
    rest = raw.rpartition(")")[2].split()  # lup: ignore[string-split] — /proc stat
    if len(rest) < 20:
        return None
    return rest[19]


def running_environments() -> Iterator[EnvVars]:
    """The environment of every process this user may read, where the system shows it.

    Linux keeps each in ``/proc/<pid>/environ``; another user's process, one
    that ended while it was read, and a system without ``/proc`` yield
    nothing, so a caller treats the answer as what is known to run.
    """
    table = Path("/proc")
    if not table.is_dir():
        return
    for entry in table.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "environ").read_bytes()
        except OSError:
            continue
        # lup: ignore[string-split] — /proc environ is NUL-separated NAME=value records
        records = [os.fsdecode(record).partition("=") for record in raw.split(b"\0")]
        yield {name: value for name, _equals, value in records if name}


def process_is_zombie(pid: int) -> bool:
    """Whether ``pid`` has exited and only waits for its parent to collect it.

    A zombie still answers a signal, so :func:`process_is_alive` counts it;
    anything asking whether a process still *runs* asks this too.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    rest = raw.rpartition(")")[2].split()  # lup: ignore[string-split] — /proc stat
    return bool(rest) and rest[0] == "Z"


def process_is_alive(pid: int, start_token: str | None) -> bool:
    """Whether the process that created a container is still running.

    ``start_token`` guards against PID reuse: when present it must match
    the live process's current token, otherwise the original owner is
    gone and a new process merely inherited its PID number.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive but owned by another user — treat as live.
        return True
    except OSError:
        return False
    if start_token is None:
        return True
    current = process_start_token(pid)
    return current is None or current == start_token


def compute_deadline(timeout_seconds: int, grace_seconds: float = 5.0) -> float | None:
    """Host-side deadline (monotonic clock) for a REPL request.

    Returns ``None`` for non-positive timeouts: "no timeout" means no
    host deadline at all, mirroring the in-sandbox behavior where the
    REPL server skips ``signal.alarm`` for non-positive values. Killing
    the connection after a fixed grace would lose the REPL state for
    deliberately long-running code.

    The grace period covers protocol overhead on top of the in-sandbox
    timeout, so the in-sandbox SIGALRM fires first under normal operation.
    """
    if timeout_seconds <= 0:
        return None
    return time.monotonic() + timeout_seconds + grace_seconds
