"""Opening the session a tool server serves, and handing it to the library.

What a server serves is the library's: :mod:`lup.tools.toolsets` builds the
declared groups for a session, decides which of them this one has anything to
put in, and serves a group over MCP stdio. What is this application's is the
session — which directories it has, whether a container was started for it,
what the roster knows it by — so this module resolves those into the
:class:`~lup.tools.toolsets.SessionNeeds` every builder reads.
"""

import atexit

import typer

from lup.coordination.identity import session_cli_name
from lup.coordination.wake import WakePath
from lup.providers.identity import native_session_id, native_wake
from lup.tools.mcp import LupMcpTool
from lup.tools.toolsets import (
    SessionNeeds,
    SessionToolset,
    assembled,
    named_only,
    serve_toolset,
)
from lup.workspace.context import SessionContext
from lup_template.agent.config import Engine
from lup_template.agent.toolsets import NOTES_GROUP, declared_tool_groups


def collect_tools_by_server(context: SessionContext) -> dict[str, list[LupMcpTool]]:
    """Collect one session's servable tools, grouped by server name.

    The groups come from the one declaration every backend registers, so what
    is served cannot drift from what the session's own path registers.
    """
    return assembled(declared_tool_groups(), session_needs(context, None)).groups


def subagent_tool() -> LupMcpTool:
    """The delegation verb this project's sessions carry, over its own specs."""
    from lup.orchestration.subagents import create_run_subagent_tool
    from lup_template.agent.core import build_subagent_factory
    from lup_template.agent.subagents import get_subagent_specs

    return create_run_subagent_tool(
        get_subagent_specs(), factory_recipe=build_subagent_factory
    )


def session_needs(
    context: SessionContext, identity: str | None, wake: WakePath = WakePath()
) -> SessionNeeds:
    """What one session gives its groups, resolved from the context it opened.

    *identity* is what the coordination group falls back to when no launcher
    minted a member id: the session's own id where an adapter relayed one in
    the context, and for a natively opened session whatever its runtime gave
    the process — which the caller resolves, since the context names where the
    session's notes go and not who it is.

    A sandbox is started here rather than inside the group that serves its
    tools, because it outlives that group: the container is registered for
    teardown when this process exits, and a group builder is not where a
    process-wide lifetime belongs.
    """
    from lup.coordination.identity import session_member_id
    from lup.orchestration.reflection import ReviewGate
    from lup.sandbox.container import Sandbox
    from lup.workspace.paths import project_root
    from lup_template.agent.config import settings

    sandbox = None
    if context.session_id and settings.sandbox_enabled:
        sandbox = Sandbox(
            session_id=context.session_id,
            shared_dir=context.session_dir / "sandbox_shared",
        )
        atexit.register(sandbox.stop)

    named = identity if identity is not None else (context.session_id or "")
    return SessionNeeds(
        session_dir=context.session_dir,
        root=project_root(),
        gate=ReviewGate(flag_path=context.gate_flag),
        outputs_dir=context.outputs_dir,
        sandbox=sandbox,
        realtime_dir=context.realtime_dir,
        subagent_tool=subagent_tool(),
        member=session_member_id(named),
        wake=wake,
    )


def collect_session_toolset(
    context: SessionContext | None,
    identity: str | None = None,
    wake: WakePath = WakePath(),
) -> SessionToolset | None:
    """The session's whole toolset — groups and their servers' companions — or nothing.

    Nothing where no session is open, because every group closes over a
    session's directories, and a server with no session to serve is one
    nothing asked for: the caller says so rather than serving a toolset built
    against directories that do not exist.
    """
    if context is None:
        return None
    return assembled(declared_tool_groups(), session_needs(context, identity, wake))


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


def harness_session_context(name: str) -> SessionContext:
    """Open the session a natively launched tool server serves.

    An adapter-launched server is handed a session that already exists; a
    server a native runtime starts is the first thing in that session to run,
    so it opens one under the name it was given. The name is the whole
    identity, and every group of one runtime's session is started with the
    same name, so those processes agree on where session state lives without
    a channel between them.
    """
    from lup.workspace.notes import session_gate_flag, setup_notes

    notes = setup_notes(session_id=name, task_id=name, type="harness")
    return SessionContext(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        gate_flag=session_gate_flag(name),
        session_id=name,
        task_id=name,
    )


def serve_tools(
    list_only: bool,
    server_group: str | None,
    session: str | None = None,
    runtime: Engine | None = None,
) -> None:
    """Serve the collected tools over MCP stdio (see the ``serve-tools`` command)."""
    from lup.observability.metrics import configure_metrics, metrics_path
    from lup.workspace.context import read_session_context
    from lup_template.agent.config import settings

    if runtime is not None:
        settings.agent_sdk = runtime

    context = read_session_context()
    identity: str | None = None
    wake = WakePath()
    if context is None and session is not None:
        # A native runtime relays no context, so the session opened here is
        # named for where its notes go and not for who it is. What the roster
        # knows it by is the launcher's id where one was minted, otherwise the
        # id the runtime gave this process, which its adapter reads — and
        # nothing where the runtime hands its servers none.
        context = harness_session_context(session)
        identity = native_session_id(runtime) if runtime is not None else ""
        # What would make this session look, which is a different question from
        # what it is called on the roster and answered by a different half: the
        # name reaches a peer's own message tool, so only the adapter for the
        # runtime that resolves that name can say whether there is one.
        wake = (
            native_wake(runtime, session_cli_name())
            if runtime is not None
            else WakePath()
        )
    if context is not None:
        configure_metrics(metrics_path(context.session_dir))

    groups = declared_tool_groups()
    declared = [group.name for group in groups]
    if server_group is not None and server_group not in declared:
        raise typer.BadParameter(
            f"no group named {server_group!r}: this project declares "
            f"{', '.join(declared)}"
        )
    toolset = collect_session_toolset(context, identity, wake)
    if toolset is None:
        typer.echo(
            "no session context and no --session name, so there is nothing to "
            "serve: an adapter relays a session in the environment and a "
            "native runtime names one on the command line",
            err=True,
        )
        raise typer.Exit(1)
    if list_only:
        for tool in toolset.served(server_group, named_only(groups)):
            typer.echo(tool.name)
        return
    serve_toolset(toolset, groups, server_group, NOTES_GROUP)
