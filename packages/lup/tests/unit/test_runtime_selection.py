"""Selecting a runtime is one assignment, and both runtimes answer it.

The autonomy roster is read out of the type rather than restated, so a degree
added to :data:`~lup.providers.selection.SessionAutonomy` fails here until every
runtime has spelled it — which is the whole point of the request being a
declaration each runtime renders.
"""

from pathlib import Path
from typing import get_args

import pytest

from lup.providers.claude.runtime import ClaudeSessionConfig
from lup.providers.claude.selection import CLAUDE_AUTONOMY, CLAUDE_RUNTIME
from lup.providers.codex.runtime import CodexSessionConfig
from lup.providers.codex.selection import (
    CODEX_AUTONOMY,
    CODEX_RUNTIME,
    codex_mcp_server,
)
from lup.policy.hooks import LupHooksConfig
from lup.tools.mcp import create_mcp_server
from lup.client import Client
from lup.providers.selection import Runtime, SessionAutonomy, SessionRequest

AUTONOMY_DEGREES = get_args(SessionAutonomy.__value__)


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_runtime_carries_its_own_login(runtime: Runtime) -> None:
    assert runtime.name
    assert runtime.login.config_home_env
    assert runtime.login.credentials_file


@pytest.mark.parametrize("degree", AUTONOMY_DEGREES)
def test_every_runtime_spells_every_degree_of_autonomy(degree: str) -> None:
    assert degree in CLAUDE_AUTONOMY
    assert degree in CODEX_AUTONOMY


def test_claude_renders_the_whole_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rendered: list[ClaudeSessionConfig] = []

    def record(config: ClaudeSessionConfig) -> Client:
        rendered.append(config)
        return Client(lambda resume=None: None)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr("lup.providers.claude.selection.create_claude", record)
    CLAUDE_RUNTIME.session_factory(
        SessionRequest(
            model="a-model",
            instructions="be brief",
            cwd=tmp_path,
            autonomy="unattended",
            allowed_tools=["Read"],
            max_turns=3,
            environment={"KEEP": "1"},
            hooks=LupHooksConfig(),
        )
    )

    config = rendered[0]
    assert config.model == "a-model"
    assert config.system_prompt == "be brief"
    assert config.cwd == tmp_path
    assert config.permission_mode == "bypassPermissions"
    assert config.allowed_tools == ["Read"]
    assert config.max_turns == 3
    assert config.environment["KEEP"] == "1"
    assert CLAUDE_RUNTIME.login.config_home_env in config.environment
    assert config.hooks is not None


def test_codex_renders_what_it_can_spell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rendered: list[CodexSessionConfig] = []

    def record(config: CodexSessionConfig) -> Client:
        rendered.append(config)
        return Client(lambda resume=None: None)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr("lup.providers.codex.selection.create_codex", record)
    CODEX_RUNTIME.session_factory(
        SessionRequest(
            model="a-model",
            instructions="be brief",
            cwd=tmp_path,
            autonomy="accept_edits",
            tool_servers={"group": {"command": "uv", "args": ["run", "tools"]}},
        )
    )

    config = rendered[0]
    assert config.model == "a-model"
    assert config.developer_instructions == "be brief"
    assert config.sandbox == "workspace-write"
    assert config.writable_roots == [tmp_path]
    assert config.mcp_servers["group"].command == "uv"
    assert config.mcp_servers["group"].args == ["run", "tools"]


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"tools": ["Read"]},
        {"allowed_tools": ["Read"]},
        {"hooks": LupHooksConfig()},
    ],
    ids=["tools", "allowed_tools", "hooks"],
)
def test_codex_refuses_what_it_cannot_govern(
    request_kwargs: dict[str, object], tmp_path: Path
) -> None:
    """A field Codex has no words for is an error, never a silent drop."""
    with pytest.raises(ValueError, match="no session-level"):
        CODEX_RUNTIME.session_factory(
            SessionRequest(cwd=tmp_path, **request_kwargs)  # pyright: ignore[reportArgumentType]
        )


def test_codex_will_not_infer_the_directory_it_sandboxes_against() -> None:
    with pytest.raises(ValueError, match="cwd"):
        CODEX_RUNTIME.session_factory(SessionRequest(model="a-model"))


def test_codex_rejects_a_tool_group_it_cannot_launch() -> None:
    with pytest.raises(ValueError, match="subprocess"):
        codex_mcp_server("group", {"type": "sse", "url": "https://example.test"})


def test_codex_will_not_relaunch_a_hosted_tool_group_as_a_subprocess() -> None:
    """The refusal that stops a session's own state being answered around.

    A hosted server reads the process hosting it — the context variables
    scoping the session it answers inside, its clients, its caches. Relaunched
    as a subprocess it would not fail: it would answer every call from
    defaults, confidently, and nothing downstream could tell the difference.
    So the refusal has to say why, or the transport change it looks like is
    the repair somebody reaches for.
    """
    with pytest.raises(ValueError, match="answer from defaults"):
        codex_mcp_server("group", create_mcp_server("group"))


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_workspace_home_is_named_in_the_runtime_that_opens_it(
    runtime: Runtime, tmp_path: Path
) -> None:
    """Where a workspace's sessions write is a per-runtime fact, so the whole
    selection has to carry it. An application deriving one runtime's home for
    every session points the other at a directory its CLI never reads, while
    dropping the home its profile selected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    environment = runtime.workspace_environment(
        {runtime.login.config_home_env: str(tmp_path / "account")}, workspace
    )

    assert runtime.login.config_home_env in environment


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_request_costs_nothing_to_state_and_is_contained_when_opened(
    runtime: Runtime, tmp_path: Path
) -> None:
    """Stating a request touches no filesystem, so building one cannot fail on
    a home it has no reason to need yet. The home appears when the runtime
    opens the session, which is the only moment both the workspace and the
    runtime are known."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    request = SessionRequest(cwd=workspace)

    assert runtime.login.config_home_env not in request.environment
    assert runtime.login.config_home_env in runtime.contained(request).environment


@pytest.mark.parametrize("runtime", [CLAUDE_RUNTIME, CODEX_RUNTIME])
def test_a_request_naming_no_workspace_has_nothing_to_be_contained_against(
    runtime: Runtime,
) -> None:
    request = SessionRequest()

    assert runtime.contained(request) == request
