"""Reading what the generated Codex dispatcher answered.

Codex has two refusal channels and the dispatcher picks between them by what
the refusal is for. A call the review queue parked answers on stdout, as a
structured denial carrying its reason, because Codex drops `systemMessage`
when a hook exits 2 and that reason names the operator who can release it.
Every other refusal takes exit 2, and a permitted call says nothing at all —
so exit status alone cannot tell an allow from a parked review, and each
suite that asked it separately got a different answer.
"""

import json

import sh


def codex_effect(result: sh.RunningCommand) -> str:
    """``allow`` or ``deny``, over whichever channel this refusal took."""
    if result.exit_code == 2:
        return "deny"
    if not result.stdout:
        return "allow"
    return str(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"])


def codex_denial(result: sh.RunningCommand) -> str:
    """The refused call's operator-visible reason, from either channel."""
    if result.exit_code == 2:
        return result.stderr.decode()
    assert result.exit_code == 0
    rendered = json.loads(result.stdout)
    output = rendered["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["hookEventName"] == "PreToolUse"
    assert rendered["systemMessage"] == output["permissionDecisionReason"]
    return str(output["permissionDecisionReason"])
