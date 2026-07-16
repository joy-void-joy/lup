# lup: ignore[dict-str-payload, os-environ, set-shape]
# Test fixtures and assertions construct these shapes deliberately.
"""Round-trip test of the serve-tools subprocess with session-context env.

This is the wiring the Codex/OpenAI adapters depend on: tools are
constructed in a separate process from relayed env vars, the reflection
gate crosses the process boundary through a flag file, and the output
and metrics artifacts land in the session directory where the parent
process reads them. No LLM involved.
"""

import os
from pathlib import Path

import pytest
import sh
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lup.workspace.context import (
    GATE_FLAG_ENV,
    OUTPUTS_DIR_ENV,
    REALTIME_DIR_ENV,
    SESSION_DIR_ENV,
    SESSION_ID_ENV,
)
from lup.realtime.relay import MetaEvent, RealtimeMailbox, ReplyEvent
from lup.sandbox.container import Sandbox

from lup_template.agent.toolsets import (
    EXAMPLE_GROUP,
    build_session_toolset,
    tool_group_names,
)

pytestmark = pytest.mark.integration


async def test_serve_tools_session_round_trip(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    gate_flag = tmp_path / "gate_flag"

    params = StdioServerParameters(
        command="uv",
        args=["run", "lup-devtools", "agent", "serve-tools"],
        env={
            **os.environ,
            SESSION_DIR_ENV: str(session_dir),
            GATE_FLAG_ENV: str(gate_flag),
            OUTPUTS_DIR_ENV: str(tmp_path / "outputs"),
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {"review", "submit_output"} <= names
            # The example placeholder ships fabricated data and is served to no
            # live agent by default — matching the Claude path. It is reachable
            # only via an explicit --server example.
            assert "search_example" not in names
            assert "fetch_example" not in names

            premature = await session.call_tool("submit_output", {"summary": "early"})
            assert premature.isError is True
            assert not (session_dir / "output.json").exists()

            reviewed = await session.call_tool(
                "review",
                {
                    "assessment": "wiring test",
                    "confidence": 0.9,
                    "tool_audit": "none used",
                    "process_reflection": "n/a",
                    "skip_reviewer": True,
                },
            )
            assert reviewed.isError is False
            assert gate_flag.exists()

            accepted = await session.call_tool(
                "submit_output", {"summary": "done", "confidence": 0.8}
            )
            assert accepted.isError is False

    assert (session_dir / "output.json").exists()
    assert (session_dir / "metrics.json").exists()


def served_names(env: dict[str, str], *args: str) -> set[str]:
    """Run ``serve-tools --list`` with the given selector; return the names."""
    uv = sh.Command("uv")
    out = uv("run", "lup-devtools", "agent", "serve-tools", "--list", *args, _env=env)
    return {line for line in str(out).splitlines() if line}


def test_served_group_names_match_toolset_registry(tmp_path: Path) -> None:
    """serve-tools must serve exactly what the toolsets registry builds.

    ``build_session_toolset`` is the declared single source of tool groups
    for every backend, and the stdio server derives from it — so each
    ``--server <group>`` selection lists precisely that group's registry
    tools, and the default serves every group but the example placeholder.
    """
    session_dir = tmp_path / "session"
    realtime_dir = session_dir / "realtime"
    env = {
        **os.environ,
        SESSION_DIR_ENV: str(session_dir),
        GATE_FLAG_ENV: str(tmp_path / "gate_flag"),
        OUTPUTS_DIR_ENV: str(tmp_path / "outputs"),
        SESSION_ID_ENV: "registry-match",
        REALTIME_DIR_ENV: str(realtime_dir),
    }

    groups = build_session_toolset(
        session_dir=session_dir,
        outputs_dir=tmp_path / "outputs",
        sandbox=Sandbox(
            session_id="registry-match", shared_dir=session_dir / "sandbox_shared"
        ),
        realtime_dir=realtime_dir,
    )["groups"]

    for group in (*tool_group_names(realtime=True), EXAMPLE_GROUP):
        expected = {tool.name for tool in groups[group]}
        assert served_names(env, "--server", group) == expected

    default_expected = {
        tool.name
        for name, tools in groups.items()
        if name != EXAMPLE_GROUP
        for tool in tools
    }
    assert served_names(env) == default_expected


async def test_serve_tools_realtime_session_group(tmp_path: Path) -> None:
    """The relay round-trip the Codex realtime mode depends on.

    The session tool group is served only when the realtime directory is
    relayed; tool calls inside the subprocess must land as mailbox
    artifacts the parent process can consume.
    """
    session_dir = tmp_path / "session"
    realtime_dir = session_dir / "realtime"

    params = StdioServerParameters(
        command="uv",
        args=["run", "lup-devtools", "agent", "serve-tools", "--server", "session"],
        env={
            **os.environ,
            SESSION_DIR_ENV: str(session_dir),
            GATE_FLAG_ENV: str(tmp_path / "gate_flag"),
            OUTPUTS_DIR_ENV: str(tmp_path / "outputs"),
            REALTIME_DIR_ENV: str(realtime_dir),
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {
                "reply",
                "schedule_action",
                "debounce",
                "sleep",
                "remind",
                "context",
                "meta",
            } == names

            premature = await session.call_tool("sleep", {"seconds": 60})
            assert premature.isError is True

            replied = await session.call_tool(
                "reply", {"messages": [{"message": "hello from the subprocess"}]}
            )
            assert replied.isError is False

            await session.call_tool("meta", {"thought": "relay wiring test"})
            recorded = await session.call_tool("sleep", {"seconds": 60})
            assert recorded.isError is False

    mailbox = RealtimeMailbox(realtime_dir)
    events = mailbox.read_new_events()
    assert [type(e) for e in events] == [ReplyEvent, MetaEvent]

    request = mailbox.consume_sleep_request()
    assert request is not None
    assert request.seconds == 60
