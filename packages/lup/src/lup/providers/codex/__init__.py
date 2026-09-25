"""Codex: the declaration a program writes, and every word it is written in.

A program names Codex parts from here and nowhere deeper: the declaration,
the program it starts, the tool servers it launches. Which module inside the
adapter defines what is the adapter's business, so this module holds each
public part itself rather than pointing at another.

What stays behind in the modules beside this one is the adapter proper. The
runtime side: ``app_server`` is the typed JSON-RPC stdio transport,
``runtime`` opens app-server sessions behind the :mod:`lup.sessions`
contracts, and ``config`` holds profile and compatible-endpoint transforms.
The harness side: ``harness`` renders canonical declarations into the
``.codex`` plugin tree (including the generated policy dispatcher),
``harness_runtime`` probes the CLI, verifies the separately installed plugin
cache, and installs it explicitly, and ``native`` decodes hook payloads into
:mod:`lup.policy` events and renders decisions back to the wire.

Every behavior class in the adapter fills a neutral library contract:
artifact, prompt, invocation, and probe capabilities from
:mod:`lup.harness.contracts`; session, turn, and binding capabilities from
:mod:`lup.sessions.capabilities`; config transforms and profile resolution from
:mod:`lup.providers.config`; and native event decoding and decision rendering
from :mod:`lup.policy.native`. Frozen Pydantic models are the adapter-owned
configuration and evidence data those implementations consume.

Deliberately Codex-only, with no neutral contract:

- :class:`~lup.providers.codex.app_server.CodexAppServer` is the JSON-RPC
  stdio transport to ``codex app-server``. The Claude counterpart is the
  external ``claude_agent_sdk`` package, so no second in-repository
  implementation exists to justify a transport contract.
- :class:`~lup.providers.codex.harness_runtime.CodexPluginInstaller` and the
  plugin cache-evidence helpers install and digest-verify the separately
  cached plugin copy the Codex CLI executes. The Claude launcher runs the
  verified in-repository plugin directory in place, so an installer contract
  would have exactly one possible implementation.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from lup.policy.hooks import LupHooksConfig
from lup.providers.codex.model_choice import (
    CodexModelChoice,
    codex_model_id,
    refuse_unsupported_effort,
)
from lup.providers.codex.models import CodexEffort
from lup.providers.codex.native_tools import CodexNativeTools
from lup.providers.codex.subagents import CodexModelTiers, CodexSubagentTools
from lup.providers.confinement import SessionContainment
from lup.sessions.errors import UnsupportedCapability
from lup.sessions.events import SubmissionGateResolver
from lup.sessions.middleware import CorrectionConfig
from lup.tools.mcp import LupMcpTool, ServerCompanion
from lup.tools.native import NativeTools
from lup.types import EnvVars, JsonObject

CODEX_PROGRAM = Path("codex")
"""The program a Codex session is started as when nothing names another.

