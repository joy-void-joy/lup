#!/usr/bin/env python3
"""PreToolUse hook that controls WebFetch permissions via regex patterns.

The URL is normalized to `scheme://host/path` (lowercased host; credentials,
port, query, and fragment dropped) and patterns must match from the first
character (re.match). Anchoring prevents allowlist bypasses through URLs
embedded in another host's query string or path.

Decision order:
1. Check normalized URL against DENY_PATTERNS -> deny with reason
2. Check normalized URL against ALLOW_PATTERNS -> auto-allow
3. Fall through -> defer to user (ask)
"""

import json
import re
import sys
import urllib.parse

from pydantic import BaseModel, ValidationError

# ---------------------------------------------------------------------------
# Configuration: edit these lists to control WebFetch permissions
#
# Patterns match against the normalized `scheme://host/path` from the start
# (re.match). End host patterns with `/` so lookalike domains
# (e.g. docs.claude.com.evil.example) can't extend them.
# ---------------------------------------------------------------------------

ALLOW_PATTERNS: list[str] = [
    # Project documentation
    r"https?://docs\.claude\.com/",
    r"https?://ai\.pydantic\.dev/",
    # OpenAI Codex
    r"https?://github\.com/openai/codex",
    r"https?://raw\.githubusercontent\.com/openai/codex/",
    r"https?://developers\.openai\.com/codex/",
]

DENY_PATTERNS: list[tuple[str, str]] = [
    # (pattern, reason)
    # Example:
    # (r"https?://malicious\.example\.com/", "Blocked: known malicious domain"),
]

# ---------------------------------------------------------------------------
# Hook implementation
# ---------------------------------------------------------------------------

HookOutput = dict[str, dict[str, str]]


class WebFetchInput(BaseModel):
    url: str = ""
    prompt: str = ""


class HookEvent(BaseModel):
    tool_name: str = ""
    tool_input: WebFetchInput = WebFetchInput()


def allow_decision(reason: str = "Auto-allowed: URL matches allowlist") -> HookOutput:
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


def normalize_url(url: str) -> str | None:
    """Reduce a URL to `scheme://host/path` for anchored matching.

    Returns None when the URL is unparseable or lacks a scheme or host —
    those fall through to the user prompt.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    return f"{parts.scheme}://{host}{parts.path}"


def decide(url: str) -> HookOutput | None:
    target = normalize_url(url)
    if target is None:
        return None

    for pattern, reason in DENY_PATTERNS:
        if re.match(pattern, target):
            return deny_decision(reason)

    for pattern in ALLOW_PATTERNS:
        if re.match(pattern, target):
            return allow_decision()

    return None


def main() -> None:
    try:
        event = HookEvent.model_validate_json(sys.stdin.read())
    except (ValidationError, OSError):
        sys.exit(0)

    if event.tool_name != "WebFetch":
        sys.exit(0)

    result = decide(event.tool_input.url)
    if result:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
