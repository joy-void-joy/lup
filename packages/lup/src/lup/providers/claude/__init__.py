"""Claude Code: the declaration a program writes, and every part it is written with.

A program names Claude parts from here and nowhere deeper: the agent it
declares, the session and turn that agent opens, the sandbox, permission and
endpoint vocabulary it takes, the submission tool's name. Which module inside
the adapter defines what is the adapter's business, so this module holds each
public part itself rather than pointing at another.

What stays behind in the modules beside this one is the adapter proper. The
runtime side: ``runtime`` opens Claude SDK sessions behind the
:mod:`lup.sessions` contracts, ``transcripts`` reads the record Claude Code
keeps of each conversation, and ``config`` holds profile and
compatible-endpoint transforms. The harness side: ``harness`` renders canonical
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

Nothing here imports the Claude Agent SDK: an agent is a declaration, and the
SDK loads when a session opens.

Deliberately Claude-only, with no neutral contract:
:mod:`~lup.providers.claude.hooks` translates portable Lup hooks into
in-process SDK hook callbacks, a mechanism only the Claude SDK exposes; Codex
hooks exist solely as generated plugin command artifacts.
"""

from collections.abc import AsyncIterator, Generator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Literal, Self, overload

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, model_validator

from lup.policy.enforcement import SandboxPosture
from lup.policy.hooks import LupHooksConfig
from lup.providers.claude.model_choice import (
    ClaudeModelChoice,
    claude_default_effort,
    claude_model_id,
    refuse_unsupported_effort,
)
from lup.providers.claude.models import ClaudeEffort
from lup.providers.claude.native_tools import claude_native_tools, claude_tool_allowed
from lup.sessions.capabilities import ConversationRecord, ForkSession, SessionEngine
from lup.sessions.events import (
    AnyTurnBlock,
    LiveTurnEvent,
    SessionId,
    SessionSummary,
    SubmissionGateResolver,
    TurnEvent,
    TurnId,
    TurnInput,
    TurnMessage,
    TurnRequest,
    TurnResult,
)
from lup.sessions.layers import SessionLayers
from lup.sessions.turns import LazyTurn, turn_input
from lup.tools.mcp import LupMcpTool, McpServerEntry, create_mcp_server
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


class ClaudeCompatibleEndpoint(BaseModel, frozen=True):
    """All configuration owned by an Anthropic-compatible endpoint."""

    base_url: AnyHttpUrl
    api_key: SecretStr | None = None
    """The credential sent, or ``None`` for a placeholder a local endpoint expects."""

    auth_style: Literal["auth_token", "api_key"] = "auth_token"
    map_model_aliases: bool = True


# The fully qualified name of the turn-bound submission tool as Claude Code
# sees it. Compositions that install their own tool-allowlist hooks must
# include it, or the hook denies the very tool the turn requires.
# lup: ignore[constant-declaration] — the qualified name Claude Code composes
SUBMISSION_TOOL = "mcp__lup-output__submit_output"

# lup: ignore[constant-declaration] — the server name the adapter hosts a
# declaration's own tools under, which its allowlist spells as well
TOOLS_SERVER = "lup-tools"


class ClaudeTurn[T: BaseModel | None]:
    """One turn of a Claude session: await it for the result, iterate its blocks.

    Nothing starts until something asks — an await, an iteration,
    :meth:`events`, :meth:`live` or :meth:`interrupt` — and then it starts
    once, however many ask. Awaiting it again, after iterating or after
    awaiting, returns the same result. Claude takes no input into a running
    turn, so a Claude turn has no ``steer``: ask again when this one ends.
    """

    def __init__(self, turn: LazyTurn[T]) -> None:
        self.turn = turn

    def __await__(self) -> Generator[object, None, TurnResult[T]]:
        return self.turn.result().__await__()

    def __aiter__(self) -> AsyncIterator[AnyTurnBlock]:
        return self.turn.blocks()

    def events(self) -> AsyncIterator[TurnEvent]:
        """Every durable event of this turn, from its first, as they happen."""
        return self.turn.events()

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        """The durable events and the deltas between them, as they happen."""
        return self.turn.live()

    async def interrupt(self) -> None:
        """Stop this turn, returning once it has stopped."""
        await self.turn.interrupt()


