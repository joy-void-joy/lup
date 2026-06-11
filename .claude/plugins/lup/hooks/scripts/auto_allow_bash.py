#!/usr/bin/env python3
"""PreToolUse hook that controls Bash permissions via regex patterns.

A command is split on shell operators (``&&``, ``||``, ``;``, ``|``) into
segments. Within each segment, rules are evaluated like .gitignore: all
patterns are checked top-to-bottom and the last matching rule wins. The
whole command auto-allows only when EVERY segment resolves to allow; if any
segment matches a deny rule the command is denied, and if any segment
matches no rule the decision falls through to the user (ask). This closes
the chaining bypass where a harmless prefix (``ls && rm -rf ~``) would
auto-approve a dangerous compound.
"""

import json
import re
import shlex
import sys

from typing import Literal

from pydantic import BaseModel, ValidationError


class Allow(BaseModel):
    action: Literal["allow"] = "allow"
    pattern: str
    reason: str = "Auto-allowed: command matches allowlist"


class Deny(BaseModel):
    action: Literal["deny"] = "deny"
    pattern: str
    reason: str = "Denied: command matches denylist"


# ---------------------------------------------------------------------------
# Configuration: rules evaluated top-to-bottom, last match wins
# ---------------------------------------------------------------------------

RULES: list[Allow | Deny] = [
    # Safe read-only / common commands
    Allow(pattern=r"^ls\b"),
    Allow(pattern=r"^tree\b"),
    Allow(pattern=r"^grep\b"),
    # xargs is only safe when its payload command is itself read-only.
    # Splitting on `|` makes `xargs <cmd>` its own segment, so this rule
    # whitelists the payload rather than blanket-approving any xargs.
    Allow(pattern=r"^xargs\s+(ls|tree|grep|cat|echo|test|file|wc|head|tail)\b"),
    Allow(pattern=r"^test "),
    Allow(pattern=r"^find"),
    # GitHub CLI (read-only)
    Allow(pattern=r"^gh (pr|issue) (list|view|diff|status)\b"),
    # Git (safe subset)
    Allow(
        pattern=r"^git (status|log|diff|show|branch|worktree|stash|remote|fetch|tag|add|commit)\b"
    ),
    # uv package management
    Allow(pattern=r"^uv (remove|lock)\b"),
    Allow(pattern=r"^uv run (pyright|pytest|ruff)\b"),
    Allow(pattern=r"^uv run \S+ --help$"),
    # lup-devtools CLI
    Allow(pattern=r"uv run lup-devtools\b"),
    # Block all python invocations...
    Deny(
        pattern=r"(^|\b)python3?\b",
        reason="Denied: use lup-devtools instead, or create a script in ./tmp/.",
    ),
    # ...except tmp scripts (overrides the deny above)
    Allow(pattern=r"^uv run (python )?(\./)?tmp/\S+\.py\b"),
]

# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------

HookOutput = dict[str, dict[str, str]]


class BashInput(BaseModel):
    command: str = ""
    description: str = ""
    timeout: int | None = None
    run_in_background: bool = False


class HookEvent(BaseModel):
    tool_name: str = ""
    tool_input: BashInput = BashInput()


def _allow(reason: str = "Auto-allowed: command matches allowlist") -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }


def _deny(reason: str) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


SHELL_OPERATORS = ("&&", "||", ";", "|", "\n")


def split_segments(command: str) -> list[str]:
    """Split a command into segments on shell operators, respecting quotes.

    ``shlex`` tokenization keeps quoted strings intact so an operator inside
    a quoted argument (``grep "a|b" f``) does not create a spurious segment.
    On a tokenization error (unbalanced quotes, etc.) the whole command is
    returned as a single segment so the caller errs toward "ask".
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return [command.strip()]

    segments: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token in SHELL_OPERATORS or set(token) <= {"|", "&", ";"}:
            if current:
                segments.append(" ".join(current))
                current = []
            continue
        current.append(token)
    if current:
        segments.append(" ".join(current))
    return [s for s in segments if s]


def decide_segment(segment: str) -> Literal["allow", "deny", "ask"]:
    """Resolve a single segment via last-match-wins over RULES."""
    decision: Literal["allow", "deny", "ask"] = "ask"
    for rule in RULES:
        if re.search(rule.pattern, segment):
            decision = rule.action
    return decision


def decide(command: str) -> HookOutput | None:
    cmd = command.strip()
    if not cmd:
        return None

    segments = split_segments(cmd)
    if not segments:
        return None

    decisions = [(segment, decide_segment(segment)) for segment in segments]

    # A deny on any segment wins over everything (a dangerous payload anywhere
    # in the pipeline must block the whole command).
    for segment, decision in decisions:
        if decision == "deny":
            return _deny(f"Denied: segment is denylisted | segment: {segment[:80]}")

    # Auto-allow only when EVERY segment is explicitly allowlisted; a single
    # non-allowlisted segment falls through to the user.
    if all(decision == "allow" for _segment, decision in decisions):
        return _allow()

    return None


def main() -> None:
    try:
        event = HookEvent.model_validate_json(sys.stdin.read())
    except ValidationError, OSError:
        sys.exit(0)

    if event.tool_name != "Bash":
        sys.exit(0)

    result = decide(event.tool_input.command)
    if result:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
