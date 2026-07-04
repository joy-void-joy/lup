"""Docker-based Python sandbox for isolated code execution.

Provides a persistent REPL inside a Docker container with state that
survives across calls (variables, imports, data).  Use ``Sandbox`` as a
context manager and call ``run_code`` / ``run_install`` directly, or
expose it to an agent via ``create_tools()`` /
``create_mcp_server()``.

Network modes:
- "bridge": Full network access (default)
- "none": No network access at all

Examples:
    Run code in an isolated sandbox::

        >>> with Sandbox(session_id="demo", shared_dir="/tmp/shared") as sb:
        ...     result = sb.run_code("import math; print(math.pi)")
        ...     result["stdout"]
        '3.141592653589793\\n'
        ...     result["exit_code"]
        0

    State persists across calls within the same session::

        >>> with Sandbox(session_id="demo", shared_dir="/tmp/shared") as sb:
        ...     sb.run_code("x = 42")
        ...     result = sb.run_code("print(x * 2)")
        ...     result["stdout"]
        '84\\n'

    Install packages and create MCP tools for an agent::

        >>> with Sandbox(session_id="demo", shared_dir="/tmp/shared") as sb:
        ...     sb.run_install(["scipy"])
        ...     server = sb.create_mcp_server(name="sandbox")
"""

import io
import json
import logging
import os
import tarfile
import time
from collections.abc import Generator, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol, Self, TypedDict

try:
    import docker
except ImportError as exc:
    raise ImportError(
        "lup.sandbox requires the 'docker' extra. Install with: uv sync --extra docker"
    ) from exc
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container, ExecResult
from docker.utils.socket import SocketError, next_frame_header, read_exactly
from pydantic import BaseModel, Field

from lup.mcp import (
    LupMcpServerConfig,
    LupMcpTool,
    ToolError,
    create_mcp_server,
    lup_tool,
)

logger = logging.getLogger(__name__)

NetworkMode = Literal["bridge", "none"]
MountMode = Literal["rw", "ro"]

DEFAULT_PRE_INSTALL: tuple[str, ...] = (
    "requests",
    "pandas",
    "numpy",
    "beautifulsoup4",
    "lxml",
)
"""Packages pre-installed in new containers by default."""


# --- Pydantic input schemas ---


class ExecuteCodeInput(BaseModel):
    """Input schema for the execute_code tool."""

    code: str = Field(min_length=1)


class InstallPackageInput(BaseModel):
    """Input schema for the install_package tool."""

    packages: list[str] = Field(min_length=1)


class Mount(BaseModel):
    """One entry in the sandbox's container filesystem topology.

    Names a container-side path, what backs it (a host directory for a
    bind, a Docker named volume otherwise), the access mode, and how the
    in-sandbox agent should use it. This is the single source of truth for
    both the Docker ``volumes`` mapping and the code-execution tool
    description, so what the agent is told always matches what is mounted.
    """

    container_path: str = Field(description="Absolute path inside the container")
    source: str = Field(description="Host directory (bind) or Docker volume name")
    kind: Literal["bind", "volume"]
    mode: MountMode
    purpose: str = Field(description="What the agent uses this path for")


# --- TypedDict definitions for result types ---


class ExecuteCodeResult(TypedDict):
    """Result from executing Python code in the sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class InstallPackageResult(TypedDict):
    """Result from installing packages in the sandbox."""

    exit_code: int
    output: str
    packages: list[str]


# --- Output models for lup_tool ---


class ExecuteCodeOutput(BaseModel):
    """Tool output for execute_code (mirrors ExecuteCodeResult)."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class InstallPackageOutput(BaseModel):
    """Tool output for install_package (mirrors InstallPackageResult)."""

    exit_code: int
    output: str
    packages: list[str]


# --- Helper functions ---


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
    rest = raw.rpartition(")")[2].split()
    if len(rest) < 20:
        return None
    return rest[19]


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


# --- Sandbox class ---


class SandboxNotInitializedError(RuntimeError):
    """Raised when sandbox operations are called on an inactive sandbox."""


class CodeExecutionTimeoutError(RuntimeError):
    """Raised when code execution exceeds the timeout."""


