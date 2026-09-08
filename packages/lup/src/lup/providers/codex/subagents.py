"""Codex compilation of portable delegated roles."""

from typing import assert_never

from pydantic import BaseModel

from lup.types import JsonObject, ModelTier, SubagentSpec


class CodexModelTiers(BaseModel, frozen=True):
    """Provider model defaults, replaceable for an account or compatible endpoint."""

    strongest: str = "gpt-6-astra"
    balanced: str = "gpt-5.6-terra"
    fast: str = "gpt-5.6-luna"

    def resolve(self, tier: ModelTier, *, inherited: str | None = None) -> str | None:
        match tier:
            case "inherit":
                return inherited
            case "strongest":
                return self.strongest
            case "balanced":
                return self.balanced
            case "fast":
                return self.fast
            case _:
                # lup: ignore[own-model-dispatch] — provider compilation of literals, not project model variants
                assert_never(tier)


class CodexSubagentTools(BaseModel, frozen=True):
    """Read-only runtime facilities, never an approximation of an exact grant.

    Workspace reads use sandboxed shell commands and image viewing. Web
    research uses the hosted search tool, not network access for that shell.
    Ambient MCP servers are disabled separately after config/read resolves
    the project configuration.
    """

    workspace_read: bool = False
    web_search: bool = False

    def configuration(self) -> JsonObject:
        return {
            "features": {
                "shell_tool": self.workspace_read,
                "unified_exec": self.workspace_read,
                "view_image": self.workspace_read,
                "apps": False,
                "plugins": False,
                "multi_agent": False,
                "browser_use": False,
                "computer_use": False,
                "image_generation": False,
                "skill_mcp_dependency_install": False,
            },
            "web_search": "live" if self.web_search else "disabled",
        }


def subagent_tools(spec: SubagentSpec) -> CodexSubagentTools:
    """Reject exact grants that app-server cannot enforce without widening."""
    if spec.tools:
        raise ValueError(
            "Codex app-server cannot enforce exact delegated tool grants: "
            + ", ".join(spec.tools)
            + ". Declare workspace-read or web-search capabilities when those "
            "runtime facilities are intended."
        )
    workspace_read = False
    web_search = False
    for capability in spec.capabilities:
        match capability:
            case "workspace-read":
                workspace_read = True
            case "web-search":
                web_search = True
            case _:
                # lup: ignore[own-model-dispatch] — provider compilation of literals, not project model variants
                assert_never(capability)
    return CodexSubagentTools(workspace_read=workspace_read, web_search=web_search)
