"""Compile portable delegated roles into Claude's model and tool vocabulary."""

from collections.abc import Iterator
from typing import Literal, assert_never

from lup.types import ModelTier, SubagentSpec


def model_alias(tier: ModelTier) -> Literal["inherit", "opus", "sonnet", "haiku"]:
    """Claude's native aliases, shared by SDK roles and generated agents."""
    match tier:
        case "inherit":
            return "inherit"
        case "strongest":
            return "opus"
        case "balanced":
            return "sonnet"
        case "fast":
            return "haiku"
        case _:
            # lup: ignore[own-model-dispatch] — provider compilation of literals, not project model variants
            assert_never(tier)


def subagent_tools(spec: SubagentSpec) -> list[str]:
    """Expose only the role's exact tools and declared runtime facilities.

    A scoped permission rule is not a tool name. Native agent definitions
    have no separate permission-rule field, so refusing it prevents a scoped
    grant from becoming permission to use the whole tool.
    """

    def native_tools() -> Iterator[str]:
        for capability in spec.capabilities:
            match capability:
                case "workspace-read":
                    yield from ["Read", "Glob", "Grep"]
                case "web-search":
                    yield from ["WebSearch", "WebFetch"]
                case _:
                    # lup: ignore[own-model-dispatch] — provider compilation of literals, not project model variants
                    assert_never(capability)
        for grant in spec.tools:
            if "(" in grant:
                raise ValueError(
                    f"Claude delegated roles cannot enforce scoped tool grant {grant!r}; "
                    "declare its permission policy in the owning session"
                )
            yield grant

    return list(dict.fromkeys(native_tools()))
