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

# Interpreters that run arbitrary code. The deny below matches these only as a
# segment's command word — a bare name (`python`) or the basename of a path
# (`/usr/bin/python`) — never as a substring of an argument, filename, or
# directory (so `grep python`, `ls some/python3/dir`, `./py-helper.sh` are fine).
CODE_INTERPRETERS = ("python3?", "perl", "ruby", "node", "deno", "bun", "php")

# Command-position wrappers that change nothing about what runs next: an
# environment assignment (`VAR=val`) or a pass-through builtin. Skipping them
# keeps `sudo python x`, `env python x`, and `exec python x` denied.
COMMAND_PREFIX = (
    r"(?:[A-Za-z_]\w*=\S*\s+|(?:sudo|env|command|exec|time|nohup|setsid|stdbuf)\s+)*"
)

# `uv run [flags] <cmd>` and `uvx <cmd>` launch a command inside the project
# env; the interpreter deny looks through the flags to the command they run.
UV_LAUNCHER = r"(?:uv\s+run\s+(?:-\S+\s+|--\S+(?:[= ]\S+)?\s+)*|uvx\s+)"

INTERPRETER_DENY_REASON = (
    "Denied: use lup-devtools or `uv run lup` instead, or create a script in ./tmp/."
)

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
    Allow(pattern=r"^cd(\s+\S+)?$"),
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
    # Block code interpreters run as a segment's command word (directly, via a
    # pass-through wrapper, or via `uv run`/`uvx`). Segments are already split
    # on separators, so anchoring at `^` is enough.
    Deny(
        pattern=rf"^{COMMAND_PREFIX}(?:{UV_LAUNCHER})?(?:\S*/)?(?:{'|'.join(CODE_INTERPRETERS)})(?![\w./-])", # lup: Will this block "command | python3 -c "?
        reason=INTERPRETER_DENY_REASON,
    ),
    # ...and `uv run` executing inline code or a module/script, which runs
    # python without naming it (`uv run -c ...`, `-m ...`, `--script ...`).
    Deny(
        pattern=rf"^{COMMAND_PREFIX}{UV_LAUNCHER}(?:\S+\s+)*(?:-c|-m|--script)(?=[=\s])",
        reason=INTERPRETER_DENY_REASON,
    ),
    # ...except tmp scripts (overrides the denies above)
    Allow(pattern=r"^uv run (python )?(\./)?tmp/\S+\.py\b"),
]

# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------

HookOutput = dict[str, dict[str, str]]

# Process/command substitution opens with `$(`, `<(`, or `>(`; has_substitution
# treats any of these (or a backtick) as "could run anything" and blocks
# auto-allow. Backticks are handled separately since they have no prefix char.
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


# One left-to-right scan of a shell command, as an ordered alternation of the
# pieces that segment-splitting must respect. Quoting and escapes are handled
# by consuming whole spans, so a separator inside quotes is never seen as one:
#   sep      a separator that ends a segment: `;` `|` newline, `&&` `||`, or a
#            bare `&` (job control) that is not part of a `>&`/`&>` redirection
#   '...'    single-quoted span (no escapes inside)
#   "..."    double-quoted span (`\"` keeps the quote)
#   \x       a backslash escape
#   text     a run of ordinary characters
#   .        any leftover (e.g. an unterminated quote)
SEGMENT_TOKEN = re.compile(
    r"""
      (?P<sep> ;|\|\||\||&&|\n|(?<![>&])&(?!>) )
    | '[^']*'
    | "(?:\\.|[^"\\])*"
    | \\.
    | [^;|&\n'"\\]+
    | .
    """,
    re.VERBOSE | re.DOTALL,
)


def split_segments(command: str) -> list[str]:
    """Split a shell command on unquoted separators into trimmed segments."""
    segments: list[str] = []
    current: list[str] = []
    for token in SEGMENT_TOKEN.finditer(command):
        if token.lastgroup == "sep":
            segments.append("".join(current))
            current = []
        else:
            current.append(token.group())
    segments.append("".join(current))
    return [stripped for s in segments if (stripped := s.strip())]


def has_substitution(segment: str) -> bool:
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
    """Apply RULES to a single segment; the last matching rule wins."""
    matched: Allow | Deny | Ask | None = None
    for rule in RULES:
        if re.search(rule.pattern, segment):
            matched = rule
    return matched


def decide(command: str) -> HookOutput | None:
    """Combine the per-segment verdicts into one decision for the command.

    A compound command is only as safe as its least-safe part, so the verdicts
    combine conservatively: any denied segment denies the whole command; any
    segment no rule recognizes (or any auto-allow that hides a substitution)
    forces a fall-through to the user; an explicit ask outranks allow; and the
    command auto-allows only when every segment does.
    """
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
