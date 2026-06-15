#!/usr/bin/env python3
"""PreToolUse hook that controls Bash permissions via regex patterns.

The command is split into segments on unquoted shell separators (`;`, `&&`,
`||`, `|`, newline, and background `&`). Each segment is evaluated against
RULES like .gitignore: all patterns are checked top-to-bottom, and the last
matching rule wins. Segment verdicts combine conservatively:

- any segment denies     -> deny (with that segment's reason)
- any segment is unknown -> fall through to the user (ask), unchanged
- else any segment asks  -> ask (with that rule's reason)
- every segment allows   -> allow

Segments containing command or process substitution (`$(`, backticks, `<(`,
`>(`) never auto-allow, since the substituted command could be anything.
Redirections stay in their segment's text; prefix-anchored patterns keep
them from enabling auto-allows on their own.
"""

import json
import re
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


class Ask(BaseModel):
    action: Literal["ask"] = "ask"
    pattern: str
    reason: str = "Requires approval: command matches the ask-list"


# ---------------------------------------------------------------------------
# Configuration: rules evaluated per segment, top-to-bottom, last match wins
# ---------------------------------------------------------------------------

RULES: list[Allow | Deny | Ask] = [
    # Safe read-only / common commands
    Allow(pattern=r"^ls\b"),
    Allow(pattern=r"^tree\b"),
    Allow(pattern=r"^grep\b"),
    # xargs is only safe when its payload command is itself read-only.
    # Splitting on `|` makes `xargs <cmd>` its own segment, so this rule
    # whitelists the payload rather than blanket-approving any xargs.
    Allow(pattern=r"^xargs\s+(ls|tree|grep|cat|echo|test|file|wc|head|tail)\b"),
    Allow(pattern=r"^test\b"),
    Allow(pattern=r"^find\b(?!.*(-exec|-ok|-delete))"),
    # Navigation: a plain `cd <path>` segment, so compounds like
    # `cd <worktree> && uv run pytest` auto-allow when every part is safe
    Allow(pattern=r"^cd(\s+\S+)?$"), # CLAUDE: How does it check recursively that all sub segments are safe here?
    # GitHub CLI (read-only)
    Allow(pattern=r"^gh (pr|issue) (list|view|diff|status)\b"),
    # Git (safe subset)
    Allow(
        pattern=r"^git (status|log|diff|show|branch|worktree|stash|remote|fetch|tag|add|commit)\b"
    ),
    # uv package management: remove/lock only touch local files; add/sync fetch
    # and execute dependency code, so they require explicit approval.
    Allow(pattern=r"^uv (remove|lock)\b"),
    Ask(
        pattern=r"^uv (add|sync)\b",
        reason="`uv add`/`uv sync` fetch and execute dependency code — approve explicitly",
    ),
    Allow(pattern=r"^uv run (pyright|pytest|ruff)\b"),
    Allow(pattern=r"^uv run \S+ --help$"),
    # lup-devtools CLI
    Allow(pattern=r"^uv run lup-devtools\b"),
    # Block python invocations (at command position: start of segment or after
    # a separator, including via `uv run`). Mentions of "python" in arguments,
    # messages, or grep patterns are unaffected.
    Deny(
        pattern=r"(^|;|&&|\|\||\|)\s*(\S*/)?(uv\s+run\s+)?python3?\b", #CLAUDE: When I use claude, I often see block on files or otherwise that contains the word "python", even if the invocation doesn't contain the word "Python". Also, sometimes, the agent tries to cheat with e.g. perl or with uv run -c or stuff like that (verify this)
        reason="Denied: use lup-devtools or `uv run lup` instead, or create a script in ./tmp/.",
    ),
    # ...except tmp scripts (overrides the deny above)
    Allow(pattern=r"^uv run (python )?(\./)?tmp/\S+\.py\b"),
]

# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------

HookOutput = dict[str, dict[str, str]]

