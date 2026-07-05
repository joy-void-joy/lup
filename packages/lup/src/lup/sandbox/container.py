"""Docker container lifecycle for the Python sandbox.

The ``Sandbox`` context manager owns one session's container and volume:
create, mount, orphan-sweep, run code/installs through the REPL, and destroy.
``sandbox_cleanup`` guarantees teardown for sandboxes served from a tool
subprocess that may die without a graceful exit.

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
import logging
import os
import tarfile
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Self

try:
    import docker
except ImportError as exc:
    raise ImportError(
        "lup.sandbox requires the 'docker' extra. Install with: uv sync --extra docker"
    ) from exc
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container, ExecResult
from docker.utils.socket import SocketError

from lup.mcp import (
    LupMcpServerConfig,
    LupMcpTool,
    ToolError,
    create_mcp_server,
    lup_tool,
)
from lup.sandbox.models import (
    DEFAULT_PRE_INSTALL,
    CodeExecutionTimeoutError,
    ExecuteCodeInput,
    ExecuteCodeOutput,
    ExecuteCodeResult,
    InstallPackageInput,
    InstallPackageOutput,
    InstallPackageResult,
    Mount,
    NetworkMode,
    ReplCrashedError,
    SandboxNotInitializedError,
)
from lup.sandbox.process import decode_output, process_is_alive, process_start_token
from lup.sandbox.repl import REPL_SERVER_SCRIPT, ReplSession

logger = logging.getLogger(__name__)


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

    For sessions whose sandbox lives in a tool subprocess (the
    subprocess-served-tool paths): the subprocess owner may kill it
    without a graceful exit, skipping its atexit cleanup. The parent
    wraps the session in this context so the container and volume are
    removed regardless of how the subprocess died.
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
