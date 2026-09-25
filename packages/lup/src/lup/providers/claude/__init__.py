"""Claude Code: the declaration a program writes, and every word it is written in.

A program names Claude parts from here and nowhere deeper: the declaration,
the sandbox and permission vocabulary it takes, the submission tool's name.
Which module inside the adapter defines what is the adapter's business, so
this module holds each public part itself rather than pointing at another.

What stays behind in the modules beside this one is the adapter proper. The
runtime side: ``runtime`` opens Claude SDK sessions behind the
:mod:`lup.sessions` contracts, ``config`` holds profile and compatible-endpoint
transforms, and ``profile_store`` is the personal account registry the CLI
composition roots read. The harness side: ``harness`` renders canonical
declarations into the ``.claude`` plugin tree (including the generated policy
dispatcher), ``harness_runtime`` probes the installed CLI for doctor
evidence, ``native`` decodes hook payloads into :mod:`lup.policy` events and
renders decisions back to the wire, and ``hooks`` translates neutral hook
configs into SDK handlers.

Every behavior class in the adapter fills a neutral library contract:
artifact, prompt, invocation, and probe capabilities from
:mod:`lup.harness.contracts`; session, turn, and binding capabilities from
:mod:`lup.sessions.capabilities`; config transforms and profile resolution from
:mod:`lup.providers.config`; and native event decoding and decision rendering
from :mod:`lup.policy.native`. Frozen Pydantic models are the adapter-owned
configuration and evidence data those implementations consume.

Deliberately Claude-only, with no neutral contract:

- :class:`~lup.providers.claude.profile_store.AccountFile` persists
  personal named config-directory selections because the Claude CLI has no
  native profile registry. It projects into ``ClaudeProfileRegistry``, which
  the ``ProfileResolver`` filling consumes. The Codex CLI owns account homes
  and named config overlays natively, so no Codex counterpart exists.
- :mod:`~lup.providers.claude.hooks` translates portable Lup hooks into
  in-process SDK hook callbacks, a mechanism only the Claude SDK exposes;
  Codex hooks exist solely as generated plugin command artifacts.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from lup.policy.enforcement import SandboxPosture
from lup.policy.hooks import LupHooksConfig
from lup.providers.claude.model_choice import (
    ClaudeModelChoice,
    claude_model_id,
    refuse_unsupported_effort,
)
from lup.providers.claude.models import ClaudeEffort
from lup.providers.claude.native_tools import claude_native_tools, claude_tool_allowed
from lup.sessions.events import SubmissionGateResolver
from lup.tools.mcp import McpServerEntry
from lup.tools.native import NativeTools, native_grants
from lup.types import EnvVars, SubagentSpec

SESSION_THINKING_TOKENS = 128_000 - 1

type ClaudeSettingSource = Literal["user", "project", "local"]
"""One filesystem settings source the CLI may load for a session."""


class ClaudeSandboxConfig(BaseModel, frozen=True):
    """Claude SDK sandbox settings consumed by this factory."""

    enabled: bool = True
    auto_allow_bash_if_sandboxed: bool = True
    allow_unsandboxed_commands: bool = False
    excluded_commands: list[str] = Field(
        default=[],
        description=(
            "Command prefixes this session runs outside the boundary. A "
            "spawned session inherits none of the launching shell's settings "
            "files, so a requirement stated there reaches it only by being "
            "passed here too"
        ),
    )

    def posture(self) -> SandboxPosture:
        """These settings as the policy judging this session reads them.

        The same two values reach the CLI and the policy from this one
        object, so a session cannot be permitted more or less than whatever
        judges it believes. Read off a runtime constant instead, the two
        drifted the only way they can: the policy granted an escape the
        settings forbade, and the runtime dropped it without a word.

        The two halves are not equally firm, and only one of them settles
        its own question. ``allow_unsandboxed_commands`` decides the escape
        outright — off, the per-call argument is ignored. ``enabled`` only
        asks for a sandbox: where one cannot start, the CLI warns and runs
        the session unconfined, and this reports a boundary that is not
        there. The CLI settles that with a fail-if-unavailable setting, which
        this configuration cannot reach because the SDK's sandbox settings do
        not carry it; until they do, the placement is settled here and the
        confinement is asserted.
        """
        return SandboxPosture(
            active=self.enabled, escapable=self.allow_unsandboxed_commands
        )


type ClaudePermissionMode = Literal[
    "manual", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"
]
"""Claude Code's own words for how much a session may do without asking.

