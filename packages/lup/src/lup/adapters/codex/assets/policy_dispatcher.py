"""Codex's half of the compiled hook dispatcher.

:mod:`lup.policy.dispatcher` compiles this module together with the shared
host half into the plugin's `hooks/scripts/policy.py`, so this is not itself
a script. It holds only what Codex spells for itself: the environment naming
the home it installs trusted packages beneath, relativization against the
worktree rather than the launch directory, the three tools it routes, the
patch envelope it decodes into per-file edits, and the fail-closed exit it
takes where the command-hook boundary offers no way to ask.

The imports below resolve against the generated runtime the compiled script
sits beside, which is why this file is type-checked against that tree rather
than against the workspace.
"""

import json
import os
import sys
from pathlib import Path

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and `runtime/` is a plain sibling directory holding
# the kernel package and this plugin's policy data rather than an installed
# distribution. Naming it as a search path is what lets the imports below
# resolve, for the interpreter and for a type checker alike.
sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from codex_patch import patched_files
from host import (
    declared_identity,
    existing_write_targets,
    granted_allowances,
    managed_script_roots,
    read_document,
    sandbox_active,
)
from kernel.decision import KernelDecision
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


def managed_root():
    """The home Codex installs and trusts packages beneath."""
    environ = os.environ  # lup: ignore[os-environ]
    return Path(environ["CODEX_HOME"]) if "CODEX_HOME" in environ else None


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


def edit_decision(path_text, before, after, path_exists):
    path = Path(path_text)
    suffix = path.suffix.lower()
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else []
    return decide_edit(
        worktree_path(path_text),
        before,
        after,
        path_exists=path_exists,
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        path_roles=PATH_ROLES,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES,
        allowances=granted_allowances(CONCERN_ALLOWANCES_ENV),
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
        command = tool_input["command"]
        return decide_shell(
            command,
            SHELL_RULES,
            ALLOWED_FETCH_SCOPES,
            DENIED_FETCH_SCOPES,
            sandboxed=False if permission_request else sandbox_active(),
            trusted_script_roots=managed_script_roots(managed_root()),
            path_roles=PATH_ROLES,
            existing_targets=existing_write_targets(shell_write_targets(command)),
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
                edit_decision(
                    change.path,
                    change.before,
                    change.after,
                    change.path_exists,
                )
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
    # Every way this can fail means one thing — the call went unjudged — and
    # one answer is right for all of them. Naming the exceptions instead is
    # what let a plain unreadable file escape, and a traceback exit is not the
    # fail-closed exit this boundary takes, so the call proceeded ungoverned.
    # Nothing is swallowed: the reason carries whatever went wrong, and an
    # interrupt still passes through as the BaseException it is.
    except Exception as error:
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
