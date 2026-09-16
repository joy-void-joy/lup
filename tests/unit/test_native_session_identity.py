"""What a session nobody launched is known by: the id its runtime gave the process.

Written against the collision the roster had: a natively opened tool server
fell back to the name of the session it opened — the one constant `harness`
— so every unlaunched session in a worktree joined as one member while its
hooks answered to the runtime's own session id. What is asserted is that the
server now asks the runtime's adapter, that the launcher's id still outranks
the answer, and that no answer serves no coordination verbs at all.
"""

import pytest

from lup.coordination.identity import MEMBER_ENV
from lup.coordination.peer_tools import RosterPulse
from lup.providers.claude.identity import CLAUDE_SESSION_ENV
from lup.providers.identity import native_session_id
from lup.workspace.context import SESSION_DIR_ENV
from lup_template.devtools.agent import serve
from lup_template.harness.catalog import HARNESS_SESSION


def unlaunched(monkeypatch: pytest.MonkeyPatch) -> None:
    """No launcher minted an id, and no adapter relayed a session."""
    monkeypatch.delenv(MEMBER_ENV, raising=False)
    monkeypatch.delenv(SESSION_DIR_ENV, raising=False)


def test_claude_hands_its_servers_the_session_id_and_codex_hands_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLAUDE_SESSION_ENV, "abc-123")

    assert native_session_id("claude") == "abc-123"
    assert native_session_id("codex") == ""
    assert native_session_id("openai") == ""

    monkeypatch.delenv(CLAUDE_SESSION_ENV)

    assert native_session_id("claude") == ""


def test_a_native_server_joins_under_the_id_its_runtime_gave_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unlaunched(monkeypatch)
    context = serve.harness_session_context(HARNESS_SESSION)

    toolset = serve.collect_session_toolset(context, identity="abc-123")

    [pulse] = toolset["companions"]["coordination"] if toolset else []
    assert isinstance(pulse, RosterPulse)
    assert pulse.member_id == "abc-123"


def test_a_native_server_with_no_identity_serves_no_coordination_verbs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing, rather than a member every session of the worktree would share."""
    unlaunched(monkeypatch)
    context = serve.harness_session_context(HARNESS_SESSION)

    toolset = serve.collect_session_toolset(context, identity="")

    assert toolset is not None
    assert "coordination" not in toolset["groups"]
    assert toolset["companions"] == {}


def test_the_launcher_s_id_outranks_the_runtime_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unlaunched(monkeypatch)
    monkeypatch.setenv(MEMBER_ENV, "launched1")
    context = serve.harness_session_context(HARNESS_SESSION)

    toolset = serve.collect_session_toolset(context, identity="abc-123")

    [pulse] = toolset["companions"]["coordination"] if toolset else []
    assert isinstance(pulse, RosterPulse)
    assert pulse.member_id == "launched1"


def test_serving_for_claude_lists_the_coordination_verbs_under_the_runtime_s_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole path: `--runtime claude --session harness`, no launcher, one runtime id."""
    unlaunched(monkeypatch)
    monkeypatch.setenv(CLAUDE_SESSION_ENV, "abc-123")

    serve.serve_tools(True, "coordination", HARNESS_SESSION, "claude")
    with_identity = capsys.readouterr().out
    monkeypatch.delenv(CLAUDE_SESSION_ENV)
    serve.serve_tools(True, "coordination", HARNESS_SESSION, "claude")
    without = capsys.readouterr().out

    assert "coordination_peers" in with_identity
    assert without == ""
