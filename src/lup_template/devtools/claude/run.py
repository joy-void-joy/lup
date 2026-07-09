"""The ``lup-devtools claude`` runner: launch Claude Code wired for this project.

It execs the ``claude`` CLI with:

- the project's MCP tools attached (the ``serve-tools`` stdio server),
- the local lup plugin loaded live from disk (``--plugin-dir``, so edits
  show up without a reinstall — no marketplace, no cache, no collision),
- and, when a profile is selected, that profile's Claude config dir
  (``CLAUDE_CONFIG_DIR``).

Extra arguments pass straight through to ``claude`` (e.g. ``--resume``).
"""

import json
import os
import tempfile

import sh
import typer

from lup.adapters.profiles.claude.profile import CONFIG_DIR_ENV, ClaudeProfile
from lup.workspace.paths import project_root

MCP_SERVER_NAME = "notes"


def write_mcp_config() -> str:
    """Write a temp MCP config running the SDK tools over stdio; return its path."""
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": "uv",
                "args": ["run", "lup-devtools", "agent", "serve-tools"],
            }
        }
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="lup-mcp-", delete=False
    )
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


def run_claude(
    profile: str | None,
    model: str | None,
    no_tools: bool,
    no_plugin: bool,
    with_prompt: bool,
    extra_args: list[str],
) -> None:
    """Exec into ``claude`` configured for this project (see module docstring)."""
    args: list[str] = []

    if model:
        args.extend(["--model", model])

    if with_prompt:
        from lup_template.agent.prompts import get_system_prompt

        args.extend(["--append-system-prompt", get_system_prompt()])

    plugin_dir = project_root() / ".claude" / "plugins" / "lup"
    if not no_plugin:
        if plugin_dir.is_dir():
            args.extend(["--plugin-dir", str(plugin_dir)])
        else:
            typer.echo(
                f"Note: no local plugin at {plugin_dir}; skipping --plugin-dir",
                err=True,
            )

    mcp_path: str | None = None
    if not no_tools:
        mcp_path = write_mcp_config()
        args.extend(["--mcp-config", mcp_path])

    args.extend(extra_args)

    support = ClaudeProfile()
    config_dir = support.resolve_config_dir(profile)
    env = {**os.environ, CONFIG_DIR_ENV: str(config_dir)}
    shown = profile or support.store.active_profile() or "default"
    typer.echo(f"Launching claude (profile: {shown}, config dir: {config_dir})")

    try:
        sh.Command("claude")(*args, _fg=True, _env=env)
    except sh.CommandNotFound as e:
        typer.echo(
            "Error: 'claude' CLI not found. Install Claude Code first.", err=True
        )
        raise typer.Exit(1) from e
    except sh.ErrorReturnCode:
        pass  # claude exited non-zero or the user quit
    finally:
        if mcp_path:
            try:
                os.unlink(mcp_path)
            except OSError:
                pass
