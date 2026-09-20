"""Inert explicit MCP server used to detect startup authority across resume."""

import sys
from pathlib import Path

from pydantic import BaseModel

from lup.tools.mcp import create_mcp_server, lup_tool, serve_stdio


class Value(BaseModel):
    value: str


@lup_tool("Echo an inert probe value.")
async def echo(params: Value) -> Value:
    return params


if __name__ == "__main__":
    Path(sys.argv[1]).write_text("started")
    serve_stdio(create_mcp_server("probe", tools=[echo]))
