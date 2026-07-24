#!/usr/bin/env python3
"""Generated Codex hook dispatcher over the canonical semantic kernel.

Rendered from lup.adapters.codex.assets.policy_dispatcher by
`uv run lup-devtools harness generate all` — do not edit directly.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from kernel import KernelDecision, decide_fetch, decide_shell
from policy_data import ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES, SHELL_RULES


def sandbox_active():
    environ = os.environ  # lup: ignore[os-environ]
    return "LUP_SANDBOX_ACTIVE" in environ and environ["LUP_SANDBOX_ACTIVE"] == "1"


def managed_script_roots() -> list[str]:
    """Return absolute package roots installed and trusted by Codex."""
    environ = os.environ  # lup: ignore[os-environ]
    root = Path(environ["CODEX_HOME"]) if "CODEX_HOME" in environ else None
    if root is None or not root.is_absolute():
        return []
    return [str(root / "skills"), str(root / "plugins" / "cache")]


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    if name == "Bash":
        return decide_shell(
            tool_input["command"],
            SHELL_RULES,
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
            sandboxed=sandbox_active(),
            trusted_script_roots=managed_script_roots(),
        )
    if name == "web_fetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "apply_patch":
        return KernelDecision(
            "ask",
            "opaque patch input requires native parsing before it can be auto-allowed",
        )
    return KernelDecision("ask", f"unknown tool {name!r} is not covered by policy")


def main():
    try:
        decision = dispatch(json.load(sys.stdin))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"Malformed hook input requires approval: {error}")
        raise SystemExit(2) from error
    if decision.effect in ("allow", "defer"):
        return
    sys.stderr.write(decision.reason)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
