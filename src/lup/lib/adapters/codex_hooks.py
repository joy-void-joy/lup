"""Codex hook adapter — translates lup hook policies to Codex command hooks.

Codex uses config.toml command hooks with PreToolUse/PostToolUse/
PermissionRequest/Stop events. Each hook script receives JSON on stdin
and emits JSON to stdout with allow/deny/systemMessage fields.

This module provides:
- ``build_permission_hooks()``: Generates CodexHookConfig entries for
  directory-based read/write access control (equivalent to Claude's
  create_permission_hooks).
- ``build_reflection_gate_hook()``: Generates a CodexHookConfig entry
  for the reflection gate (equivalent to Claude's reflection gate hook).
- ``format_codex_hook_output()``: Formats a hook decision as Codex JSON.

The hook scripts themselves are standalone Python scripts that import
from this module. They read hook input from stdin, apply policy logic,
and write the decision to stdout.
"""

import json
import sys
from pathlib import Path
from typing import Literal, TypedDict

from lup.lib.adapters.codex import CodexHookConfig


class CodexHookInput(TypedDict, total=False):
    """Input JSON received by Codex hook scripts on stdin."""

    hook_event_name: str
    tool_name: str
    tool_input: dict[str, str]


class CodexHookOutput(TypedDict, total=False):
    """Output JSON emitted by Codex hook scripts to stdout."""

    decision: Literal["allow", "deny", "block"]
    reason: str
    systemMessage: str


def format_codex_hook_output(
    decision: Literal["allow", "deny", "block"],
    reason: str = "",
) -> CodexHookOutput:
    """Format a hook decision as Codex-compatible JSON."""
    output = CodexHookOutput(decision=decision)
    if reason:
        output["reason"] = reason
    return output


def read_hook_input() -> CodexHookInput:
    """Read hook input JSON from stdin (used by hook scripts)."""
    raw = sys.stdin.read()
    return json.loads(raw)


def write_hook_output(output: CodexHookOutput) -> None:
    """Write hook output JSON to stdout (used by hook scripts)."""
    sys.stdout.write(json.dumps(output))
    sys.stdout.flush()


def build_permission_hooks(
    rw_dirs: list[Path],
    ro_dirs: list[Path],
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate Codex hook configs for directory-based permission control.

    Creates a PreToolUse hook config that runs a permission check script.
    The script path must be written to disk separately (see
    write_permission_hook_script).

    Args:
        rw_dirs: Directories where Write/Edit/Read are allowed.
        ro_dirs: Additional directories where only Read is allowed.
        script_dir: Directory where hook scripts will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_permission_hook.py"
    write_permission_hook_script(script_path, rw_dirs, ro_dirs)

    return [
        CodexHookConfig(
            event="PreToolUse",
            command=f"python3 {script_path}",
        ),
    ]


def write_permission_hook_script(
    script_path: Path,
    rw_dirs: list[Path],
    ro_dirs: list[Path],
) -> None:
    """Write a standalone permission hook script to disk.

    The script reads CodexHookInput from stdin, checks directory
    permissions, and writes CodexHookOutput to stdout.
    """
    rw_list = json.dumps([str(d) for d in rw_dirs])
    ro_list = json.dumps([str(d) for d in ro_dirs])

    script = f'''\
"""Auto-generated Codex permission hook script."""
import json
import sys
from pathlib import Path

RW_DIRS = [Path(p) for p in {rw_list}]
RO_DIRS = [Path(p) for p in {ro_list}]
ALL_READABLE = RW_DIRS + RO_DIRS


def path_is_under(file_path: str, dirs: list[Path]) -> bool:
    p = Path(file_path).resolve()
    return any(p == d or d in p.parents for d in dirs)


def check_permission(hook_input: dict) -> dict:
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {{}})

    match tool_name:
        case "Write" | "Edit":
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return {{"decision": "allow"}}
            if path_is_under(file_path, RW_DIRS):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": f"{{tool_name}} denied outside RW dirs"}}

        case "Read":
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return {{"decision": "allow"}}
            if path_is_under(file_path, ALL_READABLE):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": "Read denied outside allowed dirs"}}

        case "Glob" | "Grep":
            file_path = tool_input.get("path", "")
            if not file_path:
                return {{"decision": "deny", "reason": f"Path required for {{tool_name}}"}}
            if path_is_under(file_path, ALL_READABLE):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": f"{{tool_name}} denied outside allowed dirs"}}

        case _:
            return {{"decision": "allow"}}


raw = sys.stdin.read()
hook_input = json.loads(raw)
result = check_permission(hook_input)
sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")


def build_reflection_gate_hook(
    gate_flag_path: Path,
    gated_tool: str,
    reflection_tool_name: str,
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate a Codex hook config for the reflection gate.

    The gate blocks gated_tool until a flag file exists at
    gate_flag_path (set by the reflect tool's MCP handler).

    Args:
        gate_flag_path: Path to the flag file that indicates reflection occurred.
        gated_tool: Tool name to block (e.g., "StructuredOutput").
        reflection_tool_name: Name shown in the denial message.
        script_dir: Directory where hook scripts will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_reflection_gate_hook.py"
    write_reflection_gate_script(
        script_path, gate_flag_path, gated_tool, reflection_tool_name
    )

    return [
        CodexHookConfig(
            event="PreToolUse",
            matcher=gated_tool,
            command=f"python3 {script_path}",
        ),
    ]


def write_reflection_gate_script(
    script_path: Path,
    gate_flag_path: Path,
    gated_tool: str,
    reflection_tool_name: str,
) -> None:
    """Write a standalone reflection gate hook script to disk."""
    script = f'''\
"""Auto-generated Codex reflection gate hook script."""
import json
import sys
from pathlib import Path

GATE_FLAG = Path("{gate_flag_path}")
GATED_TOOL = "{gated_tool}"
REFLECTION_TOOL = "{reflection_tool_name}"

raw = sys.stdin.read()
hook_input = json.loads(raw)
tool_name = hook_input.get("tool_name", "")

if tool_name == GATED_TOOL and not GATE_FLAG.exists():
    result = {{
        "decision": "deny",
        "reason": f"You must call {{REFLECTION_TOOL}}() before {{GATED_TOOL}}. Reflect first.",
    }}
else:
    result = {{"decision": "allow"}}

sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")