class ClaudeSession:
    """One open conversation with Claude Code, and every turn asked of it."""

    def __init__(
        self,
        engine: SessionEngine,
        record: ConversationRecord,
        forks: ForkSession["ClaudeSession"],
        *,
        deltas: bool,
    ) -> None:
        self.engine = engine
        self.record = record
        self.forks = forks
        self.deltas = deltas

    @property
    def id(self) -> SessionId:
        """Claude Code's own identity for this conversation, which resumes it."""
        return self.record.identity()

    @overload
    def ask(self, prompt: str | TurnInput) -> ClaudeTurn[None]: ...

    @overload
    def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T]
    ) -> ClaudeTurn[T]: ...

    def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T] | None = None
    ) -> ClaudeTurn[T] | ClaudeTurn[None]:
        """A turn putting ``prompt`` to this conversation, started when first used.

        With ``output`` the turn ends in a submission validated as that model,
        which its result carries as ``output``; without, ``output`` is ``None``.
        """
        if output is None:
            request = TurnRequest[None](input=turn_input(prompt))
            return ClaudeTurn(LazyTurn(self.engine, request, deltas=self.deltas))
        typed = TurnRequest[T](input=turn_input(prompt), output_type=output)
        return ClaudeTurn(LazyTurn(self.engine, typed, deltas=self.deltas))

    async def history(self) -> list[TurnMessage]:
        """Every message of this conversation, from the transcript Claude Code keeps."""
        return await self.record.messages()

    def fork(
        self, at: TurnId | None = None
    ) -> AbstractAsyncContextManager["ClaudeSession"]:
        """Open a new conversation carrying this one's history, up to turn ``at``.

        ``at`` names a turn this session took, by the identifier its result
        carries; unset, the fork carries everything so far. The fork is
        independent from the moment it opens: nothing asked of it reaches this
        conversation, nor the other way round.
        """
        return self.forks.fork(at)


