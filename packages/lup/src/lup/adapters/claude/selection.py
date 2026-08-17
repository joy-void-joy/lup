"""Claude Code as one selectable runtime.

Every field of a :class:`~lup.runtime.selection.SessionRequest` has a Claude
spelling, so nothing a caller asks for is dropped here. One is narrowed rather
than dropped: Claude's effort ladder starts at ``low``, so a request for
``minimal`` opens at that floor.
"""

from lup.adapters.claude.login import CLAUDE_LOGIN
from lup.adapters.claude.runtime import (
    ClaudeEffort,
    ClaudePermissionMode,
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.runtime.factory import SessionFactory
from lup.runtime.selection import (
    Runtime,
    SessionAutonomy,
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


def claude_config(request: SessionRequest) -> ClaudeSessionConfig:
    """Render a portable request into Claude's own session configuration.

    Rendering is separate from building so an application can stack a
    :class:`~lup.runtime.config.ConfigTransform` — a compatible endpoint, a
    profile — onto what a request asked for, before any session exists.
    """
    return ClaudeSessionConfig(
        model=request.model,
        system_prompt=request.instructions,
        tools=request.tools,
        allowed_tools=request.allowed_tools,
        tool_servers=request.tool_servers,
        permission_mode=(
            None if request.autonomy is None else CLAUDE_AUTONOMY[request.autonomy]
        ),
        effort=(None if request.effort is None else CLAUDE_EFFORT[request.effort]),
        max_turns=request.max_turns,
        max_thinking_tokens=request.max_thinking_tokens,
        cwd=request.cwd,
        environment=request.environment,
        hooks=request.hooks,
    )


def claude_session(request: SessionRequest) -> SessionFactory:
    """Render a portable request into a configured Claude session factory."""
    return create_claude_session_factory(claude_config(request))


CLAUDE_RUNTIME = Runtime(
    name="Claude Code",
    login=CLAUDE_LOGIN,
    open=claude_session,
)
"""Claude Code, as the single value an application assigns to select it."""
