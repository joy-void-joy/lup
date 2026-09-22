"""Claude's built-in roster and enforcement of explicit session grants."""

from collections.abc import Iterator, Mapping

from lup.tools.mcp import LupMcpServerConfig, McpServerEntry
from lup.tools.native import NativeToolGroup, NativeTools, native_grants


def claude_native_tools(grants: NativeTools) -> list[str] | None:
    """Expand grants; None here is Claude's explicit all-builtins preset."""
    groups = {
        NativeToolGroup.READ: ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        NativeToolGroup.WEB: ["WebFetch", "WebSearch"],
        NativeToolGroup.WRITE: ["Write", "Edit", "NotebookEdit"],
        NativeToolGroup.SHELL: ["Bash", "TaskOutput", "TaskStop"],
    }
    exact = {
        "Read",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "Write",
        "Edit",
        "NotebookEdit",
        "Bash",
        "TaskOutput",
        "TaskStop",
        "Agent",
        "Task",
        "Skill",
        "TodoWrite",
        "TaskCreate",
        "TaskUpdate",
        "TaskGet",
        "TaskList",
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        "ListMcpResources",
        "ReadMcpResource",
        "Monitor",
    }
    requested = native_grants(grants)

    def expanded() -> Iterator[str]:
        for grant in requested:
            match grant:
                case NativeToolGroup.ALL:
                    continue
                case NativeToolGroup():
                    yield from groups[grant]
                case str() if grant in exact:
                    yield grant
                case _:
                    raise ValueError(
                        f"Claude cannot enforce native tool grant {grant!r}"
                    )

    roster = list(dict.fromkeys(expanded()))
    return None if NativeToolGroup.ALL in requested else roster


def claude_tool_allowed(
    name: str,
    native: list[str] | None,
    servers: Mapping[str, McpServerEntry],
) -> bool:
    """An inherited MCP tool is never authorized by a native-tools grant."""
    if not name.startswith("mcp__"):
        return native is None or name in native
    return any(
        name in {f"mcp__{key}__{tool}" for tool in server.tool_names}
        if isinstance(server, LupMcpServerConfig)
        else name.startswith(f"mcp__{key}__")
        for key, server in servers.items()
    )
