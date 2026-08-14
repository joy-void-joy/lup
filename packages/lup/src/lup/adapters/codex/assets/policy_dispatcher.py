"""Codex's half of the compiled hook dispatcher.

:mod:`lup.policy.dispatcher` compiles this module together with the shared
host half into the plugin's `hooks/scripts/policy.py`, so this is not itself
a script. It holds only what Codex spells for itself: the environment naming
the home it installs trusted packages beneath, relativization against the
worktree rather than the launch directory, the tools it routes, the patch
envelope it decodes into per-file edits, and the fail-closed exit it takes
where the command-hook boundary offers no way to ask.

A call none of those three decode is put to the refusal table before it earns
the unclassified ask, so this file never names a tool it has no semantics for.
Which names a runtime offers is that runtime's own fact; which of them a
project has decided against is the application's — so the tools a refusal adds
to the routed set come from the declaration rather than from a list here.

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
from decisions import (
    bash_decision,
    edit_decision,
    fetch_decision,
    refused_tool_decision,
)
from host import declared_identity, read_document, sandbox_active
from kernel.decision import KernelDecision
from policy_data import AGENT_IDENTITY_ENV, AUTONOMOUS_AGENT_IDENTITIES


def managed_root():
    """The home Codex installs and trusts packages beneath."""
    environ = os.environ  # lup: ignore[os-environ]
    return Path(environ["CODEX_HOME"]) if "CODEX_HOME" in environ else None


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
        return bash_decision(
            tool_input["command"],
            managed_root(),
            False if permission_request else sandbox_active(),
            permission_request,
        )
    if name == "web_fetch":
        return fetch_decision(tool_input["url"])
    if name == "apply_patch":
        autonomous = (
            declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
        )
        return joined(
            [
                edit_decision(
                    change.path,
                    change.before,
                    change.after,
                    change.path_exists,
                    autonomous,
                )
                for change in patched_files(tool_input["command"], read_document)
            ]
        )
    # Asked of whatever reached here rather than of a listed few, exactly as
    # the Claude half asks it: which tools are worth refusing is the
    # declaration's answer, and a runtime that shipped the table without
    # consulting it would read as a refusal in force while the call went
    # through. The branches above keep their calls, which have semantics.
    refused = refused_tool_decision(
        name, [value for value in tool_input.values() if isinstance(value, str)]
    )
    if refused is not None:
        return refused
    return KernelDecision("ask", f"unknown tool {name!r} is not covered by policy")


def main():
    try:
        payload = json.load(sys.stdin)
        permission_request = (
            payload["hook_event_name"] == "PermissionRequest"
            if "hook_event_name" in payload
            else False
        )
        # Codex places nothing per call: its sandbox is a session flag on the
        # binary, so a verdict is degraded to its plain effect rather than
        # carrying an intent this boundary has no channel to perform.
        decision = dispatch(payload, permission_request).placed(False)
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