class ReplCrashedError(RuntimeError):
    """Raised when the persistent REPL process has exited unexpectedly."""


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


class Sandbox:
    """Docker-based Python sandbox for isolated code execution.

    Each session gets a unique container and volume, so concurrent sessions
    cannot interfere with each other.

    Two paths are mounted (see :meth:`mount_topology`): ``/workspace`` is
    the persistent working directory and process cwd, backed by a private
    Docker volume that is *not* visible on the host; ``/shared`` is a bind
    of ``shared_dir`` for exchanging files with the host. Relative paths in
    executed code resolve under ``/workspace``, so host exchange must use
    the absolute ``/shared`` path.

    Args:
        session_id: Unique identifier for this session (used in container/volume names).
        shared_dir: Host directory bound to /shared for host-sandbox file exchange.
        docker_image: Docker image to use for the sandbox.
        network_mode: Network access level ("bridge" or "none").
        timeout_seconds: Default timeout for code execution.
        pre_install: Packages to pre-install on start. Pass ``None`` to skip.
    """

    DEFAULT_DOCKER_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"

    def __init__(
        self,
        *,
        session_id: str,
        shared_dir: str | Path,
        docker_image: str = DEFAULT_DOCKER_IMAGE,
        network_mode: NetworkMode = "bridge",
        timeout_seconds: int = 30,
        pre_install: Sequence[str] | None = DEFAULT_PRE_INSTALL,
    ) -> None:
        suffix = session_id.replace("/", "-")
        self.container_name = f"lup-sandbox-{suffix}"
        self.docker_image = docker_image
        self.volume_name = f"lup-sandbox-ws-{suffix}"
        self.shared_dir = Path(shared_dir).resolve()
        self.network_mode = network_mode
        self.timeout_seconds = timeout_seconds
        self.pre_install = list(pre_install) if pre_install is not None else None
        self.active_container: Container | None = None
        self.docker_client: docker.DockerClient | None = None
        self.repl: ReplSession | None = None

    @property
    def container(self) -> Container:
        """Get the active container (raises if not initialized)."""
        if self.active_container is None:
            raise SandboxNotInitializedError(
                "Sandbox not initialized. Use 'with Sandbox() as sandbox:' first."
            )
        return self.active_container

    def mount_topology(self) -> list[Mount]:
        """The container's filesystem layout: source, mode, and purpose.

        One source of truth for the Docker ``volumes`` mapping
        (:meth:`start_container`) and the code-execution tool description
        (:meth:`create_tools`), so the paths the agent is told about are
        exactly the paths that exist. Derived from names set in
        ``__init__``, so it is valid before the container starts.
        """
        return [
            Mount(
                container_path="/workspace",
                source=self.volume_name,
                kind="volume",
                mode="rw",
                purpose=(
                    "Persistent working directory and process cwd; survives "
                    "across calls but is not visible on the host."
                ),
            ),
            Mount(
                container_path="/shared",
                source=str(self.shared_dir),
                kind="bind",
                mode="rw",
                purpose=(
                    f"File exchange with the host directory {self.shared_dir}; "
                    "read host inputs and write host outputs here."
                ),
            ),
        ]

    @property
    def is_active(self) -> bool:
        """Check if the sandbox container is currently running."""
        return self.active_container is not None

    SANDBOX_LABEL = "lup.sandbox"
    CREATED_AT_LABEL = "lup.sandbox.created_at"
    VOLUME_LABEL = "lup.sandbox.volume"
    OWNER_PID_LABEL = "lup.sandbox.owner_pid"
    OWNER_START_LABEL = "lup.sandbox.owner_start"
    STALE_AGE_HOURS = 24.0

    def remove_stale_container(self) -> None:
        """Remove a pre-existing container with the same name, if any."""
        if self.docker_client is None:
            return
        try:
            old = self.docker_client.containers.get(self.container_name)
            logger.warning("Removing stale container: %s", self.container_name)
            old.remove(force=True)
        except NotFound:
            pass

    def container_is_orphaned(self, labels: dict[str, str]) -> bool:
        """Decide whether a labelled container belongs to a dead owner.

        Liveness is owner-driven: a container whose creating process is
        still running is kept even past ``STALE_AGE_HOURS`` — this
        library's persistent/relay agents are meant to run indefinitely.
        Only when the owner-pid label is missing (older containers, or
        ones created elsewhere) do we fall back to the age heuristic.
        """
        owner_pid_raw = labels.get(self.OWNER_PID_LABEL)
        if owner_pid_raw is not None:
            try:
                owner_pid = int(owner_pid_raw)
            except ValueError:
                return True
            return not process_is_alive(owner_pid, labels.get(self.OWNER_START_LABEL))
        try:
            created_at = float(labels.get(self.CREATED_AT_LABEL, "0"))
        except ValueError:
            created_at = 0.0
        return created_at <= time.time() - self.STALE_AGE_HOURS * 3600

    def sweep_orphaned_containers(self) -> None:
        """Remove lup sandbox containers whose creating process is gone.

        A SIGKILLed owner leaves its uniquely-named container running
        forever (``remove_stale_container`` only matches this session's
        name). Every lup sandbox is labelled with its owner's PID and
        start token; a container is swept (with its volume) only when
        that owner process is no longer alive, so a long-lived persistent
        session is never destroyed out from under itself.
        """
        if self.docker_client is None:
            return
        try:
            candidates = self.docker_client.containers.list(
                all=True, filters={"label": self.SANDBOX_LABEL}
            )
        except (APIError, DockerException) as e:
            logger.warning("Orphan sweep failed to list containers: %s", e)
            return
        for container in candidates:
            if container.name == self.container_name:
                continue
            labels = container.labels or {}
            if not self.container_is_orphaned(labels):
                continue
            logger.warning("Removing orphaned sandbox container: %s", container.name)
            try:
                container.remove(force=True)
                volume_name = labels.get(self.VOLUME_LABEL)
                if volume_name:
                    self.docker_client.volumes.get(volume_name).remove()
            except (NotFound, APIError, DockerException) as e:
                logger.warning("Orphan cleanup of %s failed: %s", container.name, e)

    def destroy_container(self) -> None:
        """Stop and remove the current container and its session volume."""
        if self.active_container is None:
            return
        try:
            self.active_container.stop(timeout=5)
            self.active_container.remove()
        except (APIError, DockerException) as e:
            logger.warning("Failed to cleanup container: %s", e)
        finally:
            self.active_container = None

        if self.docker_client is not None:
            try:
                vol = self.docker_client.volumes.get(self.volume_name)
                vol.remove()
            except (NotFound, APIError):
                pass

    def write_repl_script(self) -> None:
        """Write the REPL server script into the container via tar archive."""
        script_bytes = REPL_SERVER_SCRIPT.encode("utf-8")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=".repl_server.py")
            info.size = len(script_bytes)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(script_bytes))
        buf.seek(0)
        self.container.put_archive("/workspace", buf)

    def run_pre_install(self) -> None:
        """Pre-install packages for faster agent execution."""
        if self.pre_install is None:
            return
        logger.info("Pre-installing packages: %s", self.pre_install)
        cmd = ["uv", "pip", "install", "--system", *self.pre_install]
        result = self.container.exec_run(cmd, demux=False)
        if result.exit_code != 0:
            logger.warning(
                "Package pre-install failed (exit %d): %s",
                result.exit_code,
                decode_output(result.output)[:500],
            )
        else:
            logger.info("Pre-installed packages successfully")

    def start(self) -> None:
        """Start the sandbox container.

        Creates a new Docker container for code execution. Removes any
        stale container with the same name first.
        """
        self.docker_client = docker.from_env()
        try:
            self.start_container()
        except (APIError, DockerException, OSError, RuntimeError):
            self.stop()
            raise

    def start_container(self) -> None:
        """Create the container and bring up the REPL (assumes a client)."""
        if self.docker_client is None:
            raise SandboxNotInitializedError("Docker client not created")
        self.remove_stale_container()
        self.sweep_orphaned_containers()

        self.shared_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Creating sandbox container: %s (network=%s)",
            self.container_name,
            self.network_mode,
        )
        logger.info("Mounting shared directory: %s -> /shared", self.shared_dir)
        self.active_container = self.docker_client.containers.run(
            self.docker_image,
            name=self.container_name,
            command="sleep infinity",
            detach=True,
            volumes={
                mount.source: {"bind": mount.container_path, "mode": mount.mode}
                for mount in self.mount_topology()
            },
            working_dir="/workspace",
            mem_limit="1g",
            network_mode=self.network_mode,
            labels={
                self.SANDBOX_LABEL: "1",
                self.CREATED_AT_LABEL: str(time.time()),
                self.VOLUME_LABEL: self.volume_name,
                self.OWNER_PID_LABEL: str(os.getpid()),
                self.OWNER_START_LABEL: process_start_token(os.getpid()) or "",
            },
        )

        if self.network_mode != "none":
            self.run_pre_install()

        self.write_repl_script()
        if self.docker_client is None or self.active_container is None:
            raise SandboxNotInitializedError(
                "Docker client or container not available after start"
            )
        self.repl = ReplSession(self.docker_client, self.active_container, {})
        self.repl.start()

    def stop(self) -> None:
        """Stop and remove the sandbox container."""
        if self.repl is not None:
            self.repl.stop()
            self.repl = None
        logger.info("Destroying sandbox container")
        self.destroy_container()
        if self.docker_client is not None:
            self.docker_client.close()
            self.docker_client = None

    def ensure_started(self) -> None:
        """Start the sandbox if it isn't running (lazy initialization).

        Tool handlers call this so a sandbox served by a tool subprocess
        only pays Docker startup when the agent actually executes code.
        """
        if self.repl is None:
            self.start()

    def restart_repl(self) -> None:
        """Restart the REPL, clearing in-memory state.

        Container, filesystem, and installed packages are preserved.
        Only the Python namespace is reset.
        """
        if self.repl is not None:
            self.repl.stop()
        if self.docker_client is None or self.active_container is None:
            raise SandboxNotInitializedError("Sandbox not initialized")
        self.repl = ReplSession(self.docker_client, self.active_container, {})
        self.repl.start()
        logger.info("REPL restarted (state cleared)")

    def __enter__(self) -> Self:
        """Enter context manager, starting the sandbox."""
        started = False
        try:
            self.start()
            started = True
        finally:
            if not started:
                self.stop()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager, stopping the sandbox."""
        self.stop()

    # --- Code execution methods ---

    def run_code(
        self, code: str, timeout_seconds: int | None = None
    ) -> ExecuteCodeResult:
        """Execute Python code in the sandbox's persistent REPL.

        Variables, imports, and data persist between calls within the same
        session. If the REPL crashes, it is restarted automatically (but
        state from previous cells is lost).

        Args:
            code: Python code to execute.
            timeout_seconds: Max execution time in seconds. If None, uses
                the sandbox's default timeout. Zero or negative means no
                timeout at all — no in-sandbox alarm and no host deadline,
                so long-running code completes without losing REPL state.

        Returns:
            Result containing exit code, stdout, stderr, and duration.
        """
        if self.repl is None:
            raise SandboxNotInitializedError("REPL not initialized")
        if timeout_seconds is None:
            timeout_seconds = self.timeout_seconds

        try:
            return self.repl.execute(code, timeout_seconds)
        except ReplCrashedError:
            logger.warning("REPL crashed, restarting")
            self.repl.stop()
            try:
                self.repl.start()
            except (RuntimeError, DockerException, APIError, SocketError):
                logger.exception("REPL restart failed")
                self.repl = None
                raise SandboxNotInitializedError("REPL restart failed")
            return ExecuteCodeResult(
                exit_code=1,
                stdout="",
                stderr=(
                    "REPL process crashed and was restarted. "
                    "Variables from previous cells have been lost. "
                    "Please re-run any setup code."
                ),
                duration_ms=0,
            )

    def run_install(self, packages: list[str]) -> InstallPackageResult:
        """Install Python packages using uv.

        Args:
            packages: List of package names to install.

        Returns:
            Result containing exit code, output, and package list.
        """
        cmd = ["uv", "pip", "install", "--system", *packages]
        result: ExecResult = self.container.exec_run(cmd, demux=False)

        output_text = decode_output(result.output)

        return InstallPackageResult(
            exit_code=result.exit_code if result.exit_code is not None else -1,
            output=output_text,
            packages=packages,
        )

    # --- MCP tool creation ---

    def create_tools(self) -> list[LupMcpTool]:
        """Create MCP tools bound to this sandbox instance.

        Returns:
            List of MCP tools for code execution and package installation.
        """
        timeout_seconds = self.timeout_seconds
        filesystem_text = "\n".join(
            f"  {mount.container_path} ({mount.mode}) — {mount.purpose}"
            for mount in self.mount_topology()
        )
        network_text = (
            "The container has network access. "
            if self.network_mode != "none"
            else "The container has no network access. "
        )

        @lup_tool(
            "Execute Python code in an isolated Docker container with persistent state. "
            "Variables, imports, and data persist between calls — no need to re-define them. "
            f"{network_text}Timeout: {timeout_seconds}s.\n\n"
            f"Filesystem (use absolute paths; the cwd is /workspace):\n{filesystem_text}\n\n"
            "Examples:\n"
            "  execute_code(code='import numpy as np; data = [1,2,3]; print(np.mean(data))')\n"
            "  execute_code(code='# Monte Carlo simulation\\nimport numpy as np\\n"
            "returns = np.random.normal(0.0005, 0.015, (10000, 14))\\n"
            "paths = 100 * np.cumprod(1 + returns, axis=1)\\n"
            "print(np.percentile(paths[:,-1], [10,25,50,75,90]))')\n"
            "State persists: define variables in one call, use them in the next.",
            name="execute_code",
        )
        async def execute_code(inp: ExecuteCodeInput) -> ExecuteCodeOutput:
            try:
                self.ensure_started()
                result = self.run_code(inp.code)
                return ExecuteCodeOutput(**result)
            except SandboxNotInitializedError as e:
                logger.error("Sandbox not initialized: %s", e)
                raise ToolError(f"Sandbox error: {e}") from e
            except CodeExecutionTimeoutError as e:
                logger.warning("Code execution timed out")
                raise ToolError(str(e)) from e
            except (APIError, DockerException) as e:
                logger.exception("Docker execution failed")
                raise ToolError(f"Docker error: {e}") from e

        @lup_tool(
            "Install one or more Python packages from PyPI using uv. Packages persist "
            "in the container across executions.",
            name="install_package",
        )
        async def install_package(inp: InstallPackageInput) -> InstallPackageOutput:
            try:
                self.ensure_started()
                result = self.run_install(inp.packages)
                return InstallPackageOutput(**result)
            except SandboxNotInitializedError as e:
                logger.error("Sandbox not initialized: %s", e)
                raise ToolError(f"Sandbox error: {e}") from e
            except (APIError, DockerException) as e:
                logger.exception("Docker execution failed")
                raise ToolError(f"Docker error: {e}") from e

        return [execute_code, install_package]

    def create_mcp_server(
        self,
        name: str = "sandbox",
        version: str = "1.0.0",
    ) -> LupMcpServerConfig:
        """Create an MCP server with sandbox tools."""
        return create_mcp_server(
            name=name,
            version=version,
            tools=self.create_tools(),
        )


@contextmanager
def sandbox_cleanup(session_id: str, shared_dir: Path) -> Generator[None]:
    """Guarantee a session's sandbox container is removed on exit.

    For sessions whose sandbox lives in a tool subprocess (Codex/OpenAI
    paths): the subprocess owner may kill it without a graceful exit,
    skipping its atexit cleanup. The parent wraps the session in this
    context so the container and volume are removed regardless of how
    the subprocess died.
    """
    try:
        yield
    finally:
        sandbox = Sandbox(session_id=session_id, shared_dir=shared_dir)
        client = docker.from_env()
        sandbox.docker_client = client
        try:
            sandbox.remove_stale_container()
            client.volumes.get(sandbox.volume_name).remove()
        except NotFound:
            pass
        except (APIError, DockerException) as e:
            logger.warning("Post-session sandbox cleanup failed: %s", e)
        finally:
            client.close()
