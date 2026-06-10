"""Reflection gate abstraction for enforcing reflect-before-output patterns.

Agents benefit from structured self-assessment before committing to output.
This module provides the domain-neutral gate mechanism:

- ``ReflectionGate``: Flag-based state tracker for whether the agent
  has reflected in the current cycle.

The reflection *tool* and its input model are domain-specific and belong
in ``agent/tools/``. This module only provides the enforcement mechanism.

Hook factories that enforce the gate live in :mod:`lup.lib.hooks` (SDK-agnostic).
Each adapter converts these to its native hook format.

One-shot agents: gate ``StructuredOutput`` on reflection.
Persistent agents: gate ``sleep`` on reflection (via ``Scheduler.meta_gate``).

Examples:
    Gate ``StructuredOutput`` until the agent has reflected::

        >>> from lup.reflect import ReflectionGate
        >>> from lup.hooks import create_reflection_gate
        >>> from lup.types import merge_hooks
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


class ReflectionGate:
    """Tracks whether the agent has reflected in the current cycle.

    Used by :func:`~lup.lib.hooks.create_reflection_gate` to enforce
    "reflect before X" patterns. The reflection tool handler calls :meth:`mark_reflected`
    after saving reflection data. The orchestration layer calls
    :meth:`reset` when a new cycle begins (e.g., after each agent action
    in persistent mode).

    Supports two modes:
    - In-memory (default): For adapters where hooks run in-process.
    - File-backed: For adapters where hooks are external scripts
      that check for a flag file's existence.
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
            elif self.flag_path.exists():
                self.flag_path.unlink()

    def mark_reflected(self) -> None:
        """Record that reflection has occurred."""
        self.reflected = True

    def reset(self) -> None:
        """Require fresh reflection (start of new cycle)."""
        self.reflected = False
