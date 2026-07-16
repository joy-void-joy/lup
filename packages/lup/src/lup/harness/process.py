"""Concrete local process launching for typed harness boundaries."""

import os
from pathlib import Path

import sh

from lup.harness.contracts import ProcessLauncher
from lup.harness.models import ExitStatus, LaunchRequest


def decoded_output(value: bytes | str | None) -> str:
    """Decode output captured by ``sh`` without discarding framing."""
    if value is None:
        return ""
    return (
        value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    )


class LocalProcessLauncher(ProcessLauncher):
    """Run an explicitly named executable with captured output and no shell."""

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
