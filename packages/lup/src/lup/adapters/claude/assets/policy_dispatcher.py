"""Claude Code's half of the compiled hook dispatcher.

:mod:`lup.policy.dispatcher` compiles this module together with the shared
host half into the plugin's `hooks/scripts/policy.py`, so this is not itself
a script. It holds only what Claude Code spells for itself: the environment
naming the root it installs trusted packages beneath, relativization against
the launch directory, the four tools it routes, and the conservative ask it
returns through its own decision channel for input nothing can decide from.

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
from decisions import bash_decision, edit_decision, fetch_decision
from host import declared_identity, read_document, sandbox_active
from kernel.decision import KernelDecision, escalation_offer, sandbox_escaped
from policy_data import AGENT_IDENTITY_ENV, AUTONOMOUS_AGENT_IDENTITIES


def managed_root():
    """The root Claude Code installs and trusts packages beneath."""
    environ = os.environ  # lup: ignore[os-environ]
    if "CLAUDE_CONFIG_DIR" in environ:
        return Path(environ["CLAUDE_CONFIG_DIR"])
    if "HOME" in environ:
        return Path(environ["HOME"]) / ".claude"
    return None


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
        spliced = current.replace(old_text, new_text)  # lup: ignore[string-replace]
        return current, spliced
    if occurrences != 1:
        raise ValueError("Edit preimage must occur exactly once")
    position = current.find(old_text)
    updated = current[:position] + new_text + current[position + len(old_text) :]
    return current, updated


def spent_escape(tool_input):
    """Whether the call as written already asked to run outside the sandbox.

    Claude Code's own spelling of the escape, read here rather than compared
    against in two places: what it means is the kernel's `sandbox_escaped`,
    which both this boundary and the in-process seam ask.
    """
    return (
        "dangerouslyDisableSandbox" in tool_input
        and tool_input["dangerouslyDisableSandbox"] is True
    )


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
    autonomous = (
        agent_type in AUTONOMOUS_AGENT_IDENTITIES
        or declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
    )
    if name == "Bash":
        unsandboxed = spent_escape(tool_input)
        return bash_decision(
            tool_input["command"],
            managed_root(),
            sandbox_active() and not unsandboxed,
            interactive=True,
            # A call's sandbox is an argument of the call here, so a verdict
            # that has to leave the sandbox is carried out rather than refused.
            escapable=True,
        )
    if name == "WebFetch":
        return fetch_decision(tool_input["url"])
    if name == "Edit":
        path = tool_input["file_path"]
        before, after = edit_documents(
            path,
            tool_input["old_string"],
            tool_input["new_string"],
            "replace_all" in tool_input and tool_input["replace_all"] is True,
        )
        return edit_decision(path, before, after, Path(path).exists(), autonomous)
    if name == "Write":
        path = tool_input["file_path"]
        return edit_decision(
            path,
            read_document(path),
            tool_input["content"],
            Path(path).exists(),
            autonomous,
        )
    return KernelDecision("ask", "tool is not classified")


def rendered(decision, payload):
    """Answer one call on the permission channel, and place it on the other.

    Claude Code takes a call's sandbox as an argument of the call rather than
    as part of the verdict, so a placed decision goes out as the permission
    decision plus a rewrite of the arguments — which is what makes an
    unprompted placement reachable at all. Three things in the runtime make
    that rewrite carry the flag rather than swallow it, each read out of the
    shipped Claude Code binary at version 2.1.228 — the baseline to re-check
    against, rather than a conclusion to remember: the PreToolUse hook
    schema types `updatedInput` as an open record of arbitrary keys;
    `dangerouslyDisableSandbox` is a declared field of the shell tool's own
    input schema, so it is not an unknown key for the schema validation a
    returned `updatedInput` has to pass; and the one per-tool key filter
    applied to it before execution is keyed by a table naming a different
    tool, so for the shell tool the object arrives whole and the sandbox is
    chosen from it. What remains outside this file's reach is the session
    itself: a host that forbids unsandboxed commands ignores the flag, and
    the call runs confined with the verdict unchanged.

    The rewrite replaces the arguments rather than merging into them, so the
    whole input is carried through. A deferral is placed nowhere, which is
    also why nothing here reads a payload a deferral may not have parsed.

    Both sandbox questions are answered yes here, from that one field: the
    rewrite is how a verdict places a call, and the same field on the call the
    agent writes is how the agent places its own — which is what an
    ``escalable`` verdict offers it. Both halves of that offer are decided in
    the kernel rather than spelled here: `escalation_offer` says whether it is
    extended, and `sandbox_escaped` whether a call that spent it still leaves.
    The in-process seam asks the same two, because one field two boundaries
    fill from two conditions is a field they can fill differently — which is
    how the rewrite once revoked an offer the permission channel had granted.
    """
    settled = decision.placed(escapable=True, agent_escalates=True)
    if settled.effect == "defer":
        return {}
    answer = {
        "hookEventName": "PreToolUse",
        "permissionDecision": settled.effect,
        "permissionDecisionReason": settled.reason,
    }
    offer = escalation_offer(settled.sandbox, settled.reason)
    if offer:
        answer["additionalContext"] = offer
    if settled.sandbox == "ambient" or payload["tool_name"] != "Bash":
        return {"hookSpecificOutput": answer}
    return {
        "hookSpecificOutput": {
            **answer,
            "updatedInput": {
                **payload["tool_input"],
                "dangerouslyDisableSandbox": sandbox_escaped(
                    settled.sandbox, spent_escape(payload["tool_input"])
                ),
            },
        }
    }


def main():
    payload = {}
    try:
        payload = json.load(sys.stdin)
        decision = dispatch(payload)
    # Every way this can fail means one thing — the call went unjudged — and
    # one answer is right for all of them. Naming the exceptions instead is
    # what let a plain unreadable file escape, and the traceback exit reaches
    # PreToolUse as a non-blocking error, so the call proceeded ungoverned.
    # Nothing is swallowed: the reason carries whatever went wrong, and an
    # interrupt still passes through as the BaseException it is.
    except Exception as error:
        decision = KernelDecision(
            "ask", f"Malformed hook input requires approval: {error}"
        )
    json.dump(rendered(decision, payload), sys.stdout)