Named once because two places read it: the field default below, and the
caller that falls back to it when a request asked for no container to enter.
Spelled twice, the fallback would be a second opinion about what this
runtime is called.
"""


class CodexMcpServerConfig(BaseModel, frozen=True):
    """One project tool group served to Codex over an explicit subprocess."""

    command: str
    args: list[str] = []
    env: EnvVars = {}
    required: bool = True


class Codex(
    BaseModel,
    frozen=True,
    arbitrary_types_allowed=True,
    extra="forbid",
    revalidate_instances="always",
):
    """One Codex agent, declared whole."""

    model: CodexModelChoice | None = None
    """A slug from Codex's catalog, a portable tier, or a custom id."""

    model_tiers: CodexModelTiers = CodexModelTiers()
    """The slug each portable tier selects, for an account or endpoint whose
    lineup differs from the one lup ships as default."""

    system_prompt: str = ""
    """The standing instructions every turn of a session is read under.

    Codex calls these its developer instructions; the shared name is what
    lets a reader move between providers keeping one argument list.
    """

    cwd: Path | None = None
    """Where the session works and what it is sandboxed against.

    ``None`` is where the caller stands when a session opens, read then
    rather than here: read at import, a library loaded before a process
    changed directory would open every session somewhere else.
    """

    policy_root: Path | None = None
    """Application project declaring policy; direct callers default to cwd."""
    executable: Path = CODEX_PROGRAM
    containment: SessionContainment = "none"
    """The boundary owning this executable's home; outer wrappers prepare theirs."""
    named_profile: str | None = None
    model_provider: str | None = None
    provider_config: JsonObject | None = None
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] | None = None
    # The app-server's own wire spellings, passed through by thread_parameters.
    approval_policy: Literal["untrusted", "on-request", "granular", "never"] | None = (
        None
    )
    hooks: LupHooksConfig | None = None
    effort: CodexEffort | None = None
    """What this session asks the model to spend, or None to leave it to the home.

    ``None`` means inherit, which is right only while the *model* is also
    inherited. Where a model is named, :attr:`paired_effort` answers instead —
    see :meth:`model_selection` for why the two cannot travel apart. Which
    rungs a model accepts is its catalog row's answer, and a rung outside it
    is refused where this is declared.
    """

    paired_effort: CodexEffort = "medium"
    """The effort a named model carries when the caller names none.

    A judgement, so it is an overridable default rather than a constant: a
    caller who knows what their model should spend says so and this is never
    read. What it must not be is *absent*, because absence is what let a
    caller's model reach the API beside a stranger's effort.
    """

    environment: EnvVars = {}
    submission_gate_resolver: SubmissionGateResolver | None = None
    correction: CorrectionConfig = CorrectionConfig()
    continuation: CorrectionConfig = CorrectionConfig(
        instruction="Continue according to the Stop hook feedback."
    )
    mcp_servers: dict[str, CodexMcpServerConfig] = {}
    writable_roots: list[Path] = []
    delegated_tools: CodexSubagentTools | None = None
    native_tools: NativeTools = None
    application_tools: dict[str, LupMcpTool] = {}
    companions: list[ServerCompanion] = []

    @model_validator(mode="after")
    def reject_unanswerable_approvals(self) -> Self:
        """Refuse a thread that would ask questions this session cannot answer.

        An approval policy that asks makes the app-server send approval
        requests back here, and only declared hooks answer them. Without
        those the transport refuses every request as unhandled, which stalls
        the turn on its first command — so the combination is rejected at
        construction instead of at the first act.
        """
        if self.containment == "outer" and self.executable == CODEX_PROGRAM:
            raise ValueError(
                "outer containment requires the prepared container executable"
            )
        CodexNativeTools.compile(self.native_tools)
        for key in self.provider_config or {}:
            if key not in {"model_provider", "model_providers"}:
                raise ValueError(
                    f"provider_config {key!r} is outside provider endpoint declarations and explicit session authority; use native_tools or tool_servers"
                )
        for name in self.application_tools:
            if (
                not name.startswith("lup_app_")
                or not name.isascii()
                or not all(char.isalnum() or char in "_-" for char in name)
                or len(name) > 64
            ):
                raise ValueError(f"invalid or reserved application tool name {name!r}")
        if self.delegated_tools is not None and self.native_tools:
            raise ValueError(
                "delegated_tools and native_tools are alternative authority declarations"
            )
        if self.delegated_tools is not None and (
            self.sandbox != "read-only" or self.approval_policy != "never"
        ):
            raise ValueError(
                "delegated tools require read-only sandbox and never approvals"
            )
        if self.delegated_tools is not None and (
            self.mcp_servers or self.writable_roots
        ):
            raise ValueError(
                "delegated tool capabilities do not grant MCP servers or writable roots"
            )
        if self.approval_policy not in {None, "never"} and self.hooks is None:
            raise ValueError(
                f"approval_policy {self.approval_policy!r} makes the app-server "
                "ask this session for decisions; supply hooks to answer them, "
                "or use 'never'"
            )
        return self

    def validated_for_app_server(self) -> Self:
        """Refuse native capabilities before any process starts, without payloads."""
        if self.named_profile is not None:
            raise UnsupportedCapability(
                "Codex app-server cannot select named profiles or apply all startup "
                "settings through thread configuration. Configure the intended "
                "CODEX_HOME/config.toml before opening, or supply explicit supported "
                "session settings. Interactive Codex launches support named profiles."
            )
        return self

    def model_selection(self) -> JsonObject:
        """The model and the effort that goes with it — both, or neither.

        A model and its reasoning effort are one choice, and the home this
        session opens against already holds an answer to both: it is seeded
        from the operator's own configuration, so it carries the model *they*
        chose and the effort they chose for it.

        Naming only the model therefore does not select a model. It selects
        half of somebody else's pair, and the API is the first thing to notice
        — ``'max' is not supported with the 'gpt-5.5' model``, a 400 before the
        turn does anything, naming neither the home nor the caller. Every
        Codex session Lup opened through a named model was one home edit away
        from it.

        So the two travel together. Naming neither inherits a pair that was
        chosen together and is therefore coherent; naming a model sends an
        effort beside it, the caller's where they gave one and
        :attr:`paired_effort` where they did not.
        """
        model = self.model_id()
        if model is None:
            return {} if self.effort is None else {"effort": self.effort}
        return {"model": model, "effort": self.effort or self.paired_effort}

    def model_id(self) -> str | None:
        """The slug the app-server is asked for, or None to inherit the home's."""
        return codex_model_id(self.model, self.model_tiers)

    @model_validator(mode="after")
    def the_model_takes_its_effort(self) -> Self:
        """Refuse an effort the catalog says this session's model cannot take.

        The effort checked is the one :meth:`model_selection` would send — the
        paired one where the caller named none — because a model is never
        sent alone, and a paired rung the model lacks fails the same 400.
        """
        refuse_unsupported_effort(
            self.model, self.effort or self.paired_effort, self.model_tiers
        )
        return self

    def native_capabilities(self) -> CodexNativeTools:
        """Resolve explicit delegated facilities through the same startup bounds."""
        if self.delegated_tools is not None:
            return CodexNativeTools(
                shell=self.delegated_tools.workspace_read,
                images=self.delegated_tools.workspace_read,
                web=self.delegated_tools.web_search,
            )
        return CodexNativeTools.compile(self.native_tools)

    def workspace(self) -> Path:
        """The directory a session works in: the declared one, or where the caller is."""
        return self.cwd if self.cwd is not None else Path.cwd()
