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
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lup.paths import GATE_FLAG_ENV, OUTPUTS_DIR_ENV, SESSION_DIR_ENV

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
            assert {
                "search_example",
                "fetch_example",
                "review",
                "submit_output",
            } <= names

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
