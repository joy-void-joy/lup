"""The Codex runtime pointed at any OpenAI-compatible endpoint."""

from lup.adapters.background.agent import BackgroundAgent
from lup.adapters.background.params import BackgroundAgentParams
from lup.adapters.clients.Client import Client
from lup.adapters.engines.codex import CodexEngine
from lup.adapters.engines.Engine import Engine
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profile import Profile


class OpenAICompatEngine(Engine):
    """The Codex runtime pointed at any OpenAI-compatible endpoint.

    An engine wrapping the ``codex`` engine: backgrounds, the builtin
    table, and the profile refusal delegate to the composed base, and
    only client construction is its own — it defines a custom model
    provider from the endpoint.
    """

    id = "openai-compat"

    def __init__(self, base: CodexEngine | None = None) -> None:
        self.base = base if base is not None else CodexEngine()

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.codex.compat import create_openai_compat

        return create_openai_compat(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        return self.base.background(params)

    def profiles(self) -> Profile:
        return self.base.profiles()

    def builtin_tools(self) -> frozenset[str]:  # lup: ignore[frozenset-shape]
        return self.base.builtin_tools()
