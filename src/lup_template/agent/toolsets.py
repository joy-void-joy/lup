"""Which tool groups this project's sessions carry.

A declaration, not an assembly: :mod:`lup.tools.toolsets` builds a session's
groups, decides which of them this session has anything to put in, and
:mod:`lup.mcp.serve` serves them; what belongs here is the list — lup's own
servers, named rather than rebuilt, and this domain's own groups, built from
whatever their tools need.

Each group becomes one MCP server, the group's name becomes the server's name,
and a tool ``foo`` in group ``notes`` is addressed as ``mcp__notes__foo`` on
every backend. A group that builds nothing for a session is not registered and
serves nothing, so nothing here has to ask whether this session has a sandbox,
an identity, or a mailbox.

Add a domain group by writing its builder and naming it in
:func:`declared_tool_servers`. Everything downstream — server registration, the
names a subprocess backend serves, the servers a native runtime starts — is
read off that one list.
"""

# lup: template: declare each domain tool group in declared_tool_servers.

import atexit

from pydantic import TypeAdapter

from lup.mcp import CodeIntel, Coordination, Group, HostedServer, Ledger
from lup.tools.mcp import LupMcpTool
from lup.tools.toolsets import (
    SessionNeeds,
    ToolGroup,
    realtime_group,
    sandbox_group,
)

NOTES_GROUP = "notes"
"""Where this project's own reflection verbs are served, and its delegation one."""

EXAMPLE_GROUP = "example"
"""Placeholder tools with fabricated data — served to no live agent by default;
ask for it by name (``tools serve`` with its server) to try it."""


# lup: defer: the `notes` group is the reflection module's, and it also carries
# `run_subagent`, so a project declining reflection loses the delegation verb
# from its harness sessions. Serve delegation from a group core or project owns.
def notes_group(name: str = NOTES_GROUP) -> ToolGroup:
    """This domain's own verbs: structured self-review, and delegation.

    The reviewer runs as a nested agent on the auxiliary model, so the
    reflection tools are this project's rather than the library's: what a
    reviewer is asked and what counts as approval are a domain's question.
    """

    def tools(needs: SessionNeeds) -> list[LupMcpTool]:
        from lup_template.agent.config import aux_model
        from lup_template.agent.tools.reflect import create_reflect_tools

        kit = create_reflect_tools(
            session_dir=needs.session_dir,
            outputs_dir=needs.outputs_dir,
            gate=needs.gate,
            reviewer_model=aux_model(),
        )
        built = list(kit["tools"])
        return [*built, needs.subagent_tool] if needs.subagent_tool else built

    return ToolGroup(name=name, tools=tools)


def example_group(name: str = EXAMPLE_GROUP) -> ToolGroup:
    """The scaffold's demonstration tools, which answer with fabricated data."""

    def tools(needs: SessionNeeds) -> list[LupMcpTool]:
        from lup_template.agent.tools.example import EXAMPLE_TOOLS

        return list(EXAMPLE_TOOLS)

    return ToolGroup(name=name, tools=tools, serving="named")


def declared_tool_servers() -> list[HostedServer]:
    """Every server this project's sessions may carry, in the order they serve.

    Three of them are lup's, named here rather than rebuilt: their tools,
    their companions and the conditions under which a session has them arrive
    with the library, so a pulse added to the coordination server reaches this
    project by a dependency bump rather than by somebody porting it. The
    container's and the relay's are lup's groups served as this project
    serves them: the container is the one :func:`session_needs` starts where
    this project's settings enable one, never one the server starts itself.
    """
    from lup_template.kinds import EDGE_KINDS, LAYOUT, NODE_KINDS

    return [
        Group(builder=notes_group),
        Group(builder=sandbox_group),
        CodeIntel(),
        Group(builder=realtime_group),
        Coordination(),
        Ledger(nodes=NODE_KINDS, edges=EDGE_KINDS, layout=LAYOUT),
        Group(builder=example_group),
    ]


def declared_tool_groups() -> list[ToolGroup]:
    """The groups those servers serve, for the assembly a session builds itself."""
    return [server.group() for server in declared_tool_servers()]


def subagent_tool() -> LupMcpTool:
    """The delegation verb this project's sessions carry, over its own specs."""
    from lup.orchestration.subagents import create_run_subagent_tool
    from lup_template.agent.core import build_subagent_factory
    from lup_template.agent.subagents import get_subagent_specs

    return create_run_subagent_tool(
        get_subagent_specs(), factory_recipe=build_subagent_factory
    )


def session_needs(needs: SessionNeeds, runtime: str | None) -> SessionNeeds:
    """What this project adds to a session its servers are started for.

    The needs hook every served group of this project runs under: the engine
    the runtime names, so a nested agent opens on the same backend; a
    container, where this project's settings enable one; and its delegation
    verb, which the notes group carries.

    The container is started here rather than inside the group that serves
    its tools, because it outlives that group: it is registered for teardown
    when this process exits, and a group builder is not where a process-wide
    lifetime belongs.
    """
    from lup.sandbox.container import Sandbox
    from lup_template.agent.config import Engine, settings

    if runtime is not None:
        settings.agent_sdk = TypeAdapter(Engine).validate_python(runtime)
    sandbox = needs.sandbox
    if sandbox is None and settings.sandbox_enabled:
        sandbox = Sandbox(
            session_id=needs.session_dir.name,
            shared_dir=needs.session_dir / "sandbox_shared",
        )
        atexit.register(sandbox.stop)
    return needs.model_copy(
        update={"sandbox": sandbox, "subagent_tool": subagent_tool()}
    )
