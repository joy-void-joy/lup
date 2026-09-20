"""Claude Code as one selectable runtime.

Every field of a :class:`~lup.providers.selection.SessionRequest` has a Claude
spelling, so nothing a caller asks for is dropped here. One is narrowed rather
than dropped: Claude's effort ladder starts at ``low``, so a request for
``minimal`` opens at that floor.
"""

from lup.policy.identity import POLICY_ROOT_ENV
from lup.workspace.paths import project_root
from lup.providers.claude.config_home import workspace_config_environment
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.claude.runtime import (
    ClaudeEffort,
    ClaudePermissionMode,
    ClaudeSandboxConfig,
    ClaudeSessionConfig,
    create_claude,
)
from lup.sessions.client import Client
from lup.providers.selection import (
    Runtime,
    SessionAutonomy,
    SessionContainment,
    SessionEffort,
    SessionRequest,
)

# lup: ignore[constant-declaration] — each value is Claude Code's own permission
# mode for the autonomy beside it, over a vocabulary this library closes
CLAUDE_AUTONOMY: dict[SessionAutonomy, ClaudePermissionMode] = {
    "ask": "default",
    "accept_edits": "acceptEdits",
    "plan": "plan",
    "unattended": "bypassPermissions",
}
"""What Claude Code calls each degree of autonomy a caller can ask for."""

# lup: ignore[constant-declaration] — each value is Claude Code's own effort for
# the degree beside it, over a vocabulary this library closes
CLAUDE_EFFORT: dict[SessionEffort, ClaudeEffort] = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
"""What Claude Code calls each degree of effort a caller can ask for.

``minimal`` meets ``low`` because Claude's ladder has no rung beneath it."""


# lup: ignore[constant-declaration] — each value is Claude Code's own sandbox
# setting for the wall beside it, over a vocabulary this library closes
CLAUDE_CONTAINMENT: dict[SessionContainment, ClaudeSandboxConfig | None] = {
    "outer": ClaudeSandboxConfig(enabled=False),
    "inner": ClaudeSandboxConfig(),
    "none": None,
}
"""What Claude Code is told about its own sandbox, behind each wall.

The SDK counterpart of
:data:`~lup.providers.claude.confinement.CLAUDE_CONFINEMENT`, which says the
same thing in argv to a CLI this library launches rather than opens. Both
spell it as the sandbox settings key, because that is the surface it lives
on; only the carrier differs.

``outer`` states the sandbox off rather than leaving it unsaid, so the
session and the policy kernel judging it agree on which wall is load-bearing
— :meth:`~lup.providers.claude.runtime.ClaudeSandboxConfig.posture` reads
this same object. Unsaid, the CLI would answer from a settings file the
spawned session may not even read. ``none`` says nothing on purpose: no
sandbox key is sent, and whatever the runtime's own configuration decides is
what the session gets, which is what a request meant before this axis
existed.
"""


def claude_config(request: SessionRequest) -> ClaudeSessionConfig:
    """Render a portable request into Claude's own session configuration.

    Rendering is separate from building so an application can stack a
    :class:`~lup.providers.config.ConfigTransform` — a compatible endpoint, a
    profile — onto what a request asked for, before any session exists.

    Autonomy and containment render into two fields that decide nothing
    about each other: a permission mode says how much the session may do
    before it asks, and the sandbox settings say what confines it while it
    does. Codex spells both with one word and has to reconcile them; here
    the request's two axes stay two.
    """
    return ClaudeSessionConfig(
        model=request.model,
        system_prompt=request.instructions,
        tools=request.tools,
        allowed_tools=request.allowed_tools,
        disallowed_tools=request.disallowed_tools,
        tool_servers=request.tool_servers,
        permission_mode=(
            None if request.autonomy is None else CLAUDE_AUTONOMY[request.autonomy]
        ),
        effort=(None if request.effort is None else CLAUDE_EFFORT[request.effort]),
        max_turns=request.max_turns,
        max_thinking_tokens=request.max_thinking_tokens,
        cwd=request.cwd,
        sandbox=CLAUDE_CONTAINMENT[request.containment],
        cli_path=request.contained_program,
        environment={**request.environment, POLICY_ROOT_ENV: str(project_root())},
        hooks=request.hooks,
        submission_gate_resolver=request.submission_gate,
    )


def claude_session(request: SessionRequest) -> Client:
    """Render a portable request into a configured Claude session factory."""
    return create_claude(claude_config(request))


CLAUDE_RUNTIME = Runtime(
    name="Claude Code",
    login=CLAUDE_LOGIN,
    open=claude_session,
    workspace_home=workspace_config_environment,
)
"""Claude Code, as the single value an application assigns to select it."""
