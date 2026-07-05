"""Persistent in-container Python REPL over Docker's exec socket.

Holds the JSON-line protocol server script that runs inside the container,
the variant-shape socket helpers docker-py hands back, and the ``ReplSession``
that streams code to the REPL and reads its multiplexed frames. State (the
Python namespace) persists across calls like notebook cells.
"""

import json
import logging
import time
from typing import Protocol

try:
    import docker
except ImportError as exc:
    raise ImportError(
        "lup.sandbox requires the 'docker' extra. Install with: uv sync --extra docker"
    ) from exc
from docker.models.containers import Container
from docker.utils.socket import SocketError, next_frame_header, read_exactly

from lup.sandbox.models import (
    CodeExecutionTimeoutError,
    ExecuteCodeResult,
    ReplCrashedError,
    SandboxNotInitializedError,
)
from lup.sandbox.process import compute_deadline

logger = logging.getLogger(__name__)


class ExecSocket(Protocol):
    """Opaque handle to docker-py's exec stream.

    docker-py hands back a different concrete socket per platform and
    version (a raw ``socket.socket``, a ``SocketIO`` wrapper, an SSH/npipe
    socket) with no shared typed surface, so the REPL holds the handle
    opaquely and reaches close, read, write, and timeout — which differ by
    variant — dynamically through the module helpers below.
    """


def socket_send(sock: ExecSocket, data: bytes) -> None:
    """Write bytes to a docker exec socket across its variant shapes.

    A raw socket exposes ``sendall`` (on itself or the wrapped ``_sock``);
    a ``SocketIO`` wrapper exposes ``write`` instead.
    """
    raw = getattr(sock, "_sock", sock)
    sender = getattr(raw, "sendall", None)
    if sender is not None:
        sender(data)
    else:
        getattr(sock, "write")(data)


def socket_close(sock: ExecSocket) -> None:
    """Close a docker exec socket and the buffered response behind it."""
    response = getattr(sock, "_response", None)
    if response is not None:
        response.close()
    getattr(sock, "close")()


def socket_set_timeout(sock: ExecSocket, timeout: float | None) -> None:
    """Set the timeout on whichever variant carries ``settimeout``.

    ``timeout=None`` restores blocking mode. The raw socket may be the
    handle itself or the wrapped ``_sock``.
    """
    for candidate in (sock, getattr(sock, "_sock", None)):
        setter = getattr(candidate, "settimeout", None)
        if setter is not None:
            setter(timeout)
            return


REPL_SERVER_SCRIPT = r"""
# Persistent Python REPL server — runs inside the Docker container.
#
# Protocol (JSON-line over stdin/stdout):
#   Request:  {"code": "...", "timeout": 30}
#   Response: {"exit_code": 0, "stdout": "...", "stderr": "...", "duration_ms": 42}
#
# - All exec() calls share a single namespace, so variables and imports
#   persist across requests (like notebook cells).
# - sys.stdin/stdout/stderr are redirected to /dev/null so user code cannot
#   interfere with the JSON protocol.  The original streams are saved as
#   _proto_in/_proto_out for protocol I/O.
# - SIGALRM enforces per-request timeouts (exit_code 124 on expiry).
# - stdout/stderr are capped at 1 MB to prevent memory blowouts.

import json, signal, sys, time, traceback
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

_MAX_OUTPUT = 1_048_576
_namespace = {"__builtins__": __builtins__}

class _Timeout(Exception):
    pass

def _alarm(signum, frame):
    raise _Timeout()

# Hijack standard streams: save originals for protocol, redirect to /dev/null
# so user code (print, input) can't corrupt the JSON wire format.
_proto_in = sys.stdin
_proto_out = sys.stdout
sys.stdin = open("/dev/null", "r")
sys.stdout = open("/dev/null", "w")
sys.stderr = open("/dev/null", "w")

for _line in _proto_in:
    _line = _line.strip()
    if not _line:
        continue
    try:
        _req = json.loads(_line)
    except json.JSONDecodeError:
        _proto_out.write(json.dumps({"exit_code": 1, "stdout": "", "stderr": "Invalid JSON", "duration_ms": 0}) + "\n")
        _proto_out.flush()
        continue

    _code = _req.get("code", "")
    _timeout = _req.get("timeout", 30)
    _so = StringIO()
    _se = StringIO()
    _ec = 0
    _t0 = time.perf_counter()
    _old_alarm = signal.signal(signal.SIGALRM, _alarm)
    try:
        if _timeout > 0:
            signal.alarm(_timeout)
        with redirect_stdout(_so), redirect_stderr(_se):
            exec(compile(_code, "<cell>", "exec"), _namespace)
    except _Timeout:
        _ec = 124
        _se.write(f"Execution timed out after {_timeout} seconds\n")
    except SystemExit as _e:
        _ec = _e.code if isinstance(_e.code, int) else 1
    except BaseException:
        _ec = 1
        _se.write(traceback.format_exc())
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, _old_alarm)

    _ms = int((time.perf_counter() - _t0) * 1000)
    _proto_out.write(json.dumps({
        "exit_code": _ec,
        "stdout": _so.getvalue()[:_MAX_OUTPUT],
        "stderr": _se.getvalue()[:_MAX_OUTPUT],
        "duration_ms": _ms,
    }) + "\n")
    _proto_out.flush()
"""


