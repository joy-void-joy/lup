"""Reflection gate abstraction for enforcing reflect-before-output patterns.

Agents benefit from structured self-assessment before committing to output.
This module provides the domain-neutral gate mechanism:

- ``ReflectionGate``: Flag-based state tracker for whether the agent
  has reflected in the current cycle.
- ``create_reflection_gate()``: Hook factory that denies a target tool
  (e.g., ``StructuredOutput``, ``sleep``) until reflection is recorded.

The reflection *tool* and its input model are domain-specific and belong
in ``agent/tools/``. This module only provides the enforcement mechanism.

One-shot agents: gate ``StructuredOutput`` on reflection.
Persistent agents: gate ``sleep`` on reflection (via ``Scheduler.meta_gate``).

Examples:
    Gate ``StructuredOutput`` until the agent has reflected::

        >>> from lup.reflect import ReflectionGate, create_reflection_gate
        >>> from lup.hooks import merge_hooks
        >>> gate = ReflectionGate()
        >>> gate_hooks = create_reflection_gate(
        ...     gate=gate,
        ...     gated_tool="StructuredOutput",
        ...     reflection_tool_name="mcp__notes__review",
        ... )
        >>> hooks = merge_hooks(permission_hooks, gate_hooks)

    In the reflection tool handler, mark as reflected::

        >>> gate.mark_reflected()
        >>> gate.reflected
        True

    For persistent agents, reset the gate each cycle::

        >>> gate.reset()
        >>> gate.reflected
        False
"""

from lup.hooks import HooksConfig, create_tool_gate


class ReflectionGate:
    """Tracks whether the agent has reflected in the current cycle.

    Used by :func:`create_reflection_gate` to enforce "reflect before X"
    patterns. The reflection tool handler calls :meth:`mark_reflected`
    after saving reflection data. The orchestration layer calls
    :meth:`reset` when a new cycle begins (e.g., after each agent action
    in persistent mode).
    """

    def __init__(self) -> None:
        self.reflected: bool = False

    def mark_reflected(self) -> None:
        """Record that reflection has occurred."""
        self.reflected = True

    def reset(self) -> None:
        """Require fresh reflection (start of new cycle)."""
        self.reflected = False


def create_reflection_gate(
    *,
    gate: ReflectionGate,
    gated_tool: str,
    reflection_tool_name: str = "reflection",
    denial_message: str | None = None,
) -> HooksConfig:
    """Create a PreToolUse hook that denies *gated_tool* until reflection.

    **What:** Preset over :func:`lup.hooks.create_tool_gate` — denies
    *gated_tool* with a message naming *reflection_tool_name* while
    ``gate.reflected`` is False, and explicitly allows it afterwards.

    **When:** Wire this for any "reflect before X" pattern: gate
    ``StructuredOutput`` for one-shot agents or ``sleep`` for persistent
    agents. The reflection tool handler calls
    :meth:`ReflectionGate.mark_reflected`; persistent agents reset the
    gate per cycle via :meth:`ReflectionGate.reset`.

    **Why:** The external :class:`ReflectionGate` object (rather than
    the gate primitive's one-shot ``on_unlock_tool`` tracking) supports
    resettable, per-cycle reflection.

    .. note::

        If you also need to rewrite the gated tool's input (e.g., unwrap
        a ``{"parameter": {...}}`` wrapper), combine both checks in a
        single hook to avoid the CLI bug where multiple PreToolUse hooks
        overwrite each other's ``updatedInput`` (SDK issue #15897).
        Register this gate as the **last** PreToolUse hook.

    Args:
        gate: The :class:`ReflectionGate` instance tracking status.
        gated_tool: Tool name to block (e.g., ``"StructuredOutput"``).
        reflection_tool_name: Name shown in the denial message.
        denial_message: Custom denial text. Uses a sensible default
            if ``None``.

    Returns:
        HooksConfig with a PreToolUse hook.
    """
    default_message = (
        f"You must call {reflection_tool_name}() with your assessment "
        f"BEFORE calling {gated_tool}. Reflect on your work first, "
        f"then try again."
    )

    return create_tool_gate(
        gated_tool=gated_tool,
        message=denial_message or default_message,
        unlocked=lambda _input: gate.reflected,
        allow_when_unlocked=True,
    )
