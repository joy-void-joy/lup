"""The Claude Agent SDK engine: full scaffolding on Anthropic models."""

from lup.adapters.background.agent import BackgroundAgent
from lup.adapters.background.params import BackgroundAgentParams
from lup.adapters.clients.Client import Client
from lup.adapters.engines.Engine import Engine
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profile import Profile


class ClaudeEngine(Engine):
    """The Claude Agent SDK: full scaffolding on Anthropic models."""

    id = "claude"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.claude.create import create_claude

        return create_claude(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        from lup.adapters.background.claude import build_claude_background

        return build_claude_background(params)

    def profiles(self) -> Profile:
        from lup.adapters.profiles.claude.profile import ClaudeProfile

        return ClaudeProfile()

    def builtin_tools(self) -> frozenset[str]:
        from lup.adapters.tools.claude import CLAUDE_BUILTIN_TOOLS

        return CLAUDE_BUILTIN_TOOLS
