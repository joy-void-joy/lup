#!/usr/bin/env python3
"""Generated Claude hook dispatcher over the canonical semantic kernel.

Rendered from lup.adapters.claude.harness by
`uv run lup-devtools harness generate all` — do not edit directly.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from kernel import KernelDecision, decide_edit, decide_fetch, decide_shell
from policy_data import (
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    AUTONOMOUS_AGENT_IDENTITIES,
    DENIED_FETCH_SCOPES,
    MAXIMUM_ADDED_LINES,
    PATH_RULES,
)


def edit_documents(path, old_text, new_text):
    current = Path(path).read_text(encoding="utf-8")
    if current.count(old_text) != 1:
        raise ValueError("Edit preimage must occur exactly once")
    position = current.find(old_text)
    updated = current[:position] + new_text + current[position + len(old_text) :]
    return current, updated


def edit_decision(path_text, before, after, autonomous):
    path = Path(path_text)
    suffix = path.suffix.lower()
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else ()
    return decide_edit(
        path_text,
        before,
        after,
        path_exists=path.exists(),
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=autonomous,
        python_source=suffix in (".py", ".pyi"),
    )


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
    autonomous = agent_type in AUTONOMOUS_AGENT_IDENTITIES
    if name == "Bash":
        return decide_shell(tool_input["command"])
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
