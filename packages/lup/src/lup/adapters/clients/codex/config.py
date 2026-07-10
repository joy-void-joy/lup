"""The Codex runtime's ``config_overrides`` builders.

The Codex app-server is a Rust subprocess configured through TOML; every
capability the seam wires in lands here as override lines — external MCP
tool servers and the native workspace-write sandbox.
"""

import json
from collections.abc import Sequence
from pathlib import Path


def build_mcp_config_overrides(
    serve_tools_command: str = "uv",
    serve_tools_args: list[str] | None = None,
    env: dict[str, str] | None = None,  # lup: ignore[dict-str-payload] — env map
    servers: Sequence[str] = ("notes", "sandbox"),
) -> list[str]:
    """Build config_overrides for lup MCP tools via serve-tools.

    The Codex app-server is a Rust subprocess with no in-process tool
    registration. Tools must be configured as external MCP servers via
    TOML config. This generates the config_overrides that point Codex
    at the lup-devtools serve-tools command.

    One entry is emitted per server group so tool names match the
    Claude path exactly (``mcp__notes__submit_output``,
    ``mcp__sandbox__execute_code``); each subprocess serves one group
    via ``serve-tools --server <name>``.

    Args:
        serve_tools_command: Executable that launches the tool server.
        serve_tools_args: Base arguments for the launcher (the
            ``--server <name>`` selector is appended per group).
        env: Session-context env vars for the subprocesses (see
            :class:`lup.workspace.context.SessionContext`).
        servers: Server groups to register.
    """
    base_args = serve_tools_args or ["run", "lup-devtools", "agent", "serve-tools"]
    overrides: list[str] = []  # lup: ignore[empty-collection] — per-server fold
    for name in servers:
        args = [*base_args, "--server", name]
        overrides.append(f'mcp_servers.{name}.command="{serve_tools_command}"')
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
