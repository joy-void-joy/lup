"""Behavior tests for the auto_allow_fetch permission hook.

Loads the hook script by path (it lives outside the package tree) and
exercises decide() — the pure pattern-matching core — table-driven.
"""

import importlib.util
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).parents[2]
    / ".claude"
    / "plugins"
    / "lup"
    / "hooks"
    / "scripts"
    / "auto_allow_fetch.py"
)

spec = importlib.util.spec_from_file_location("auto_allow_fetch", HOOK_PATH)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def fetch_decision(url: str) -> str | None:
    """Return 'allow', 'deny', or None (fall through to user prompt)."""
    result = hook.decide(url)
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


def test_allowlisted_docs_still_allow() -> None:
    assert fetch_decision("https://docs.claude.com/en/api/overview") == "allow"
    assert fetch_decision("https://ai.pydantic.dev/agents/") == "allow"
    assert fetch_decision("http://docs.claude.com/") == "allow"


def test_embedded_allowed_url_does_not_bypass() -> None:
    assert fetch_decision("https://evil.example/?u=https://docs.claude.com/") is None
    assert fetch_decision("https://evil.example/https://docs.claude.com/") is None
    assert fetch_decision("https://evil.example/#https://docs.claude.com/") is None


def test_lookalike_hosts_fall_through() -> None:
    assert fetch_decision("https://docs.claude.com.evil.example/") is None
    assert fetch_decision("https://docs.claude.com@evil.example/") is None


def test_unparseable_or_relative_urls_fall_through() -> None:
    assert fetch_decision("docs.claude.com/en/docs") is None
    assert fetch_decision("") is None


def test_deny_wins_over_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook,
        "DENY_PATTERNS",
        [(r"https?://docs\.claude\.com/internal/", "Blocked: internal docs")],
    )
    assert fetch_decision("https://docs.claude.com/internal/secrets") == "deny"
    assert fetch_decision("https://docs.claude.com/en/docs") == "allow"


def test_unknown_urls_fall_through() -> None:
    assert fetch_decision("https://example.com/page") is None
