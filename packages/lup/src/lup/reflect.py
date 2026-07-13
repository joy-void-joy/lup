"""Reflection gate abstraction for enforcing reflect-before-output patterns.

Agents benefit from structured self-assessment before committing to output.
This module provides the domain-neutral gate mechanism:

- ``ReflectionGate``: Flag-based state tracker for whether the agent
  has reflected in the current cycle.

The reflection *tool* and its input model are domain-specific and belong
in ``agent/tools/``. This module only provides the enforcement mechanism.

Hook factories that enforce the gate live in :mod:`lup.hooks` (SDK-agnostic).
Each adapter converts these to its native hook format.

One-shot agents: gate ``StructuredOutput`` on reflection.
Persistent agents: gate ``sleep`` on reflection (via ``Scheduler.meta_gate``).

Examples:
    Gate ``StructuredOutput`` until the agent has reflected::

        >>> from lup.reflect import ReflectionGate
        >>> from lup.hooks import create_reflection_gate, merge_hooks
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

from pathlib import Path

from lup.hooks import LupHooksConfig, create_tool_gate


class ReflectionGate:
    """Tracks whether the agent has reflected in the current cycle.

    Used by :func:`~lup.hooks.create_reflection_gate` to enforce
    "reflect before X" patterns. The reflection tool handler calls :meth:`mark_reflected`
    after saving reflection data. The orchestration layer calls
    :meth:`reset` when a new cycle begins (e.g., after each agent action
    in persistent mode).

    Supports two modes, so enforcement does not depend on any one
    backend's hook support:
    - In-memory (default): when the gate and the enforcement point share
      a process (in-process hooks read ``reflected`` directly).
    - File-backed: when they do not — the flag is a file, marked and
      read across the process boundary. This is what backends without
      firing hooks rely on: the enforcement point checks the flag
      in-tool (inside submit_output) rather than in a hook.
    """

    def __init__(self, flag_path: Path | None = None) -> None:
        self.memory_flag: bool = False
        self.flag_path = flag_path

    @property
    def reflected(self) -> bool:
        if self.flag_path is not None:
            return self.flag_path.exists()
        return self.memory_flag

    @reflected.setter
    def reflected(self, value: bool) -> None:
        self.memory_flag = value
        if self.flag_path is not None:
            if value:
                self.flag_path.parent.mkdir(parents=True, exist_ok=True)
                self.flag_path.touch()
            else:
                self.flag_path.unlink(missing_ok=True)

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
) -> LupHooksConfig:
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
        SDK-agnostic hooks configuration with a PreToolUse hook.
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
        tag="reflection_gate",
    )
