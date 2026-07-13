"""The background-agent request: what a builder receives before engine dispatch."""

from collections.abc import Callable

from pydantic import BaseModel

from lup.mcp import LupMcpTool


class BackgroundAgentParams(BaseModel):
    """The request a background-agent builder receives, before engine dispatch."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    system_prompt: str
    build_message: Callable[[], str | None]
    start_message: str = ""
    model: str | None = None
    debounce_seconds: float = 3.0
    tools: list[LupMcpTool] | None = None
    builtin_tools: list[str] | None = None
    allowed_tools: list[str] | None = None
    on_response: Callable[[object], None] | None = None
