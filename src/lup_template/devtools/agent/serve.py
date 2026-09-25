"""This project's tool groups, built for inspection rather than served.

Serving is the library's: :mod:`lup.mcp.serve` opens the session a server is
started for, validates the server back from its command line, and runs this
project's :func:`~lup_template.agent.toolsets.session_needs` hook before its
groups build. What is left here is reading those groups without a live session
— the ``inspect`` table and the ``repl`` welcome panel — and building them for
one opened session, the way a served process would.
"""

from lup.mcp.serve import context_needs
from lup.tools.mcp import LupMcpTool
from lup.tools.toolsets import SessionNeeds, assembled
from lup.workspace.context import SessionContext
from lup_template.agent.toolsets import declared_tool_groups, session_needs


def collect_tools_by_server(context: SessionContext) -> dict[str, list[LupMcpTool]]:
    """Collect one session's servable tools, grouped by server name.

    The groups come from the one declaration every backend registers, and the
    needs from the hook every served process runs, so what is collected here
    cannot drift from what a launched session is served.
    """
    needs = session_needs(context_needs(context, context.session_id or ""), None)
    return assembled(declared_tool_groups(), needs).groups


def collect_registry_tools() -> dict[str, list[LupMcpTool]]:
    """Enumerate every tool group the declaration can build, for inspection.

    Built against a throwaway directory, so callers with no live session
    (``inspect``, the ``repl`` welcome panel) can list real tools with real
    schemas. The handlers close over the discarded paths: introspect these
    tools, never serve or call them.
    """
    import tempfile
    from pathlib import Path

    from lup.orchestration.reflection import ReviewGate
    from lup.sandbox.container import Sandbox
    from lup.workspace.paths import project_root

    with tempfile.TemporaryDirectory(prefix="lup_toolset_enum_") as tmp:
        base = Path(tmp)
        toolset = assembled(
            declared_tool_groups(),
            SessionNeeds(
                session_dir=base / "session",
                root=project_root(),
                gate=ReviewGate(),
                sandbox=Sandbox(session_id="toolset-enum", shared_dir=base / "shared"),
                realtime_dir=base / "realtime",
            ),
        )
    return toolset.groups
