"""Portable roles compile exhaustively without widening exact grants."""

from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from lup.providers.claude.subagents import model_alias, subagent_tools as claude_tools
from lup.providers.codex.app_server import CodexAppServer
from lup.providers.codex.runtime import CodexConversationState, CodexSessionConfig
from lup.providers.codex.subagents import CodexModelTiers, subagent_tools as codex_tools
from lup.sessions.events import SessionId
from lup.types import JsonObject, JsonValue, ModelTier, SubagentCapability, SubagentSpec


def role(**fields: JsonValue) -> SubagentSpec:
    return SubagentSpec.model_validate(
        {"name": "reader", "description": "Reads evidence", "prompt": "Read.", **fields}
    )


@pytest.mark.parametrize("capability", get_args(SubagentCapability.__value__))
def test_every_capability_has_both_compilers(capability: SubagentCapability) -> None:
    spec = role(capabilities=[capability])
    expected = {
        "workspace-read": ["Read", "Glob", "Grep"],
        "web-search": ["WebSearch", "WebFetch"],
    }
    assert claude_tools(spec) == expected[capability]
    native = codex_tools(spec)
    assert native.workspace_read == (capability == "workspace-read")
    assert native.web_search == (capability == "web-search")


@pytest.mark.parametrize("tier", get_args(ModelTier.__value__))
def test_every_tier_has_both_compilers(tier: ModelTier) -> None:
    assert (
        model_alias(tier)
        == {
            "inherit": "inherit",
            "strongest": "opus",
            "balanced": "sonnet",
            "fast": "haiku",
        }[tier]
    )
    assert (
        CodexModelTiers().resolve(tier, inherited="parent")
        == {
            "inherit": "parent",
            "strongest": "gpt-6-astra",
            "balanced": "gpt-5.6-terra",
            "fast": "gpt-5.6-luna",
        }[tier]
    )


def test_exact_grants_keep_the_canonical_vocabulary() -> None:
    spec = role(capabilities=["workspace-read"], tools=["Read", "mcp__notes__inspect"])
    assert spec.tools == ["Read", "mcp__notes__inspect"]
    assert claude_tools(spec) == ["Read", "Glob", "Grep", "mcp__notes__inspect"]
    with pytest.raises(ValueError, match="exact delegated tool grants"):
        codex_tools(spec)


def test_scoped_grants_are_not_widened_to_whole_tools() -> None:
    spec = role(tools=["Bash(git status)"])
    with pytest.raises(ValueError, match="scoped tool grant"):
        claude_tools(spec)
    with pytest.raises(ValueError, match="exact delegated tool grants"):
        codex_tools(spec)


@pytest.mark.parametrize(
    "fields",
    [
        {"capabilities": ["workspace-write"]},
        {"model": "claude-opus-5"},
        {"tools": ["exec_command"]},
        {"native_option": True},
        {"max_turns": 0},
    ],
)
def test_invalid_declarations_do_not_disappear(fields: JsonObject) -> None:
    with pytest.raises(ValidationError):
        role(**fields)


def test_empty_capabilities_do_not_inherit_native_tools() -> None:
    spec = role()
    assert claude_tools(spec) == []
    assert not codex_tools(spec).workspace_read
    assert not codex_tools(spec).web_search


async def test_codex_disables_inherited_mcp_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = CodexAppServer(Path("codex"))
    calls: list[tuple[str, JsonObject]] = []

    async def request(method: str, params: JsonObject) -> JsonValue:
        calls.append((method, params))
        if method == "config/read":
            return {
                "config": {"mcp_servers": {"ambient-writer": {"command": "writer"}}}
            }
        assert method == "thread/start"
        return {"thread": {"id": "restricted"}}

    monkeypatch.setattr(server, "request", request)
    config = CodexSessionConfig(
        cwd=tmp_path,
        sandbox="read-only",
        approval_policy="never",
        delegated_tools=codex_tools(role(capabilities=["workspace-read"])),
    )
    assert config.delegated_tools is not None
    state = CodexConversationState(config, server, None)
    assert await state.ensure_thread() == "restricted"
    assert calls[0] == ("config/read", {"cwd": str(tmp_path), "includeLayers": False})
    assert calls[1][1] == {
        "cwd": str(tmp_path),
        "developerInstructions": "",
        "sandbox": "read-only",
        "approvalPolicy": "never",
        "config": {
            **config.delegated_tools.configuration(),
            "mcp_servers": {"ambient-writer": {"enabled": False}},
        },
    }
    assert await state.ensure_thread() == "restricted"
    assert len(calls) == 2


async def test_codex_restricted_role_cannot_resume_wider_thread(tmp_path: Path) -> None:
    config = CodexSessionConfig(
        cwd=tmp_path,
        sandbox="read-only",
        approval_policy="never",
        delegated_tools=codex_tools(role()),
    )
    state = CodexConversationState(
        config, CodexAppServer(Path("codex")), SessionId(value="old")
    )
    with pytest.raises(ValueError, match="cannot resume"):
        await state.ensure_thread()


def test_codex_restricted_tools_require_enforced_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="read-only sandbox"):
        CodexSessionConfig(cwd=tmp_path, delegated_tools=codex_tools(role()))
