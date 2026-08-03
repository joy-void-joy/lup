#!/usr/bin/env python3
"""Generated Claude hook dispatcher over the canonical semantic kernel.

Rendered from lup.adapters.claude.assets.policy_dispatcher by
`uv run lup-devtools harness generate all` — do not edit directly.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[1] / "runtime")
)  # lup: Why do we have sys.path.insert here?
from kernel.decision import (
    KernelDecision,
)  # lup: I'm not comfortable having invalid python code here. Can't we compile it or something?
from kernel.edit import decide_edit
from kernel.fetch import decide_fetch
from kernel.lex import shell_write_targets
from kernel.shell import decide_shell
from policy_data import (
    AGENT_IDENTITY_ENV,
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    AUTONOMOUS_AGENT_IDENTITIES,
    CONCERN_ALLOWANCES_ENV,
    DENIED_FETCH_SCOPES,
    MAXIMUM_ADDED_LINES,
    PATH_ROLES,
    PATH_RULES,
    SHELL_RULES,
)


def sandbox_active():
    environ = os.environ  # lup: ignore[os-environ]
    return "LUP_SANDBOX_ACTIVE" in environ and environ["LUP_SANDBOX_ACTIVE"] == "1"


def managed_script_roots() -> list[str]:
    """Return absolute package roots installed and trusted by Claude Code.

    The workspace-local plugin directory is deliberately not a root: it is
    agent-adjacent and verified only at launch, so an approved write there
    must not grant silent execution rights for the rest of the session.
    """
    environ = os.environ  # lup: ignore[os-environ]
    if "CLAUDE_CONFIG_DIR" in environ:
        home = Path(environ["CLAUDE_CONFIG_DIR"])
    elif "HOME" in environ:
        home = Path(environ["HOME"]) / ".claude"
    else:
        return []
    if not home.is_absolute():
        return []
    return [str(home / "skills"), str(home / "plugins" / "cache")]


def edit_documents(path, old_text, new_text, replace_all):
    """Build the before and after documents one Edit call would produce.

    A `replace_all` edit rewrites every occurrence, so requiring exactly one
    would reject the tool's own semantics — and a rejection here is not a
    judgment: it reaches the agent as an approval prompt that no rule
    produced, which is how a whole class of edit went ungoverned.
    """
    current = Path(path).read_text(encoding="utf-8")
    occurrences = current.count(old_text)
    if occurrences == 0:
        raise ValueError("Edit preimage does not occur in the file")
    if replace_all:
        # Reproducing the Edit tool's own splice: source text has no parser
        # here, and the preimage is a literal the caller already chose.
        return current, current.replace(old_text, new_text)  # lup: ignore[string-replace]
    if occurrences != 1:
        raise ValueError("Edit preimage must occur exactly once")
    position = current.find(old_text)
    updated = current[:position] + new_text + current[position + len(old_text) :]
    return current, updated


def workspace_path(path_text):
    path = Path(path_text)
    if not path.is_absolute():
        return path_text
    root = Path.cwd().resolve()
    resolved = path.resolve()
    if resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    return path_text


def edit_decision(path_text, before, after, autonomous):
    path = Path(path_text)
    suffix = path.suffix.lower()
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else ()
    return decide_edit(
        workspace_path(path_text),
        before,
        after,
        path_exists=path.exists(),
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        path_roles=PATH_ROLES,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=autonomous,
        allowances=granted_allowances(),
        python_source=suffix in (".py", ".pyi"),
    )


def existing_write_targets(command):
    """Report which of a command's write targets already exist on disk.

    The kernel never reads the filesystem, so it cannot tell creating a file
    from overwriting one. Resolving that here keeps the decision itself a
    pure function of the command text and this list.
    """
    return [
        target
        for target in shell_write_targets(command)
        if (Path.cwd() / target).exists()
    ]


def declared_identity():
    """The identity this session's launcher declared, if it declared one."""
    environ = os.environ  # lup: ignore[os-environ]
    return environ[AGENT_IDENTITY_ENV] if AGENT_IDENTITY_ENV in environ else ""


def granted_allowances():
    """Edit gates a human approved for the concern this session is working."""
    environ = os.environ  # lup: ignore[os-environ]
    if CONCERN_ALLOWANCES_ENV not in environ:
        return []
    declared = json.loads(environ[CONCERN_ALLOWANCES_ENV] or "[]")
    return [str(name) for name in declared]


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
    autonomous = (
        agent_type in AUTONOMOUS_AGENT_IDENTITIES
        or declared_identity() in AUTONOMOUS_AGENT_IDENTITIES
    )
    if name == "Bash":
        unsandboxed = (
            "dangerouslyDisableSandbox" in tool_input
            and tool_input["dangerouslyDisableSandbox"] is True
        )
        return decide_shell(
            tool_input["command"],
            SHELL_RULES,
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
            sandboxed=sandbox_active() and not unsandboxed,
            trusted_script_roots=managed_script_roots(),
            path_roles=PATH_ROLES,
            existing_targets=existing_write_targets(tool_input["command"]),
        )
    if name == "WebFetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "Edit":
        before, after = edit_documents(
            tool_input["file_path"],
            tool_input["old_string"],
            tool_input["new_string"],
            "replace_all" in tool_input and tool_input["replace_all"] is True,
        )
        return edit_decision(tool_input["file_path"], before, after, autonomous)
    if name == "Write":
        path = Path(tool_input["file_path"])
        return edit_decision(
            tool_input["file_path"],
            path.read_text(encoding="utf-8") if path.exists() else None,
            tool_input["content"],
            autonomous,
        )
    return KernelDecision("ask", "tool is not classified")


def rendered(decision):
    if decision.effect == "defer":
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.effect,
            "permissionDecisionReason": decision.reason,
        }
    }


def main():
    try:
        decision = dispatch(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        decision = KernelDecision(
            "ask", f"Malformed hook input requires approval: {error}"
        )
    json.dump(rendered(decision), sys.stdout)


if __name__ == "__main__":
    main()
