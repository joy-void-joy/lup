"""Codex as one selectable runtime.

Codex decides autonomy with a sandbox rather than a permission mode over
tools: this adapter drives the app-server, whose approval channel it does not
implement, so a request is honoured by bounding what a session may reach
instead of by asking. Four fields have no Codex spelling and are refused
rather than dropped — ``tools``, ``allowed_tools`` and ``disallowed_tools``,
which have no app-server equivalent, and ``hooks``, which Codex governs
through the policy dispatcher its harness tree installs rather than per
session. A caller that set one asked for something this runtime cannot do,
and silence there would be a session running with less governance than it
requested.

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

from lup.providers.codex.home import select_codex_home
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.runtime import (
    CodexMcpServerConfig,
    CodexSessionConfig,
    create_codex,
)
from lup.tools.mcp import McpServerEntry, RawStdioServerConfig
from lup.sessions.client import Client
from lup.providers.selection import (
    Runtime,
    SessionAutonomy,
    SessionEffort,
    SessionRequest,
)
from lup.types import EnvVars

type CodexSandbox = Literal["read-only", "workspace-write", "danger-full-access"]
type CodexEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]

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


def codex_config(request: SessionRequest) -> CodexSessionConfig:
    """Render a portable request into Codex's own session configuration.

    Rendering is separate from building so an application can stack a
    :class:`~lup.providers.config.ConfigTransform` — a compatible endpoint, a
    profile — onto what a request asked for, before any session exists.

    ``cwd`` is required rather than defaulted: Codex sandboxes a session
    against its working directory, so inferring one would decide what the
    session may write from wherever the process happened to start.
    """
    refused = [
        name
        for name, asked in (
            ("tools", request.tools is not None),
            ("allowed_tools", bool(request.allowed_tools)),
            ("disallowed_tools", bool(request.disallowed_tools)),
            ("hooks", request.hooks is not None),
        )
        if asked
    ]
    if refused:
        raise ValueError(
            f"Codex has no session-level {', '.join(refused)}; govern this "
            "session through the policy dispatcher in its harness tree"
        )
    if request.cwd is None:
        raise ValueError("Codex sandboxes a session against a cwd; none was given")
    return CodexSessionConfig(
        model=request.model,
        developer_instructions=request.instructions,
        cwd=request.cwd,
        sandbox=(
            None if request.autonomy is None else CODEX_AUTONOMY[request.autonomy]
        ),
        approval_policy="never",
        effort=(None if request.effort is None else CODEX_EFFORT[request.effort]),
        environment=request.environment,
        mcp_servers={
            name: codex_mcp_server(name, server)
            for name, server in request.tool_servers.items()
        },
        writable_roots=[request.cwd],
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