class Claude(
    BaseModel,
    frozen=True,
    arbitrary_types_allowed=True,
    extra="forbid",
    revalidate_instances="always",
):
    """One Claude Code agent, declared whole: what opens its sessions."""

    model: ClaudeModelChoice | None = None
    """A name from Claude Code's catalog, a portable tier, or a custom id."""

    system_prompt: str = ""
    coding_harness_preset: bool = True
    native_tools: NativeTools = None
    tools: list[LupMcpTool] = []
    """Application tools, served to every session on an in-process server."""

    allowed_tools: list[str] = []
    disallowed_tools: list[str] = []
    tool_servers: dict[str, McpServerEntry] = {}
    permission_mode: ClaudePermissionMode | None = "bypassPermissions"
    max_turns: int | None = None
    delta_streaming: bool = True
    """Whether partial-message deltas are streamed, which gates `live()`."""

    max_thinking_tokens: int | None = SESSION_THINKING_TOKENS
    effort: ClaudeEffort | None = None
    """How hard the session thinks; ``ultra`` is ``xhigh`` with ultracode on.

    Unset, the model's own default, which :meth:`resolved_effort` answers. Only
    the default adapts: a rung named here that the model lacks is refused.
    """

    cwd: Path | None = None
    add_dirs: list[Path] = []
    plugin_dirs: list[Path] = []
    """Plugin directories this session loads, the way `--plugin-dir` does.

    Settings inheritance is disabled; only explicitly named directories load.
    Plugins can introduce delegated authority and require the broad ALL grant.
    """
    environment: EnvVars = {}
    profile: str | None = None
    """The account every session opens as: a name among the person's lup
    profiles, resolved to that account's Claude home the way ``harness claude
    --profile`` resolves it, and taking precedence over a home ``environment``
    names. Unset, sessions stay on the account this process already runs
    under. An unknown name is refused when a session opens, listing the known
    ones."""

    endpoint: ClaudeCompatibleEndpoint | None = None
    """An Anthropic-compatible endpoint the sessions talk to instead of Anthropic's."""

    sandbox: ClaudeSandboxConfig | None = None
    hooks: LupHooksConfig | None = None
    submission_gate_resolver: SubmissionGateResolver | None = None
    subagents: list[SubagentSpec] = []
    layers: SessionLayers = SessionLayers()
    """What every session opened here is wrapped in, turn by turn and whole."""

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
            "The program this session's CLI is started as. Unset, it is the "
            "`claude` on PATH — the one an interactive launch runs — and the "
            "SDK's bundled CLI only where none is installed, so one declaration "
            "never runs on two CLI versions. Named so a session can be opened "
            "through a wrapper that execs the real CLI inside a container: the "
            "SDK spawns whatever is here and passes it the same arguments, so a "
            "worker gets its own boundary without this adapter learning "
            "anything about containers"
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

    def resolved_effort(self) -> ClaudeEffort | None:
        """The effort the CLI is started with: the one named, or the model's default.

        The default is :func:`~lup.providers.claude.model_choice.claude_default_effort`'s:
        ``xhigh`` where the model's catalog row takes it, the row's highest rung
        below that otherwise, and none for a model taking no effort.
        """
        if self.effort is not None:
            return self.effort
        return claude_default_effort(self.model)

    def servers(self) -> dict[str, McpServerEntry]:
        """Every tool server a session opens with: the declared ones, and ``tools``."""
        if not self.tools:
            return dict(self.tool_servers)
        hosted = create_mcp_server(TOOLS_SERVER, tools=self.tools)
        return {**self.tool_servers, TOOLS_SERVER: hosted}

    @model_validator(mode="after")
    def enforce_native_authority(self) -> Self:
        """Keep permissions, settings and delegated roles within the grant."""
        from lup.providers.claude.subagents import subagent_tools

        native_grants(self.native_tools)
        roster = claude_native_tools(self.native_tools)
        servers = self.servers()
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
            if not claude_tool_allowed(name, roster, servers):
                raise ValueError(
                    f"allowed_tools {name!r} is outside native_tools and explicit tool_servers"
                )
        for role in self.subagents:
            for name in subagent_tools(role):
                if not claude_tool_allowed(name, roster, servers):
                    raise ValueError(
                        f"subagent {role.name!r} tool {name!r} exceeds session native_tools"
                    )
        return self

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[ClaudeSession]:
        """Open a conversation, or resume the one ``resume`` names.

        The SDK loads here, not when the agent is declared; the CLI connects
        when the first turn starts, once that turn's submission tool is bound.
        """
        from lup.providers.claude.runtime import ClaudeSessionOpener

        return ClaudeSessionOpener(self).open_session(resume)

    @overload
    async def ask(self, prompt: str | TurnInput) -> TurnResult[None]: ...

    @overload
    async def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T]
    ) -> TurnResult[T]: ...

    async def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T] | None = None
    ) -> TurnResult[T] | TurnResult[None]:
        """Open a conversation, take one turn, and close it however the turn ends."""
        async with self.open() as session:
            if output is None:
                return await session.ask(prompt)
            return await session.ask(prompt, output)

    async def sessions(self) -> list[SessionSummary]:
        """The conversations Claude Code has on record for this agent's workspace.

        Read from the transcripts Claude Code keeps under this agent's own
        configuration home — its profile's, where it names one — newest
        first, whether this library opened them or a terminal did.
        """
        from lup.execution.threads import run_sync
        from lup.providers.claude.config_home import session_config_home
        from lup.providers.claude.login import CLAUDE_LOGIN
        from lup.providers.claude.transcripts import ClaudeTranscripts
        from lup.providers.profile_tree import profile_environment

        account = profile_environment(CLAUDE_LOGIN, self.profile)
        home = session_config_home({**self.environment, **account})
        transcripts = ClaudeTranscripts(home)
        workspace = self.cwd if self.cwd is not None else Path.cwd()
        return await run_sync(lambda: transcripts.sessions(workspace))

    def layered(self, layers: SessionLayers) -> Self:
        """This agent with ``layers`` laid over its own, the fields set there winning."""
        return self.model_copy(update={"layers": layers.over(self.layers)})
