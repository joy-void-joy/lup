"""Claude Code as one selectable runtime.

Every field of a :class:`~lup.providers.selection.SessionRequest` has a Claude
spelling, so nothing a caller asks for is dropped or narrowed here. A model
only Codex's catalog lists is refused, since Claude Code has no such model.
"""

from lup.policy.identity import POLICY_ROOT_ENV
from lup.workspace.paths import project_root
from lup.providers.claude.config_home import workspace_config_environment
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.claude.model_choice import claude_model_choice
from lup.providers.claude.models import ClaudeEffort
from lup.providers.claude import (
    Claude,
    ClaudePermissionMode,
    ClaudeTools,
)
from lup.providers.selection import (
    Runtime,
    SessionAutonomy,
    SessionEffort,
    SessionRequest,
)

# lup: ignore[constant-declaration] — each value is Claude Code's own permission
# mode for the autonomy beside it, over a vocabulary this library closes
CLAUDE_AUTONOMY: dict[SessionAutonomy, ClaudePermissionMode] = {
    "ask": "manual",
    "accept_edits": "acceptEdits",
    "plan": "plan",
    "unattended": "bypassPermissions",
}
"""What Claude Code calls each degree of autonomy a caller can ask for."""

# lup: ignore[constant-declaration] — each value is Claude Code's own effort for
# the degree beside it, over a vocabulary this library closes
CLAUDE_EFFORT: dict[SessionEffort, ClaudeEffort] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "ultra": "ultra",
}
"""What Claude Code calls each degree of effort a caller can ask for.

Every rung under its own name: ``ultra`` becomes ``xhigh`` with ultracode on
only where the session's options are compiled, which is also where a model's
own catalog row refuses a rung it lacks."""


def claude_config(request: SessionRequest) -> Claude:
    """Render a portable request into Claude's own session configuration.

    Rendering is separate from building so an application can stack a
    :class:`~lup.providers.config.ConfigTransform` — a compatible endpoint, a
    profile — onto what a request asked for, before any session exists.

    Autonomy and the sandbox render into two fields that decide nothing
    about each other: a permission mode says how much the session may do
    before it asks, and the sandbox settings say what confines it while it
    does. Codex spells both with one word and has to reconcile them; here
    the request's two axes stay two.
    """
    return Claude(
        model=None if request.model is None else claude_model_choice(request.model),
        system_prompt=request.instructions,
        tools=ClaudeTools(builtin=request.tools.builtin, mcp=request.tools.mcp),
        allowed_tools=request.allowed_tools,
        disallowed_tools=request.disallowed_tools,
        permission_mode=(
            None if request.autonomy is None else CLAUDE_AUTONOMY[request.autonomy]
        ),
        effort=(None if request.effort is None else CLAUDE_EFFORT[request.effort]),
        max_turns=request.max_turns,
        max_thinking_tokens=request.max_thinking_tokens,
        cwd=request.cwd,
        sandbox=request.sandbox,
        cli_path=request.contained_program,
        environment={**request.environment, POLICY_ROOT_ENV: str(project_root())},
        hooks=request.hooks,
        submission_gate_resolver=request.submission_gate,
    )


CLAUDE_RUNTIME = Runtime(
    name="Claude Code",
    login=CLAUDE_LOGIN,
    open=claude_config,
    workspace_home=workspace_config_environment,
)
"""Claude Code, as the single value an application assigns to select it."""