class ReplSession:
    """Persistent Python REPL inside a Docker container.

    Communicates over Docker's exec socket API using a JSON-line protocol.
    The REPL maintains a shared namespace across code executions, so
    variables and imports persist between calls.
    """

    def __init__(
        self,
        client: docker.DockerClient,
        container: Container,
        environment: dict[str, str],
    ) -> None:
        self.client = client
        self.container = container
        self.environment = environment
        self.sock: ExecSocket | None = None
        self.exec_id: str | None = None

    def start(self) -> None:
        """Start the REPL process and verify it responds."""
        exec_result: dict[str, str] = self.client.api.exec_create(
            self.container.id,
            ["python", "-u", "/workspace/.repl_server.py"],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=False,
            workdir="/workspace",
            environment=self.environment or None,
        )
        self.exec_id = exec_result["Id"]
        self.sock = self.client.api.exec_start(self.exec_id, socket=True)
        result = self.execute("pass", timeout_seconds=10)
        if result["exit_code"] != 0:
            raise RuntimeError(f"REPL startup failed: {result['stderr']}")
        logger.info("Persistent REPL started")

    def stop(self) -> None:
        """Close the socket connection to the REPL."""
        if self.sock is not None:
            try:
                socket_close(self.sock)
            except (OSError, ValueError):
                # Socket-layer close failures (already closed, broken pipe)
                # are expected during teardown; anything else propagates.
                logger.debug("Closing REPL connection failed", exc_info=True)
            self.sock = None
        self.exec_id = None

    def execute(self, code: str, timeout_seconds: int) -> ExecuteCodeResult:
        """Send code to the REPL and return the result.

        Non-positive ``timeout_seconds`` disables both the in-sandbox
        SIGALRM and the host-side deadline — the call blocks until the
        code finishes.
        """
        if self.sock is None:
            raise SandboxNotInitializedError("REPL not connected")

        request = json.dumps({"code": code, "timeout": timeout_seconds}) + "\n"
        self.send(request.encode("utf-8"))

        deadline = compute_deadline(timeout_seconds)
        try:
            response = self.recv_response(deadline)
        except (SocketError, OSError) as e:
            raise ReplCrashedError(f"REPL exited: {e}") from e

        if response.get("exit_code") == 124:
            raise CodeExecutionTimeoutError(
                f"Code execution timed out after {timeout_seconds} seconds"
            )

        return ExecuteCodeResult(
            exit_code=int(response.get("exit_code", 1)),
            stdout=str(response.get("stdout", "")),
            stderr=str(response.get("stderr", "")),
            duration_ms=int(response.get("duration_ms", 0)),
        )

    def send(self, data: bytes) -> None:
        """Write raw bytes to the exec socket stdin."""
        if self.sock is None:
            raise ReplCrashedError("REPL not connected")
        try:
            socket_send(self.sock, data)
        except (BrokenPipeError, OSError) as e:
            raise ReplCrashedError(f"REPL write failed: {e}") from e

    def recv_response(self, deadline: float | None) -> dict[str, int | str]:
        """Read Docker multiplex frames until a complete JSON line arrives.

        ``deadline=None`` blocks indefinitely (no-timeout requests).
        """
        stdout_buf = b""
        while True:
            if deadline is None:
                self.set_socket_timeout(None)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplCrashedError("Timed out waiting for REPL response")
                self.set_socket_timeout(remaining)

            stream_type, size = next_frame_header(self.sock)
            if size < 0:
                raise ReplCrashedError("REPL EOF")

            data = read_exactly(self.sock, size)
            match stream_type:
                case 1:  # stdout
                    stdout_buf += data
                    if b"\n" in stdout_buf:
                        line, _, _ = stdout_buf.partition(b"\n")
                        text = line.decode("utf-8", errors="replace")
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError as e:
                            raise ReplCrashedError(
                                f"REPL returned non-JSON: {text[:200]}"
                            ) from e
                case 2:  # stderr
                    logger.debug(
                        "REPL stderr: %s", data.decode("utf-8", errors="replace")
                    )

    def set_socket_timeout(self, timeout: float | None) -> None:
        """Set timeout on the underlying socket (None = blocking mode)."""
        if self.sock is not None:
            socket_set_timeout(self.sock, timeout)