These are the choices ``claude --permission-mode`` lists. The CLI still reads
``default``, its internal name for ``manual``, which the Agent SDK's own
literal spells, so the adapter hands the SDK that spelling."""


# The fully qualified name of the turn-bound submission tool as Claude Code
# sees it. Compositions that install their own tool-allowlist hooks must
# include it, or the hook denies the very tool the turn requires.
# lup: ignore[constant-declaration] — the qualified name Claude Code composes
SUBMISSION_TOOL = "mcp__lup-output__submit_output"


class Claude(
    BaseModel,
    frozen=True,
    arbitrary_types_allowed=True,
    extra="forbid",
    revalidate_instances="always",
):
    """One Claude Code agent, declared whole."""

    model: ClaudeModelChoice | None = None
    """A name from Claude Code's catalog, a portable tier, or a custom id."""

    system_prompt: str = ""
    coding_harness_preset: bool = True
    native_tools: NativeTools = None
    allowed_tools: list[str] = []
    disallowed_tools: list[str] = []
    tool_servers: dict[str, McpServerEntry] = {}
    permission_mode: ClaudePermissionMode | None = "bypassPermissions"
    max_turns: int | None = None
    delta_streaming: bool = True
    """Whether partial-message deltas are streamed, which gates `live()`."""

    max_thinking_tokens: int | None = SESSION_THINKING_TOKENS
    effort: ClaudeEffort | None = None
    """How hard the session thinks; ``ultra`` is ``xhigh`` with ultracode on."""

    cwd: Path | None = None
    add_dirs: list[Path] = []
    plugin_dirs: list[Path] = []
    """Plugin directories this session loads, the way `--plugin-dir` does.

    Settings inheritance is disabled; only explicitly named directories load.
    Plugins can introduce delegated authority and require the broad ALL grant.
    """
    environment: EnvVars = {}
    sandbox: ClaudeSandboxConfig | None = None
    hooks: LupHooksConfig | None = None
    submission_gate_resolver: SubmissionGateResolver | None = None
    subagents: list[SubagentSpec] = []
    max_buffer_size: int | None = None
    stderr_tail_lines: int = Field(
        default=50,
        description=(
            "How many trailing CLI stderr lines are kept to explain a dead "
            "subprocess. Bounded because stderr is unbounded and only the "
            "end of it says why the process stopped."
        ),
    )
    setting_sources: list[ClaudeSettingSource] | None = None
    cli_path: Path | None = Field(
        default=None,
        description=(
            "The program this session's CLI is started as, where the default "
            "is whichever `claude` the SDK finds on PATH. Named so a session "
            "can be opened through a wrapper that execs the real CLI inside a "
            "container: the SDK spawns whatever is here and passes it the "
            "same arguments, so a worker gets its own boundary without this "
            "adapter learning anything about containers"
        ),
    )
    extra_args: dict[str, str | None] = {}  # lup: ignore[dict-str-payload]

    @model_validator(mode="after")
    def the_model_takes_its_effort(self) -> Self:
        """Refuse an effort the catalog says this session's model cannot take.

        Refused where it is declared, because the alternative is quieter and
        worse: the CLI drops an effort a model lacks, and a session asked to
        think at ``max`` runs at whatever the model does by default.
        """
        refuse_unsupported_effort(self.model, self.effort)
        return self

    def model_id(self) -> str | None:
        """The model name the CLI is started with, or None to leave it the CLI's."""
        return claude_model_id(self.model)

    @model_validator(mode="after")
    def enforce_native_authority(self) -> Self:
        """Keep permissions, settings and delegated roles within the grant."""
        from lup.providers.claude.subagents import subagent_tools

        native_grants(self.native_tools)
        roster = claude_native_tools(self.native_tools)
        if self.setting_sources:
            raise ValueError(
                "session native_tools cannot inherit setting_sources; declare hooks and tool_servers explicitly"
            )
        if self.plugin_dirs and roster is not None:
            raise ValueError(
                "plugin_dirs can introduce delegated authority and require NativeToolGroup.ALL"
            )
        for argument, value in self.extra_args.items():
            if argument not in {
                "no-session-persistence",
                "strict-mcp-config",
                "debug",
                "verbose",
            }:
                raise ValueError(
                    f"extra_args {argument!r} may override native_tools; use a declared session field"
                )
            if argument == "strict-mcp-config" and value is not None:
                raise ValueError("strict-mcp-config cannot be overridden")
        for name in self.allowed_tools:
            if name == SUBMISSION_TOOL:
                continue
            if not claude_tool_allowed(name, roster, self.tool_servers):
                raise ValueError(
                    f"allowed_tools {name!r} is outside native_tools and explicit tool_servers"
                )
        for role in self.subagents:
            for name in subagent_tools(role):
                if not claude_tool_allowed(name, roster, self.tool_servers):
                    raise ValueError(
                        f"subagent {role.name!r} tool {name!r} exceeds session native_tools"
                    )
        return self
