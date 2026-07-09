"""Claude scaffolding pointed at an Anthropic-compatible endpoint."""

from lup.adapters.background.BackgroundDriver import (
    BackgroundAgent,
    BackgroundAgentParams,
)
from lup.adapters.clients.Client import Client
from lup.adapters.engines.claude import ClaudeEngine
from lup.adapters.engines.Engine import Engine
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profile import Profile


class ClaudeCompatEngine(Engine):
    """Claude scaffolding pointed at an Anthropic-compatible endpoint.

    An engine wrapping the ``claude`` engine: backgrounds, profiles, and
    the builtin table delegate to the composed base, and only client
    construction is its own — it reads the endpoint (``base_url``,
    credential routing, model aliases) onto the native env.
    """

    id = "claude-compat"

    def __init__(self, base: ClaudeEngine | None = None) -> None:
        self.base = base if base is not None else ClaudeEngine()

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.claude.compat import create_claude_compat

        return create_claude_compat(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        return self.base.background(params)

    def profiles(self) -> Profile:
        return self.base.profiles()

    def builtin_tools(self) -> frozenset[str]:  # lup: ignore[frozenset-shape]
        return self.base.builtin_tools()
