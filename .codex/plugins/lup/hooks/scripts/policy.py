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
from kernel.decision import KernelDecision
from kernel.edit import decide_edit
from kernel.fetch import decide_fetch
from kernel.lex import shell_write_targets
from kernel.shell import decide_shell
from codex_patch import patched_files
from policy_data import (
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    DENIED_FETCH_SCOPES,
    MAXIMUM_ADDED_LINES,
    PATH_RULES,
    SHELL_RULES,
)


# lup: This seems very close to claude's policy_dispatcher, we shoud DRY this


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


def worktree_path(path_text):
    """Relativize against the worktree holding the path, not the cwd.

    A sibling worktree is writable but is not under the launch directory,
    so relativizing against the cwd would leave its paths absolute and
    every repo-relative path rule — human-owned files, protected
    directories — would quietly fail to match inside it.
    """
    path = Path(path_text)
    if not path.is_absolute():
        return path_text
    resolved = path.resolve()
    for root in resolved.parents:
        if (root / ".git").exists():
            return resolved.relative_to(root).as_posix()
    return path_text


def read_document(path_text):
    path = Path(path_text)
    return path.read_text(encoding="utf-8") if path.exists() else None


def edit_decision(path_text, before, after):
    path = Path(path_text)
    suffix = path.suffix.lower()
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else ()
    return decide_edit(
        worktree_path(path_text),
        before,
        after,
        path_exists=path.exists(),
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        python_source=suffix in (".py", ".pyi"),
    )


def joined(decisions):
    """Join one envelope's files: deny beats ask beats defer beats allow."""
    for effect in ("deny", "ask", "defer"):
        for decision in decisions:
            if decision.effect == effect:
                return decision
    return KernelDecision("allow", "every patched file is declared safe")


def dispatch(payload, permission_request=False):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    if name == "Bash":
        return decide_shell(
            tool_input["command"],
            SHELL_RULES,
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
            sandboxed=False if permission_request else sandbox_active(),
            trusted_script_roots=managed_script_roots(),
            existing_targets=existing_write_targets(tool_input["command"]),
            interactive=permission_request,
        )
    if name == "web_fetch":
        return decide_fetch(
            tool_input["url"],
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
        )
    if name == "apply_patch":
        changes = patched_files(tool_input["command"], read_document)
        return joined(
            [
                edit_decision(change.path, change.before, change.after)
                for change in changes
            ]
        )
    return KernelDecision("ask", f"unknown tool {name!r} is not covered by policy")


def main():
    try:
        payload = json.load(sys.stdin)
        permission_request = (
            payload["hook_event_name"] == "PermissionRequest"
            if "hook_event_name" in payload
            else False
        )
        decision = dispatch(payload, permission_request)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"Malformed hook input requires approval: {error}")
        raise SystemExit(2) from error
    if permission_request and decision.effect == "allow":
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            },
            sys.stdout,
        )
        return
    if permission_request and decision.effect == "ask":
        return
    if decision.effect in ("allow", "defer"):
        return
    sys.stderr.write(decision.reason)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
