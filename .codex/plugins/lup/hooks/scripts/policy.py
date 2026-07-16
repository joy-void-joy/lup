#!/usr/bin/env python3
"""Generated Codex hook dispatcher over the bundled semantic runtime."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from policy import Decision, decide_fetch, decide_shell

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


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    if name == "Bash":
        return decide_shell(tool_input["command"])
    if name == "web_fetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "apply_patch":
        return Decision(
            "ask",
            "opaque patch input requires native parsing before it can be auto-allowed",
        )
    return Decision("ask", f"unknown tool {name!r} is not covered by policy")


def main():
    try:
        decision = dispatch(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"Malformed hook input requires approval: {error}")
        raise SystemExit(2) from error
    if decision.effect == "allow":
        return
    sys.stderr.write(decision.reason)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
