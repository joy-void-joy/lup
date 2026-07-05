"""Single source of truth for the agent's MCP tool groups.

A *toolset* is the session's tools sorted into named groups, not one flat
list. The grouping is what MCP needs: each group becomes one MCP server, the
group name becomes the server name, and a tool ``foo`` in group ``notes`` is
addressed as ``mcp__notes__foo`` on every backend. Grouping also lets the
policy enable or withhold a whole capability (a server) at once.

Both backend paths consume this module — the Claude path registers the groups
in-process (``core.build_options``), the Codex/OpenAI path serves them over
stdio (``lup-devtools agent serve-tools``) and selects them by name
(``core.build_codex_adapter``) — so adding a group or tool here reaches every
backend, and there is deliberately nowhere else to add one.

TEMPLATE: register tool groups in build_session_toolset + tool_group_names.
Add each domain group in :func:`build_session_toolset`, and its name in
:func:`tool_group_names` when it should be served to subprocess backends.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from lup.mcp import LupMcpTool
    from lup.reflect import ReflectionGate
    from lup.sandbox import Sandbox

ServerGroup = Literal["notes", "sandbox", "session", "example"]
"""A tool-group name this registry can build — the group vocabulary every
consumer shares: server registration (``core.build_inprocess_options``),
subprocess serving and CLI selection (``lup-devtools agent serve-tools
--server``). Extend it together with :func:`build_session_toolset` when
adding a group. (A plain alias, not a ``type`` statement, so typer can
read the choices off the annotation.)"""

NOTES_GROUP: ServerGroup = "notes"
SANDBOX_GROUP: ServerGroup = "sandbox"
SESSION_GROUP: ServerGroup = "session"
EXAMPLE_GROUP: ServerGroup = "example"
"""Placeholder tools with fabricated data — never served to a live agent
by default; select explicitly (``serve-tools --server example``) to test."""


class SessionToolset(TypedDict):
    """Return type of :func:`build_session_toolset`."""

    groups: dict[ServerGroup, list["LupMcpTool"]]
    gate: "ReflectionGate"
    output_path: Path


def tool_group_names(*, realtime: bool) -> tuple[ServerGroup, ...]:
    """Group names served to subprocess backends (Codex/OpenAI).

    Excludes :data:`EXAMPLE_GROUP`. Uses the same name constants as
    :func:`build_session_toolset`; ``test_toolsets`` asserts the two
    stay aligned.
    """
    if realtime:
        return (NOTES_GROUP, SANDBOX_GROUP, SESSION_GROUP)
    return (NOTES_GROUP, SANDBOX_GROUP)


def build_session_toolset(
    *,
    session_dir: Path,
    outputs_dir: Path | None,
    gate: "ReflectionGate | None" = None,
    include_subagent_tool: bool,
    sandbox: "Sandbox | None" = None,
    realtime_dir: Path | None = None,
) -> SessionToolset:
    """Build every MCP tool group for one session.

    Args:
        session_dir: Session directory (``output.json``, review artifacts).
        outputs_dir: Past outputs for reviewer calibration.
        gate: Shared reflection gate. None creates an in-memory gate (the
            Claude in-process path); subprocess paths pass a file-backed
            gate so the parent and the tool subprocess agree.
        include_subagent_tool: True on backends without native subagents —
            the ``run_subagent`` tool then serves the same specs the Claude
            adapter converts to native ``AgentDefinition``s. False on
            Claude, which would otherwise expose both mechanisms at once.
        sandbox: Session sandbox whose tools form the ``sandbox`` group.
        realtime_dir: Relay mailbox directory; presence adds the
            ``session`` group (persistent-mode tools), wired with a
            file-backed reflection gate so this domain keeps its
            meta-before-sleep requirement — reflection is opt-in and the
            library imposes none by default.

    Returns:
        The groups plus the shared gate and the submitted-output path,
        which hook wiring (reflection gate, completion guard) needs.
    """
    from lup.output import create_output_tool
    from lup.subagents import create_run_subagent_tool

    from lup_template.agent.config import aux_model, settings
    from lup_template.agent.models import AgentOutput
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tools.example import EXAMPLE_TOOLS
    from lup_template.agent.tools.reflect import create_reflect_tools

    reflect_kit = create_reflect_tools(
        session_dir=session_dir,
        outputs_dir=outputs_dir,
        gate=gate,
        reviewer_model=aux_model(),
    )
    output_kit = create_output_tool(
        AgentOutput,
        session_dir=session_dir,
        gate=reflect_kit["gate"],
        reflection_tool_name="mcp__notes__review",
    )

    notes_tools = [*reflect_kit["tools"], *output_kit["tools"]]
    if include_subagent_tool:
        notes_tools.append(
            create_run_subagent_tool(get_subagent_specs(), default_model=settings.model)
        )

    groups: dict[ServerGroup, list[LupMcpTool]] = {NOTES_GROUP: notes_tools}

    if sandbox is not None:
        groups[SANDBOX_GROUP] = sandbox.create_tools()

    if realtime_dir is not None:
        from lup.realtime.relay import RealtimeMailbox, create_realtime_relay_tools
        from lup.reflect import ReflectionGate

        meta_flag = RealtimeMailbox(realtime_dir).meta_flag_path
        groups[SESSION_GROUP] = create_realtime_relay_tools(
            realtime_dir, gate=ReflectionGate(flag_path=meta_flag)
        )

    groups[EXAMPLE_GROUP] = list(EXAMPLE_TOOLS)

    return SessionToolset(
        groups=groups,
        gate=reflect_kit["gate"],
        output_path=output_kit["output_path"],
    )
