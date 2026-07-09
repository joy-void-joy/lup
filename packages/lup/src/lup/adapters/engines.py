"""The shipped engines: each backend's capabilities behind one object.

Every method body is a lazy one-liner into the implementation module
that owns the work — the per-engine ``create_*``/``build_*`` doors under
``lup.adapters.clients.*`` and ``lup.adapters.background.*`` — so
importing this module loads no SDK. The compat engines compose their
base engine — an ``Engine`` wrapping an ``Engine``: ``claude-compat``
delegates to the whole Claude scaffolding and ``openai-compat`` to the
whole Codex runtime, each supplying only the client construction that
points it at the compatible endpoint.
:mod:`lup.adapters.wiring` assembles these into the :data:`~lup.adapters.wiring.ENGINES`
and :data:`~lup.adapters.wiring.MODEL_ROUTES` routers.
"""

from lup.adapters.background.Background import (
    BackgroundAgent,
    BackgroundAgentParams,
)
from lup.adapters.clients.Client import Client
from lup.adapters.Engine import Engine
from lup.adapters.errors import UnsupportedOperationError
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.Profiles import ProfileSupport


class ClaudeEngine(Engine):
    """The Claude Agent SDK: full scaffolding on Anthropic models."""

    id = "claude"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.claude.client import create_claude

        return create_claude(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        from lup.adapters.background.claude import build_claude_background

        return build_claude_background(params)

    def profiles(self) -> ProfileSupport:
        from lup.adapters.profiles.claude import ClaudeProfileSupport

        return ClaudeProfileSupport()

    def builtin_tools(self) -> frozenset[str]:
        from lup.adapters.tools.claude import CLAUDE_BUILTIN_TOOLS

        return CLAUDE_BUILTIN_TOOLS


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
        from lup.adapters.clients.claude_compat import create_claude_compat

        return create_claude_compat(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        return self.base.background(params)

    def profiles(self) -> ProfileSupport:
        return self.base.profiles()

    def builtin_tools(self) -> frozenset[str]:  # lup: ignore[frozenset-shape]
        return self.base.builtin_tools()


class CodexEngine(Engine):
    """The OpenAI Codex runtime: a subprocess with served tools."""

    id = "codex"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.codex.client import create_codex

        return create_codex(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        from lup.adapters.background.codex import build_codex_background

        return build_codex_background(params)

    def profiles(self) -> ProfileSupport:
        raise UnsupportedOperationError(
            "profiles are not implemented for the codex runtime yet — its "
            "CLI reads an account home from CODEX_HOME, so a "
            "CodexProfileSupport can slot in without touching the seam."
        )

    def builtin_tools(self) -> frozenset[str]:
        """The names Codex-native builtin activity surfaces as in lup traffic.

        A name table, not a selector: whether the set is restrictable is
        the separate ``tools`` intent knob, which the codex translation
        refuses — the runtime's builtins are always on.
        """
        from lup.adapters.tools.codex import CODEX_BUILTIN_TOOLS

        return CODEX_BUILTIN_TOOLS


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
        from lup.adapters.clients.openai_compat import create_openai_compat

        return create_openai_compat(options)

    def background(self, params: BackgroundAgentParams) -> BackgroundAgent:
        return self.base.background(params)

    def profiles(self) -> ProfileSupport:
        return self.base.profiles()

    def builtin_tools(self) -> frozenset[str]:  # lup: ignore[frozenset-shape]
        return self.base.builtin_tools()
