"""The shipped engines: each backend's capabilities behind one object.

Every method body is a lazy one-liner into the implementation module
that owns the work — the per-engine ``create_*``/``build_*`` doors under
``lup.adapters.clients.*`` and ``lup.adapters.background.*`` — so
importing this module loads no SDK. The compat engines subclass their
base engine: ``claude-compat`` keeps the whole Claude scaffolding and
``openai-compat`` the whole Codex runtime, each overriding only the
client construction that points it at the compatible endpoint.
:mod:`lup.adapters.wiring` assembles these into the :data:`~lup.adapters.wiring.ENGINES`
and :data:`~lup.adapters.wiring.MODEL_ROUTES` routers.
"""

from lup.adapters.background.Background import (
    BackgroundAgentParams,
    BaseBackgroundAgent,
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

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        from lup.adapters.background.claude import build_claude_background

        return build_claude_background(params)

    def profiles(self) -> ProfileSupport:
        from lup.adapters.profiles.claude import ClaudeProfileSupport

        return ClaudeProfileSupport()

    def builtin_tools(self) -> frozenset[str]:
        from lup.adapters.tools.claude import CLAUDE_BUILTIN_TOOLS

        return CLAUDE_BUILTIN_TOOLS


class ClaudeCompatEngine(ClaudeEngine):
    """Claude scaffolding pointed at an Anthropic-compatible endpoint.

    The same engine as ``claude`` — backgrounds, profiles, and the
    builtin table are inherited — with client construction that reads
    the endpoint (``base_url``, credential routing, model aliases) onto
    the native env.
    """

    id = "claude-compat"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.claude_compat import create_claude_compat

        return create_claude_compat(options)


class CodexEngine(Engine):
    """The OpenAI Codex runtime: a subprocess with served tools."""

    id = "codex"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.codex.client import create_codex

        return create_codex(options)

    def background(self, params: BackgroundAgentParams) -> BaseBackgroundAgent:
        from lup.adapters.background.codex import build_codex_background

        return build_codex_background(params)

    def profiles(self) -> ProfileSupport:
        raise UnsupportedOperationError(
            "profiles are not implemented for the codex runtime yet — its "
            "CLI reads an account home from CODEX_HOME, so a "
            "CodexProfileSupport can slot in without touching the seam."
        )

    def builtin_tools(self) -> frozenset[str]:
        raise UnsupportedOperationError(
            "the codex runtime publishes no builtin tool-name table; its "
            "builtins (command execution, file changes) are not "
            "individually selectable."
        )


class OpenAICompatEngine(CodexEngine):
    """The Codex runtime pointed at any OpenAI-compatible endpoint.

    The same engine as ``codex`` — backgrounds and refusals are
    inherited — with client construction that defines a custom model
    provider from the endpoint.
    """

    id = "openai-compat"

    def client(self, options: LupAgentOptions) -> Client:
        from lup.adapters.clients.openai_compat import create_openai_compat

        return create_openai_compat(options)