# claude: Not super clear what this section is for? I'm missing a bit of context when reading it
TWO_CHAR_SEPARATORS = ("&&", "||")
SUBSTITUTION_PREFIXES = ("$", "<", ">")


class BashInput(BaseModel):
    command: str = ""
    description: str = ""
    timeout: int | None = None
    run_in_background: bool = False


class HookEvent(BaseModel):
    tool_name: str = ""
    tool_input: BashInput = BashInput()


def allow_decision(
    reason: str = "Auto-allowed: command matches allowlist",
) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }


def deny_decision(reason: str) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def ask_decision(reason: str) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }


# Claude: I'm assuming those split segments are how we're recursing, and so  RULES is about segments and subsegments? That work I suppose. Not hyper elegant, and somewhat fixed
def split_segments(command: str) -> list[str]:
    """Split a shell command on unquoted separators into trimmed segments.

    Tracks single/double quotes and backslash escapes so separators inside
    quoted strings stay in their segment. `&&` and `||` are single
    separators; a lone `&` separates (background job), but `>&` and `&>`
    redirections stay in the segment text.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    while i < len(command): # claude: Huh, really? Why do you need so many modifier. Can't you just for i in range or something. This is extremely not dry and very hacky here
        ch = command[i]
        pair = command[i : i + 2]
        step = 1
        match ch:
            case _ if escaped:
                current.append(ch)
                escaped = False
            case "\\" if not in_single:
                current.append(ch)
                escaped = True
            case "'" if not in_double:
                in_single = not in_single
                current.append(ch)
            case '"' if not in_single:
                in_double = not in_double
                current.append(ch)
            case _ if in_single or in_double:
                current.append(ch)
            case _ if pair in TWO_CHAR_SEPARATORS:
                segments.append("".join(current))
                current = []
                step = 2
            case ";" | "|" | "\n":
                segments.append("".join(current))
                current = []
            case "&" if pair != "&>" and (not current or current[-1] != ">"):
                segments.append("".join(current))
                current = []
            case _:
                current.append(ch)
        i += step
    segments.append("".join(current))
    return [stripped for s in segments if (stripped := s.strip())]


def has_substitution(segment: str) -> bool:
    # claude: Why is this needed?
    """True when the segment contains command or process substitution.

    `$(`, backticks, `<(`, and `>(` can execute arbitrary commands, so a
    segment containing any of them (unescaped) never auto-allows. Quoting
    is deliberately ignored: double quotes don't stop substitution.
    """
    escaped = False
    for i, ch in enumerate(segment):
        if escaped:
            escaped = False
            continue
        match ch:
            case "\\":
                escaped = True
            case "`":
                return True
            case _ if ch in SUBSTITUTION_PREFIXES and segment[i + 1 : i + 2] == "(":
                return True
            case _:
                pass
    return False


def evaluate_segment(segment: str) -> Allow | Deny | Ask | None:
    # claude: Same here
    """Apply RULES to a single segment; the last matching rule wins."""
    matched: Allow | Deny | Ask | None = None
    for rule in RULES:
        if re.search(rule.pattern, segment):
            matched = rule
    return matched


def decide(command: str) -> HookOutput | None:
    segments = split_segments(command)
    if not segments:
        return None

    all_known = True
    ask_reason: str | None = None
    reason = "Auto-allowed: command matches allowlist"
    for segment in segments:
        match evaluate_segment(segment):
            case Deny(reason=deny_reason):
                return deny_decision(deny_reason)
            case Ask(reason=segment_reason):
                ask_reason = segment_reason
            case Allow(reason=allow_reason) if not has_substitution(segment):
                reason = allow_reason
            case _:
                all_known = False

    if not all_known:
        return None
    if ask_reason is not None:
        return ask_decision(ask_reason)
    return allow_decision(reason)


def main() -> None:
    try:
        event = HookEvent.model_validate_json(sys.stdin.read())
    except (ValidationError, OSError):
        sys.exit(0)

    if event.tool_name != "Bash":
        sys.exit(0)

    result = decide(event.tool_input.command)
    if result:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
