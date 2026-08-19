"""Refusing a tool per session, asked for portably and rendered by each runtime.

Three fields on a request read alike and do different things, which is the
whole reason this one is worth pinning. ``tools`` is the roster a session is
given and bounds built-ins only; ``allowed_tools`` is auto-approval within
that roster and its own SDK docs say it restricts nothing; ``disallowed_tools``
is the one the SDK documents as removal — "removed from the model's context
and cannot be used, even if they would otherwise be allowed" — and it is not
confined to built-ins.

Without it a caller wanting "everything except this one" had to enumerate the
complement, which is a roster that has to be restated every time the tool set
grows and silently re-admits whatever was added. The failure being guarded
here is the same shape as the effort field's: a value that reaches nothing
and a session that runs wider than it asked to, with nothing raised.
"""

from pathlib import Path

import pytest

from lup.adapters.claude.runtime import build_claude_options
from lup.adapters.claude.selection import claude_config
from lup.adapters.codex.selection import codex_config
from lup.runtime.selection import SessionRequest


def test_a_request_naming_no_refusal_leaves_claude_blocking_nothing() -> None:
    """Absence has to stay absent, or every session gains a block list."""
    assert claude_config(SessionRequest(cwd=Path("."))).disallowed_tools == []


def test_a_refusal_reaches_claude_configuration() -> None:
    """The field existing on the request means nothing until it renders."""
    request = SessionRequest(cwd=Path("."), disallowed_tools=["Bash"])

    assert claude_config(request).disallowed_tools == ["Bash"]


def test_a_refusal_reaches_the_provider_call() -> None:
    """Rendering into our own config is half the trip; the SDK options are the rest."""
    options = build_claude_options(
        claude_config(SessionRequest(cwd=Path("."), disallowed_tools=["Bash"])),
        binding=lambda: None,
        resume=None,
        session_id=None,
    )

    assert options.disallowed_tools == ["Bash"]


def test_a_refusal_names_a_tool_no_roster_mentions() -> None:
    """The point of a block list is naming what a roster never enumerated."""
    request = SessionRequest(
        cwd=Path("."), tools=["Read"], disallowed_tools=["mcp__research__research"]
    )
    config = claude_config(request)

    assert config.tools == ["Read"]
    assert config.disallowed_tools == ["mcp__research__research"]


def test_the_three_tool_fields_stay_independent() -> None:
    """They read alike, so a rendering that conflated two would look correct."""
    config = claude_config(
        SessionRequest(
            cwd=Path("."),
            tools=["Read", "Bash"],
            allowed_tools=["Read"],
            disallowed_tools=["Bash"],
        )
    )

    assert config.tools == ["Read", "Bash"]
    assert config.allowed_tools == ["Read"]
    assert config.disallowed_tools == ["Bash"]


def test_codex_refuses_a_refusal_it_cannot_apply_per_session() -> None:
    """Its dispatcher is per harness tree, so honouring this would over-apply it."""
    request = SessionRequest(cwd=Path("."), disallowed_tools=["Bash"])

    with pytest.raises(ValueError, match="disallowed_tools"):
        codex_config(request)


def test_codex_stays_silent_when_no_refusal_was_asked_for() -> None:
    """A refusal nobody requested must not become a runtime that cannot open."""
    assert codex_config(SessionRequest(cwd=Path("."))).sandbox is None


def test_codex_names_every_field_it_refuses_at_once() -> None:
    """One message per session, or a caller fixes four fields in four attempts."""
    request = SessionRequest(
        cwd=Path("."),
        tools=["Read"],
        allowed_tools=["Read"],
        disallowed_tools=["Bash"],
    )

    with pytest.raises(ValueError) as refusal:
        codex_config(request)

    for field in ("tools", "allowed_tools", "disallowed_tools"):
        assert field in str(refusal.value)
