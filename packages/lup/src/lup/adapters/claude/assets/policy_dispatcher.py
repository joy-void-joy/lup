"""Claude Code's half of the compiled hook dispatcher.

:mod:`lup.policy.dispatcher` compiles this module together with the shared
host half into the plugin's `hooks/scripts/policy.py`, so this is not itself
a script. It holds only what Claude Code spells for itself: the environment
naming the root it installs trusted packages beneath, relativization against
the launch directory, the tools it routes, and the conservative ask it
returns through its own decision channel for input nothing can decide from.

A call none of those four decode is put to the refusal table before it earns
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


def dispatch(payload):
    name = payload["tool_name"]
    tool_input = payload["tool_input"]
    agent_type = payload["agent_type"] if "agent_type" in payload else ""
    autonomous = (
        agent_type in AUTONOMOUS_AGENT_IDENTITIES
        or declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
    )
    if name == "Bash":
        unsandboxed = (
            "dangerouslyDisableSandbox" in tool_input
            and tool_input["dangerouslyDisableSandbox"] is True
        )
        return bash_decision(
            tool_input["command"],
            managed_root(),
            sandbox_active() and not unsandboxed,
            True,
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
    # Asked of whatever reached here rather than of a listed few: which tools
    # are worth refusing is the declaration's answer, and naming any of them
    # here would be this file holding a second, narrower copy of it. The
    # branches above keep their calls, which have semantics to be judged by.
    refused = refused_tool_decision(
        name, [value for value in tool_input.values() if isinstance(value, str)]
    )
    if refused is not None:
        return refused
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
    json.dump(rendered(decision), sys.stdout)
