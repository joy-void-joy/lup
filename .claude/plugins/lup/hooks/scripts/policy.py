#!/usr/bin/env python3
"""Generated Claude hook dispatcher over the bundled semantic runtime."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from policy import Decision, decide_edit, decide_fetch, decide_shell

ALLOWED_FETCH_SCOPES = [
    {
        "origin": "https://docs.claude.com/",
        "path_prefix": "/",
    },
    {
        "origin": "http://docs.claude.com/",
        "path_prefix": "/",
    },
    {
        "origin": "https://ai.pydantic.dev/",
        "path_prefix": "/",
    },
    {
        "origin": "http://ai.pydantic.dev/",
        "path_prefix": "/",
    },
]
DENIED_FETCH_SCOPES = []  # lup: ignore[empty-collection]
PROTECTED_EDIT_ROOTS = [
    ".claude",
    "tmp",
    "pyproject.toml",
]


def edit_documents(path, old_text, new_text):
    current = Path(path).read_text(encoding="utf-8")
    if current.count(old_text) != 1:
        raise ValueError("Edit preimage must occur exactly once")
    position = current.find(old_text)
    updated = current[:position] + new_text + current[position + len(old_text) :]
    return current, updated


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
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
        return decide_edit(
            tool_input["file_path"],
            before,
            after,
            PROTECTED_EDIT_ROOTS,
            agent_type,
        )
    if name == "Write":
        path = Path(tool_input["file_path"])
        return decide_edit(
            tool_input["file_path"],
            path.read_text(encoding="utf-8") if path.exists() else None,
            tool_input["content"],
            PROTECTED_EDIT_ROOTS,
            agent_type,
        )
    return Decision("ask", "tool is not classified")


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
        decision = Decision("ask", f"Malformed hook input requires approval: {error}")
    json.dump(rendered(decision), sys.stdout)


if __name__ == "__main__":
    main()
