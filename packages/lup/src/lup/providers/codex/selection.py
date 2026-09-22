"""Codex as one selectable runtime.

Codex decides autonomy with a sandbox, and native authority is compiled
independently of it: ``native_tools`` names the built-in facilities a session
may reach, and an unsupported exact grant fails before launch rather than
being approximated. Declared application tools keep their Python handlers
through the thread's dynamic tools, while explicitly external servers keep
their subprocess transport. Session-level ``allowed_tools`` and
``disallowed_tools`` have no app-server equivalent and are refused rather
than dropped.

Typed output rides ``outputSchema`` on each ``turn/start``, so a schema may
change or disappear between turns without disturbing the thread. The
dynamic-tool channel is thread-scoped and therefore carries application tools
alone; changing those still requires a fresh session.

Portable PostToolUse and Stop hooks run on native lifecycle events. Tagged
inbox observers also deliver on native activity without changing approvals.
Other PreToolUse hooks must explicitly name one of the native approval
methods, or the exact joined methods in
:data:`lup.providers.codex.hooks.APPROVAL_METHODS`; only those
registrations enable approval requests. The app-server does not ask before
every tool call, so broader pre-execution hooks are refused. The generated
policy dispatcher enforces policy at the native PreToolUse boundary.

``disallowed_tools`` is refused despite the dispatcher being able to deny a
tool it can match, because that dispatcher is installed once per harness tree
and this field is asked per session: honouring it there would give every
session in the project a refusal one of them asked for. A block list is also
the field where silence costs most — a roster that came out too wide fails
visibly, where a refusal that was dropped leaves the tool callable and
nothing saying so.

``effort`` is narrowed rather than refused: Codex's ladder ends at ``xhigh``,
so a request for ``max`` opens at that ceiling. Asking to think as hard as
possible is answered by the hardest this runtime thinks, which is what was
wanted; asking for governance it has no way to apply is not.
"""

from pathlib import Path
from typing import Literal

from lup.providers.codex.hooks import codex_hook_approval_policy
from lup.providers.codex.home import select_codex_home
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.native_tools import CodexNativeTools
from lup.providers.codex.runtime import (
    CODEX_PROGRAM,
    CodexEffort,
    CodexMcpServerConfig,
    CodexSessionConfig,
    create_codex,
)
from lup.tools.mcp import LupMcpServerConfig, McpServerEntry, RawStdioServerConfig
from lup.sessions.client import Client
from lup.sessions.errors import UnsupportedCapability
from lup.providers.selection import (
    Runtime,
    SessionAutonomy,
    SessionContainment,
    SessionEffort,
    SessionRequest,
)
from lup.types import EnvVars
from lup.workspace.paths import project_root

type CodexSandbox = Literal["read-only", "workspace-write", "danger-full-access"]


# lup: ignore[constant-declaration] — each value is Codex's own sandbox name for
# the autonomy beside it, over a vocabulary this library closes
CODEX_AUTONOMY: dict[SessionAutonomy, CodexSandbox] = {
    "ask": "read-only",
    "plan": "read-only",
    "accept_edits": "workspace-write",
    "unattended": "danger-full-access",
}
"""What a session may reach, standing in for an approval it cannot raise."""

# lup: ignore[constant-declaration] — each value is Codex's own effort for the
# degree beside it, over a vocabulary this library closes
CODEX_EFFORT: dict[SessionEffort, CodexEffort] = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}
"""What Codex calls each degree of effort a caller can ask for.

``max`` meets ``xhigh`` because Codex's ladder has no rung above it."""


def codex_mcp_server(name: str, server: McpServerEntry) -> CodexMcpServerConfig:
    """Narrow one declared tool group into the subprocess Codex launches.

    The in-process case is refused rather than relaunched as a subprocess,
    which is the repair its message is written to head off. A hosted server
    closes over the state of the process that hosts it — the context
    variables scoping the session it answers inside, its open clients, its
    caches — and a subprocess inherits none of it while answering every call
    as though it had. The failure that follows is not an error: it is a tool
    returning a confident answer computed against defaults, which is the one
    kind of wrong nothing downstream can detect.

    Serving it is therefore an application's decision about what that group's
    tools read, and the application has to state it by declaring a transport
    that carries whatever they need.
    """
    match server:
        case {"command": str(command)}:
            stdio: RawStdioServerConfig = server
            return CodexMcpServerConfig(
                command=command,
                args=list(stdio["args"]) if "args" in stdio else [],
                env=dict(stdio["env"]) if "env" in stdio else {},
            )
        case _:
            raise ValueError(
                f"Codex serves tool group {name!r} over a subprocess; this one is "
                "declared as an in-process or networked server. It is not relaunched "
                "as one: a hosted server reads the hosting process's own state, and "
                "a subprocess would answer from defaults rather than fail. Declare a "
                "transport that carries what its tools read."
            )


# lup: ignore[constant-declaration] — each value is Codex's own sandbox name for
# the wall beside it, over a vocabulary this library closes
CODEX_CONTAINMENT: dict[SessionContainment, CodexSandbox | None] = {
    "outer": "danger-full-access",
    "inner": "workspace-write",
    "none": None,
}
"""What Codex's one sandbox field is asked for behind each wall.

``outer`` is the word
:data:`~lup.providers.codex.confinement.CODEX_CONFINEMENT` already sends a
launched CLI, for the same reason: Codex confines with the kernel's own
facilities, which an unprivileged container does not hand a nested caller,
so inside one the honest posture is the container alone.

``none`` names no mode at all. The wall was not asked for, so the field is
left to whatever the autonomy implies — which is what every request meant
before this axis existed.
"""

