# lup: ignore[set-shape]
# Test fixtures and assertions construct these shapes deliberately.
"""The toolsets registry — single source of truth for both backend paths.

The registry exists to make tool-group drift between backends impossible.
These tests are the tripwire: the names served to subprocess backends must
match the groups the registry actually builds, and the only allowed
difference between the Claude and Codex notes groups is the deliberate
run_subagent asymmetry.
"""

from pathlib import Path

from lup.sandbox.container import Sandbox

from lup_template.agent.toolsets import (
    EXAMPLE_GROUP,
    SessionToolset,
    build_session_toolset,
    tool_group_names,
)


def build(
    base: Path,
    *,
    include_subagent_tool: bool,
    realtime: bool = False,
    with_sandbox: bool = False,
) -> SessionToolset:
    sandbox = None
    if with_sandbox:
        sandbox = Sandbox(session_id="toolset-test", shared_dir=base / "shared")
    return build_session_toolset(
        session_dir=base / "session",
        outputs_dir=base / "outputs",
        include_subagent_tool=include_subagent_tool,
        sandbox=sandbox,
        realtime_dir=(base / "realtime") if realtime else None,
    )


def test_served_names_match_built_groups(tmp_path: Path) -> None:
    for realtime in (False, True):
        toolset = build(
            tmp_path / str(realtime),
            include_subagent_tool=True,
            realtime=realtime,
            with_sandbox=True,
        )
        built = set(toolset["groups"]) - {EXAMPLE_GROUP}
        assert set(tool_group_names(realtime=realtime)) == built


def test_subagent_tool_is_the_only_notes_asymmetry(tmp_path: Path) -> None:
    claude = build(tmp_path / "claude", include_subagent_tool=False)
    codex = build(tmp_path / "codex", include_subagent_tool=True)

    claude_names = {tool.name for tool in claude["groups"]["notes"]}
    codex_names = {tool.name for tool in codex["groups"]["notes"]}

    assert codex_names - claude_names == {"run_subagent"}
    assert claude_names <= codex_names


def test_session_group_requires_realtime_dir(tmp_path: Path) -> None:
    without = build(tmp_path / "without", include_subagent_tool=True)
    with_relay = build(tmp_path / "with", include_subagent_tool=True, realtime=True)

    assert "session" not in without["groups"]
    assert with_relay["groups"]["session"]


def test_output_path_is_the_completion_guard_target(tmp_path: Path) -> None:
    toolset = build(tmp_path, include_subagent_tool=False)
    assert toolset["output_path"] == tmp_path / "session" / "output.json"
    assert not toolset["gate"].reflected
