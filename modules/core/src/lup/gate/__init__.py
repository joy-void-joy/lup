"""The gate: the steps every module declares, run on a worktree's files, and a pass recorded by the files it passed on.

A module's declaration imports its steps' kind from here (`Step`, `Steps`), as
`lup` re-exports them; the gate itself is a module of its own, `Gate`, among
lup's default modules. Its reasons are in `README.md` here.
"""

from lup.gate.steps import Step, Steps

__all__ = ["Step", "Steps"]
