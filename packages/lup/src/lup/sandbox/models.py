"""Data models and error types for the sandbox.

The tool input schemas, code/install result shapes, the container mount
topology, and the sandbox's exception hierarchy — the shared vocabulary the
REPL transport and the container lifecycle both speak. No Docker dependency,
so importing this never requires the ``docker`` extra.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

NetworkMode = Literal["bridge", "none"]
MountMode = Literal["rw", "ro"]

DEFAULT_PRE_INSTALL: tuple[str, ...] = (  # lup: ignore[tuple-shape] — immutable default
    "requests",
    "pandas",
    "numpy",
    "beautifulsoup4",
    "lxml",
)
"""Packages pre-installed in new containers by default."""


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


class SandboxNotInitializedError(RuntimeError):
    """Raised when sandbox operations are called on an inactive sandbox."""


class CodeExecutionTimeoutError(RuntimeError):
    """Raised when code execution exceeds the timeout."""


class ReplCrashedError(RuntimeError):
    """Raised when the persistent REPL process has exited unexpectedly."""
