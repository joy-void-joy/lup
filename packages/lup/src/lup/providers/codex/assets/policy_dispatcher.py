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
    unconfined_by_declaration,
    bash_decision,
    edit_decision,
    fetch_decision,
    refused_tool_decision,
    written_review,
)
from host import (
    declared_identity,
    publish_edition,
    read_document,
    record_hook_evidence,
    sandbox_active,
)
from kernel.decision import KernelDecision, SANDBOX_TRAPPED_REASON
from kernel.shell import auto_escape_matches
from policy_data import AUTO_ESCAPE_PREFIXES
from policy_data import AGENT_IDENTITY_ENV, AUTONOMOUS_AGENT_IDENTITIES


def hook_environment():
    """The native environment passed to this bare hook process."""
    # lup: ignore[os-environ] — bare hooks have no settings package
    return os.environ


def plugin_data_root():
    """The plugin-owned writable directory Codex gives hook processes."""
    environ = hook_environment()
    root = environ["PLUGIN_DATA"] if "PLUGIN_DATA" in environ else ""
    return Path(root) if root else None


def managed_root():
    """The home Codex installs and trusts packages beneath."""
    environ = hook_environment()
    return Path(environ["CODEX_HOME"]) if "CODEX_HOME" in environ else None


def spent_escape(tool_input):
    """Whether this call requested Codex's per-command sandbox escape."""
    return (
        "sandbox_permissions" in tool_input
        and tool_input["sandbox_permissions"] == "require_escalated"
    )


def approval_fingerprint(payload):
    """Identify the fields both approval events carry for one Bash call."""
    fields = ("session_id", "turn_id", "cwd", "tool_name")
    if any(
        field not in payload
        or not isinstance(payload[field], str)
        or not payload[field]
        for field in fields
    ):
        return None
    tool_input = payload["tool_input"]
    if (
        payload["tool_name"] != "Bash"
        or not isinstance(tool_input, dict)
        or "command" not in tool_input
        or not isinstance(tool_input["command"], str)
    ):
        return None
    identity = [payload[field] for field in fields]
    identity.append(tool_input["command"])
    return json.dumps(identity, ensure_ascii=True, separators=(",", ":"))


def approval_receipt_root():
    """The plugin-owned writable directory shared by hook processes."""
    environ = hook_environment()
    if "PLUGIN_DATA" not in environ:
        return None
    return Path(environ["PLUGIN_DATA"]) / "approval-receipts"


def record_approval(payload, max_pending=256):
    """Record one native permission event without merging identical calls."""
    fingerprint = approval_fingerprint(payload)
    root = approval_receipt_root()
    if fingerprint is None or root is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    receipts = list(root.iterdir())
    overflow = len(receipts) - max_pending + 1
    for receipt in receipts[: max(0, overflow)]:
        receipt.unlink(missing_ok=True)
    receipt = root / os.urandom(16).hex()
    receipt.write_text(fingerprint, encoding="utf-8")


def uncorrelated(payload):
    """Why a call that should carry an approval does not, in one sentence.

    Empty when nothing is amiss, which is the ordinary case: a call that was
    never escalated has no approval to find and no problem to report.

    This exists because the failure it names is otherwise indistinguishable
    from the one it is not. A call whose native approval was accepted and
    whose receipt then failed to correlate reaches the same refusal as a call
    nobody approved at all -- so #180 reads as "the policy rejected my
    escalated diff" and the actual defect, whichever field the two events
    disagreed on, leaves no trace. Naming the step that failed does not fix
    it and does make the next run conclusive.
    """
    root = approval_receipt_root()
    if root is None or not root.exists() or not list(root.iterdir()):
        return ""
    if approval_fingerprint(payload) is None:
        missing = [
            field
            for field in ("session_id", "turn_id", "cwd", "tool_name")
            if field not in payload or not payload[field]
        ]
        named = ", ".join(missing) if missing else "the command"
        return (
            f" — an approval is pending for this run and this call could not be"
            f" matched to it: the event carries no {named}, so the two cannot"
            " be correlated"
        )
    return (
        " — an approval is pending for this run but none matches this exact"
        " call; the escalation and this call disagree on the session, the turn,"
        " the directory or the command text"
    )


