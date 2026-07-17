"""Local native-executable launching and its request/status vocabulary.

Implements the ``ProcessLauncher`` seam for everything that must run a
native CLI: devtools harness launch and doctor flows and the resolver's git
and skill invocations. ``LaunchRequest``/``ExitStatus`` are defined here
because launchers are their only producers; callers construct requests
through this module.
"""

import os
from pathlib import Path

import sh
from pydantic import BaseModel, ConfigDict, Field

from lup.harness.contracts import ProcessLauncher
from lup.types import EnvVars


class LaunchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    arguments: list[str]
    cwd: Path
    environment: EnvVars = Field(default_factory=dict)


class ExitStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: int
    stdout: str = ""
    stderr: str = ""


def decoded_output(value: bytes | str | None) -> str:
    """Decode output captured by ``sh`` without discarding framing."""
    if value is None:
        return ""
    return (
        value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    )


class LocalProcessLauncher(ProcessLauncher):
    """Run an explicitly named executable with captured output and no shell.

    Output is captured through pipes, never a pseudo-terminal, so children
    that branch on ``isatty`` (pagers, colorizers) emit plain machine output.
    """

    def launch(self, request: LaunchRequest) -> ExitStatus:
        if not request.arguments:
            raise ValueError("a launch request must name an executable")
        executable, *arguments = request.arguments
        command = sh.Command(executable)
        environment = {
            **os.environ,  # lup: ignore[os-environ] — inherit the process boundary
            **request.environment,
        }
        result = command(
            *arguments,
            _cwd=Path(request.cwd),
            _env=environment,
            _ok_code=range(256),
            _return_cmd=True,
            _tty_out=False,
        )
        if not isinstance(result, sh.RunningCommand):
            raise RuntimeError(f"process {executable!r} did not return command state")
        if result.exit_code is None:
            raise RuntimeError(f"process {executable!r} has no terminal exit status")
        return ExitStatus(
            code=result.exit_code,
            stdout=decoded_output(result.stdout),
            stderr=decoded_output(result.stderr),
        )
