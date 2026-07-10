"""Session context relay: parent process to a tool-serving subprocess.

Backends whose tools run outside the agent process expose lup's MCP
tools through an external stdio subprocess (``lup-devtools agent
serve-tools``). The Codex runtime does not pass the parent's shell env to
that subprocess, so session state the tools need — reflect, submit_output,
sandbox, realtime relay — crosses the boundary as env vars.

:class:`SessionContext` is that contract. The producer (the subprocess
adapter builder) and the consumer (serve-tools via
:func:`read_session_context`) share this one definition, so the env vars
cannot drift apart. In-process backends run these tools in the agent
process and never touch the relay.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

SESSION_DIR_ENV = "LUP_SESSION_DIR"
OUTPUTS_DIR_ENV = "LUP_OUTPUTS_DIR"
GATE_FLAG_ENV = "LUP_GATE_FLAG"
SESSION_ID_ENV = "LUP_SESSION_ID"
TASK_ID_ENV = "LUP_TASK_ID"
REALTIME_DIR_ENV = "LUP_REALTIME_DIR"


class SessionContext(BaseModel):
    """Session context relayed to tool-serving subprocesses via env vars."""

    session_dir: Path
    outputs_dir: Path | None = None
    gate_flag: Path | None = None
    session_id: str | None = None
    task_id: str | None = None
    realtime_dir: Path | None = None

    def to_env(self) -> dict[str, str]:  # lup: ignore[dict-str-payload] — env map
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
    environ: Mapping[str, str] | None = None,  # lup: ignore[dict-str-payload]
) -> SessionContext | None:
    """Read a SessionContext from env vars, or None when not in a session.

    Returns None when ``LUP_SESSION_DIR`` is unset — the marker that the
    process was not launched by an adapter (e.g. plain devtools usage).
    This module IS the subprocess env boundary, so it reads ``os.environ``
    directly rather than through settings.
    """
    env = os.environ if environ is None else environ  # lup: ignore[os-environ]
    session_dir = env.get(SESSION_DIR_ENV)  # lup: ignore[dict-get] — env map
    if not session_dir:
        return None

    def path_or_none(key: str) -> Path | None:
        value = env.get(key)  # lup: ignore[dict-get] — env map
        return Path(value) if value else None

    return SessionContext(
        session_dir=Path(session_dir),
        outputs_dir=path_or_none(OUTPUTS_DIR_ENV),
        gate_flag=path_or_none(GATE_FLAG_ENV),
        session_id=env.get(SESSION_ID_ENV) or None,  # lup: ignore[dict-get]
        task_id=env.get(TASK_ID_ENV) or None,  # lup: ignore[dict-get]
        realtime_dir=path_or_none(REALTIME_DIR_ENV),
    )