def spend_approval(payload):
    """Consume one pending permission event matching this exact Bash call."""
    fingerprint = approval_fingerprint(payload)
    root = approval_receipt_root()
    if fingerprint is None or root is None or not root.exists():
        return False
    for receipt in root.iterdir():
        try:
            matches = receipt.read_text(encoding="utf-8") == fingerprint
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        if not matches:
            continue
        try:
            receipt.unlink()
        except FileNotFoundError:
            continue
        return True
    return False


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
    # Where this session is rooted, which is what says whether a patched file
    # belongs to the repository being worked on or to somebody else's. Read
    # once, because the shell path and the patch path ask the same question of
    # it and a second read is a second place it can be forgotten.
    session_directory = Path(payload["cwd"]) if "cwd" in payload else None
    # Whether this session is a reviewed worker, which decides two unrelated
    # things: how a patch is judged, and whether a refusal has a route to
    # name. Read once at the top rather than inside the branch that needed it
    # first, since both branches need it now.
    autonomous = declared_identity(AGENT_IDENTITY_ENV) in AUTONOMOUS_AGENT_IDENTITIES
    if name == "Bash":
        requested_escape = spent_escape(tool_input)
        escaped = requested_escape or auto_escape_matches(
            tool_input["command"], AUTO_ESCAPE_PREFIXES
        )
        decision = bash_decision(
            tool_input["command"],
            managed_root(),
            False if permission_request else sandbox_active(),
            interactive=permission_request,
            # A native prefix rule can auto-escape one simple command; an explicit
            # request is the other supported route. Both are checked against
            # semantic placement before the hook lets the native boundary act.
            escapable=escaped,
            cwd=session_directory,
            # A reviewed worker's session has nobody at a keyboard and is not
            # therefore alone: the run it belongs to carries a mailbox that
            # reaches whoever is supervising it.
            relayed=autonomous,
            # The same identity the edit branches are given, because a command
            # carrying its own content reaches the same gates.
            autonomous=autonomous,
        )
        # PreToolUse can neither see nor place every native escape. Let Codex's
        # sandbox run a confined call or raise the PermissionRequest where this
        # same policy can judge the requested escape instead of preempting it.
        if not permission_request and decision.reason == SANDBOX_TRAPPED_REASON:
            return KernelDecision("defer", decision.reason)
        if (
            requested_escape
            and decision.effect == "allow"
            and decision.sandbox != "outside"
            and not unconfined_by_declaration(tool_input["command"])
        ):
            return KernelDecision(
                "deny",
                f"call requested outside but policy places it {decision.sandbox}; remove sandbox_permissions and retry",
            )
        return decision
    if name == "web_fetch":
        # The same directory the shell branch reads its boundary from: the
        # profile's answer for what nothing classified is one declaration,
        # not one per surface.
        return fetch_decision(tool_input["url"], session_directory)
    if name == "apply_patch":
        return joined(
            [
                edit_decision(
                    change.path,
                    change.before,
                    change.after,
                    change.path_exists,
                    autonomous,
                    change.operation(),
                    session_directory,
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


def observe(payload):
    """Record which checkout an edit landed in, and decide nothing.

    Codex reads the directory it ran in, where Claude reads the edited file.
    Not a lesser answer here, and not an available one either way: Codex
    names its files inside the patch envelope, and the parser that decodes
    one validates its context against the document on disk — which this
    event runs after the patch already rewrote. Re-decoding it here would
    fail on exactly the edits it was called for. Codex hands over its
    working directory instead, which Claude's hook is promised nothing
    about, and that is the same fact one step coarser.

    Coarser is enough to say which checkout is being edited and not enough
    to type-check what changed, so Codex records the edition and Claude also
    reports diagnostics. Checking the directory instead would answer every
    patch with every finding in the tree, most of them about files this
    edit never touched.

    A shell command is not coarser here, and gets the same reading Claude's
    does. The envelope problem above is about a *patch*, whose files this
    event can no longer decode; a command carries its own text, names its
    write targets in that text, and the files it wrote are on disk to be
    read. So the gates a shell write could never reach before it ran are put
    to its result here, which is what lets the verdict beforehand answer
    from the path alone.
    """
    root = payload["cwd"] if "cwd" in payload else ""
    if root:
        publish_edition(root)
    tool_input = payload["tool_input"] if "tool_input" in payload else {}
    command = tool_input["command"] if "command" in tool_input else ""
    if not command:
        return []
    return written_review(command, Path(root) if root else Path.cwd())


def main():
    payload = {}
    try:
        payload = json.load(sys.stdin)
        record_hook_evidence(plugin_data_root(), payload, "started")
        # Watching and deciding are separate events, and this one returns
        # before a verdict exists: the patch has already applied, so there is
        # nothing left to permit, and the fail-closed exit below would refuse
        # a call that already happened.
        event = payload["hook_event_name"] if "hook_event_name" in payload else ""
        if event == "PostToolUse":
            found = observe(payload)
            # The same one channel Claude's half has, for the same reason:
            # the call has run, so a clean exit says nothing anybody reads.
            # Silence when the result checks out, so the channel means
            # something when it is used.
            if found:
                detail = "\n".join(found)
                record_hook_evidence(
                    plugin_data_root(), payload, "completed", "observed", detail
                )
                sys.stderr.write(detail)
                raise SystemExit(2)
            record_hook_evidence(plugin_data_root(), payload, "completed", "observed")
            return
        permission_request = event == "PermissionRequest"
        permission_evidenced = event == "PreToolUse" and spend_approval(payload)
        decision = dispatch(payload, permission_request or permission_evidenced)
        # PermissionRequest has no tool-use id. A matching PreToolUse is the
        # native proof that its session-, turn-, cwd-, tool-, and command-bound
        # request proceeded; the policy is still re-run so a deny still wins.
        if permission_evidenced and decision.effect == "ask":
            decision = KernelDecision("allow", decision.reason, decision.sandbox)
        # Record before replying: an undecided request reaches a human, and a
        # later matching PreToolUse exists only when that human accepted it.
        if permission_request and decision.effect != "deny":
            record_approval(payload)
        # A verdict from here places nothing: this hook answers, and the call
        # runs with the arguments the model wrote, so a placement is degraded
        # to its plain effect rather than carrying an intent no channel here
        # performs. Asking for the launcher's host is a marker a reviewer
        # answers, and it reaches the same relay under every runtime, so
        # nothing about that route depends on this channel existing.
        decision = decision.placed(escapable=False)
    # Every way this can fail means one thing — the call went unjudged — and
    # one answer is right for all of them. Naming the exceptions instead is
    # what let a plain unreadable file escape, and a traceback exit is not the
    # fail-closed exit this boundary takes, so the call proceeded ungoverned.
    # Nothing is swallowed: the reason carries whatever went wrong, and an
    # interrupt still passes through as the BaseException it is.
    except Exception as error:
        record_hook_evidence(
            plugin_data_root(),
            payload,
            "failed",
            "error",
            f"{type(error).__name__}: {error}",
        )
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
        record_hook_evidence(plugin_data_root(), payload, "completed", "allow")
        return
    if permission_request and decision.effect == "ask":
        record_hook_evidence(plugin_data_root(), payload, "completed", "ask")
        return
    if decision.effect in ("allow", "defer"):
        record_hook_evidence(plugin_data_root(), payload, "completed", decision.effect)
        return
    # A refusal that arrives while an approval is pending is two failures
    # wearing one face -- the policy declining a call, and the correlation
    # between a native approval and the call it approved not landing. They
    # read identically without this, which is how #180 reads as the first
    # when it is the second.
    detail = decision.reason + uncorrelated(payload)
    record_hook_evidence(
        plugin_data_root(), payload, "completed", decision.effect, detail
    )
    sys.stderr.write(detail)
    raise SystemExit(2)
