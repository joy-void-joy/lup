"""Which tool groups this project's sessions carry.

A declaration, not an assembly: :mod:`lup.tools.toolsets` builds a session's
groups, decides which of them this session has anything to put in, and serves
them; what belongs here is the list — lup's own groups, named rather than
rebuilt, and this domain's own, built from whatever its tools need.

Each group becomes one MCP server, the group's name becomes the server's name,
and a tool ``foo`` in group ``notes`` is addressed as ``mcp__notes__foo`` on
every backend. A group that builds nothing for a session is not registered and
not served, so nothing here has to ask whether this session has a sandbox, an
identity, or a mailbox.

Add a domain group by writing its builder and naming it in
:func:`declared_tool_groups`. Everything downstream — server registration, the
names a subprocess backend serves, the servers a native runtime starts — is
read off that one list.
"""

# lup: template: declare each domain tool group in declared_tool_groups.

from lup.tools.mcp import LupMcpTool
from lup.tools.toolsets import (
    SessionNeeds,
    ToolGroup,
    codeintel_group,
    coordination_group,
    ledger_group,
    realtime_group,
    sandbox_group,
)

NOTES_GROUP = "notes"
"""Where this project's own reflection verbs are served, and its delegation one."""

EXAMPLE_GROUP = "example"
"""Placeholder tools with fabricated data — served to no live agent by default;
ask for it by name (``serve-tools --server example``) to try it."""


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


def declared_tool_groups() -> list[ToolGroup]:
    """Every group this project's sessions may carry, in the order they serve.

    Five of them are lup's, named here rather than rebuilt: their tools, their
    companions and the conditions under which a session has them arrive with
    the library, so a pulse added to the coordination server reaches this
    project by a dependency bump rather than by somebody porting it.
    """
    from lup_template.kinds import EDGE_KINDS, LAYOUT, NODE_KINDS

    return [
        notes_group(),
        sandbox_group(),
        codeintel_group(),
        realtime_group(),
        coordination_group(),
        ledger_group(NODE_KINDS, EDGE_KINDS, LAYOUT),
        example_group(),
    ]
