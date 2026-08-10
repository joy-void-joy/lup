"""Claude Code as one selectable runtime.

Every field of a :class:`~lup.runtime.selection.SessionRequest` has a Claude
spelling, so nothing a caller asks for is dropped here.
"""

from lup.adapters.claude.login import CLAUDE_LOGIN
from lup.adapters.claude.runtime import (
    ClaudePermissionMode,
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.runtime.factory import SessionFactory
from lup.runtime.selection import Runtime, SessionAutonomy, SessionRequest

CLAUDE_AUTONOMY: dict[SessionAutonomy, ClaudePermissionMode] = {
    "ask": "default",
    "accept_edits": "acceptEdits",
    "plan": "plan",
    "unattended": "bypassPermissions",
}
"""What Claude Code calls each degree of autonomy a caller can ask for."""


def claude_session(request: SessionRequest) -> SessionFactory:
    """Render a portable request into a configured Claude session factory."""
    return create_claude_session_factory(
        ClaudeSessionConfig(
            model=request.model,
            system_prompt=request.instructions,
            tools=request.tools,
            allowed_tools=request.allowed_tools,
            tool_servers=request.tool_servers,
            permission_mode=(
                None if request.autonomy is None else CLAUDE_AUTONOMY[request.autonomy]
            ),
            max_turns=request.max_turns,
            max_thinking_tokens=request.max_thinking_tokens,
            cwd=request.cwd,
            environment=request.environment,
            hooks=request.hooks,
        )
    )


CLAUDE_RUNTIME = Runtime(
    name="Claude Code",
    login=CLAUDE_LOGIN,
    open=claude_session,
)
"""Claude Code, as the single value an application assigns to select it."""
