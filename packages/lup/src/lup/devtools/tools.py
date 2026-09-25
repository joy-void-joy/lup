"""The ``tools`` sub-app: serve the MCP servers lup hosts, for a launched runtime.

The same command :mod:`lup.mcp.serve` runs as ``python -m lup.mcp.serve``,
mounted where a project's composed CLI can reach it, so a generated native
tree starts its servers through the program the project already runs.
"""

import typer

from lup.devtools.subapps import subapp
from lup.mcp.serve import serve_command

app = typer.Typer(no_args_is_help=True)
app.command("serve")(serve_command)
SUBAPP = subapp("tools", "Serve the MCP servers a launched session declares", app)
