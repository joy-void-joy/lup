"""The Codex runtime's ``config_overrides`` builders.

The Codex app-server is a Rust subprocess configured through TOML; every
capability the seam wires in lands here as override lines — external MCP
tool servers and the native workspace-write sandbox.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from lup.types import EnvVars


def build_mcp_config_overrides(
    command: Sequence[str],
    servers: Sequence[str],
    env: EnvVars | None = None,
) -> list[str]:
    """Build config_overrides serving tool groups as external MCP servers.

    The Codex app-server is a Rust subprocess with no in-process tool
    registration, so a caller's tool groups reach it as external MCP
    servers in TOML config. One entry is emitted per server group so tool
    names match the in-process path exactly (``mcp__notes__submit_output``,
    ``mcp__sandbox__execute_code``); each subprocess serves one group.

    Args:
        command: The caller's serving command line (executable plus base
            arguments); the ``--server <name>`` selector is appended per
            group.
        servers: Server groups to register.
        env: Session-context env vars for the subprocesses (see
            :class:`lup.workspace.context.SessionContext`).
    """
    executable, *base_args = command
    overrides: list[str] = []  # lup: ignore[empty-collection] — per-server fold
    for name in servers:
        args = [*base_args, "--server", name]
        overrides.append(f'mcp_servers.{name}.command="{executable}"')
        overrides.append(f"mcp_servers.{name}.args={json.dumps(args)}")
        for key, value in (env or {}).items():
            overrides.append(f'mcp_servers.{name}.env.{key}="{value}"')
    return overrides


def build_sandbox_config_overrides(writable_roots: Sequence[Path]) -> list[str]:
    """Native Codex filesystem enforcement via workspace-write sandbox.

    Replaces hook-script permission enforcement on Codex: the runtime's
    own sandbox confines writes to the workspace plus these roots. (A
    live probe showed config.toml command hooks never fire on current
    codex builds, so enforcement must be native or in-tool.)
    """
    roots_json = json.dumps([str(p) for p in writable_roots])
    return [
        'sandbox_mode="workspace-write"',
        f"sandbox_workspace_write.writable_roots={roots_json}",
    ]
