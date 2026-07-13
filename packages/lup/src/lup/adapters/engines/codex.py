"""The OpenAI Codex runtime engine: a subprocess with served tools."""

from lup.adapters.background.agent import BackgroundAgent
from lup.adapters.background.params import BackgroundAgentParams
from lup.adapters.clients.Client import Client
from lup.adapters.engines.Engine import Engine
from lup.adapters.errors import UnsupportedOperationError
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profile import Profile
from lup.adapters.tools.names import ToolNames


class CodexEngine(Engine):
    """The OpenAI Codex runtime: a subprocess with served tools."""

    id = "codex"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.codex.create import create_codex

        return create_codex(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        from lup.adapters.background.codex import build_codex_background

        return build_codex_background(params)

    def profiles(self) -> Profile:
        raise UnsupportedOperationError(
            "profiles are not implemented for the codex runtime yet — its "
            "CLI reads an account home from CODEX_HOME, so a CodexProfile "
            "can slot in without touching the seam."
        )

    def builtin_tools(self) -> ToolNames:
        """The names Codex-native builtin activity surfaces as in lup traffic.

        A name table, not a selector: whether the set is restrictable is
        the separate ``tools`` intent knob, which the codex translation
        refuses — the runtime's builtins are always on.
        """
        from lup.adapters.tools.codex import CODEX_BUILTIN_TOOLS

        return CODEX_BUILTIN_TOOLS
