"""Selecting which runtime answers a session, as one value.

An application that names a runtime in more than one place can be changed in
only one of them: the sessions it opens would come from Codex while the login
its profile system administers still belonged to Claude. A :class:`Runtime`
is the whole selection — what a session opens through, and where that runtime
keeps a login — so an application holds one and names a provider nowhere.

:class:`SessionRequest` is a declaration, not a configuration. It says what a
caller wants of a session in words every runtime shares; each runtime renders
it into its own shape and states, in its own docstring, what it has no words
for. A field added here is a request every runtime then has to answer.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from lup.hooks import LupHooksConfig
from lup.mcp import McpServerEntry
from lup.runtime.factory import SessionFactory
from lup.runtime.login import ProviderLogin
from lup.types import EnvVars

type SessionAutonomy = Literal["ask", "accept_edits", "plan", "unattended"]
"""How much a session may do before it stops to ask.

Named for what a caller wants rather than for either runtime's own control:
one spells this as a permission mode over tools, the other as a sandbox its
approvals are decided against, and a caller wanting an unattended session
should not have to know which.
"""

type SessionEffort = Literal["minimal", "low", "medium", "high", "xhigh", "max"]
"""How hard a session is asked to think before it answers.

The four middle rungs are the words both runtimes already share; the two ends
are each runtime's own limit, and the runtime without one renders it as the
nearest it has. Codex's ``none`` is deliberately absent: Claude has no rung
below ``low``, so admitting it here would turn "do not reason" into "reason a
little" on one runtime without saying so.
"""


class SessionRequest(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """What an application asks of a session, before a runtime renders it."""

    model: str | None = None
    instructions: str = ""
    """The standing instructions a session opens with, however it spells them."""

    cwd: Path | None = None
    autonomy: SessionAutonomy | None = None
    effort: SessionEffort | None = None
    tools: list[str] | None = None
    allowed_tools: list[str] = []
    disallowed_tools: list[str] = []
    """The tools this session may not call, whoever else would admit them.

    The third of three fields that read alike. ``tools`` is the roster a
    session is given, ``allowed_tools`` the part of it that runs without
    being asked about, and this one a refusal that outranks both — which is
    what lets a caller say "everything except this" without enumerating
    everything. A roster states a session's whole reach and has to be
    restated whenever that reach grows; a refusal keeps naming the same tool.
    """

    tool_servers: dict[str, McpServerEntry] = {}
    max_turns: int | None = None
    max_thinking_tokens: int | None = None
    environment: EnvVars = {}
    hooks: LupHooksConfig | None = None


type SessionOpener = Callable[[SessionRequest], SessionFactory]
"""Render one request into the configured session factory of one runtime."""

type WorkspaceHome = Callable[[EnvVars, Path], EnvVars]
"""Give one workspace's sessions a configuration home of their own.

Reads the environment a caller already selected — a profile naming which
account to run as — and answers the variables routing this runtime's CLI at a
home private to that workspace, so concurrent sessions cannot read each
other's half-written startup document.

Which variable carries it is the runtime's own, which is why this is a field
rather than a shared helper: a session handed another runtime's is pointed at
a directory its CLI never reads, and loses the home its profile chose.
"""


class Runtime(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One runtime an application selects, end to end.

    A transparent carrier: it decides nothing and composes no seam, so an
    application stores one the way it stores any other declaration, and the
    single assignment naming it is the only place a provider is chosen.

    End to end is what makes the carrier worth having. What a session opens
    through, where the runtime keeps a login, and where a workspace's sessions
    write are three facts about one provider, and an application that reads
    them from three places can be switched in only some of them.
    """

    name: str
    login: ProviderLogin
    open: SessionOpener
    workspace_home: WorkspaceHome

    def session_factory(self, request: SessionRequest) -> SessionFactory:
        """Open a session factory for this runtime from a portable request."""
        return self.open(self.contained(request))

    def contained(self, request: SessionRequest) -> SessionRequest:
        """The same request, its sessions pointed at a home of the workspace's own.

        Derived when a session is opened rather than when a request is built.
        A request is a declaration and should cost nothing to state; a home
        is a directory that has to exist, seeded from the account the
        environment selects. Deriving it here is also what keeps the two from
        disagreeing: an application that built the home into a request would
        have chosen a runtime before naming one, and opening that request
        through the other would point it at a directory no CLI there reads.

        A request naming no working directory is returned untouched — there
        is no workspace to contain it against.
        """
        if request.cwd is None:
            return request
        derived = self.workspace_environment(request.environment, request.cwd)
        return request.model_copy(
            update={"environment": {**request.environment, **derived}}
        )

    def workspace_environment(self, environment: EnvVars, workspace: Path) -> EnvVars:
        """Route this runtime's sessions at a home private to that workspace."""
        return self.workspace_home(environment, workspace)