# lup: ignore[constant-declaration] — Codex's own sandbox names, narrowest first
CODEX_SANDBOX_WIDTH: list[CodexSandbox] = [
    "read-only",
    "workspace-write",
    "danger-full-access",
]
"""Codex's sandbox modes, ordered by how much they let a session reach."""


def codex_sandbox(request: SessionRequest) -> CodexSandbox | None:
    """The one field Codex says both how much and how far with.

    Claude holds a permission mode and a sandbox and decides them apart.
    Codex has neither word: it states what a session may do by stating what
    it may reach, so a request naming an autonomy and a wall has named one
    field twice.

    The narrower of the two wins. That is not a precedence rule to remember
    but the refusal of one: neither axis may widen what the other narrowed,
    so an unattended session behind the inner wall reaches
    ``workspace-write``, and a planning one stays ``read-only``.

    ``outer`` takes the field outright instead. The container is the wall by
    then, and narrowing this field would arm a second boundary inside it —
    the one that cannot start there, which is what standing it down was for.
    """
    if request.containment == "outer":
        return CODEX_CONTAINMENT["outer"]
    asked: list[CodexSandbox] = [
        mode
        for mode in (
            CODEX_CONTAINMENT[request.containment],
            None if request.autonomy is None else CODEX_AUTONOMY[request.autonomy],
        )
        if mode is not None
    ]
    return min(asked, key=CODEX_SANDBOX_WIDTH.index, default=None)


def codex_config(request: SessionRequest) -> CodexSessionConfig:
    """Render a portable request into Codex's own session configuration.

    Rendering is separate from building so an application can stack a
    :class:`~lup.providers.config.ConfigTransform` — a compatible endpoint, a
    profile — onto what a request asked for, before any session exists.

    ``cwd`` is required rather than defaulted: Codex sandboxes a session
    against its working directory, so inferring one would decide what the
    session may write from wherever the process happened to start.

    ``containment`` and ``autonomy`` both land on the sandbox, which is the
    only field Codex has for either; :func:`codex_sandbox` states how the
    two are reconciled. An ``outer`` request is also started as the program
    that enters its container, the same seam Claude spells ``cli_path``.
    """
    refused = [
        name
        for name, asked in (
            ("allowed_tools", bool(request.allowed_tools)),
            ("disallowed_tools", bool(request.disallowed_tools)),
        )
        if asked
    ]
    if refused:
        raise UnsupportedCapability(
            f"Codex has no session-level {', '.join(refused)}; govern this "
            "session through the policy dispatcher in its harness tree"
        )
    limits = [
        name
        for name, value in (
            ("max_turns", request.max_turns),
            ("max_thinking_tokens", request.max_thinking_tokens),
        )
        if value is not None
    ]
    if limits:
        raise UnsupportedCapability(
            f"Codex cannot enforce {', '.join(limits)}; omit these limits and use "
            "effort for reasoning, or client timeout/budget middleware for a whole turn"
        )
    if request.cwd is None:
        raise ValueError("Codex sandboxes a session against a cwd; none was given")
    application_tools = [
        (f"lup_app_{name}__{tool.name}", tool)
        for name, server in request.tool_servers.items()
        if isinstance(server, LupMcpServerConfig)
        for tool in server.tools
    ]
    if len({name for name, _tool in application_tools}) != len(application_tools):
        raise ValueError(
            "hosted server/tool names collide in Codex; rename the ambiguous server or tool"
        )
    return CodexSessionConfig(
        model=request.model,
        developer_instructions=request.instructions,
        cwd=request.cwd,
        policy_root=project_root(),
        sandbox=codex_sandbox(request),
        executable=request.contained_program or CODEX_PROGRAM,
        containment=request.containment,
        approval_policy=codex_hook_approval_policy(request.hooks),
        hooks=request.hooks,
        effort=(None if request.effort is None else CODEX_EFFORT[request.effort]),
        environment=request.environment,
        native_tools=request.native_tools,
        mcp_servers={
            name: codex_mcp_server(name, server)
            for name, server in request.tool_servers.items()
            if not isinstance(server, LupMcpServerConfig)
        },
        application_tools=dict(application_tools),
        companions=[
            companion
            for server in request.tool_servers.values()
            if isinstance(server, LupMcpServerConfig)
            for companion in server.companions
        ],
        writable_roots=[request.cwd]
        if CodexNativeTools.compile(request.native_tools).write
        or CodexNativeTools.compile(request.native_tools).shell
        else [],
        submission_gate_resolver=request.submission_gate,
    )


def codex_session(request: SessionRequest) -> Client:
    """Render a portable request into a configured Codex session factory."""
    return create_codex(codex_config(request))


def codex_workspace_home(environment: EnvVars, workspace: Path) -> EnvVars:
    """Give one workspace's Codex sessions a home of their own.

    A home the environment already names is honoured as it stands: Codex
    seeds a scoped home by copying credentials into it, so deriving a second
    one underneath a home somebody selected deliberately would run the
    session against a copy of an account rather than the account.

    Naming a home is all this does. The project's own plugin is installed
    into it when a session opens, because installing is a package manager
    away and naming is asked for wherever a request is merely described —
    including where a request states something Codex refuses, which has to
    reach its refusal rather than dying on an install first.
    """
    return CODEX_LOGIN.environment(select_codex_home(None, environment, workspace).path)


CODEX_RUNTIME = Runtime(
    name="Codex",
    login=CODEX_LOGIN,
    open=codex_session,
    workspace_home=codex_workspace_home,
)
"""Codex, as the single value an application assigns to select it."""
