"""`Gate`: the module running every module's steps on a worktree's files, among lup's default modules."""

from lup.declaration.module import Module
from lup.doors.parts import Parts
from lup.gate.checking import Gating
from lup.gate.promises import GatePromises
from lup.gate.steps import Step, Steps

FORMAT = Step(
    name="format",
    command=["ruff", "format", "--check"],
    fix=["ruff", "format"],
    together=True,
)
"""Every Python file laid out as ruff's formatter lays it out, which its fix does."""
PROMISES = Step(name="promises", command=["pytest"], together=True)
"""The promises of the modules the declaration resolves to, and the examples in
docstrings, as the project's pytest settings collect them (`lup/testing/README.md`)."""
IMPORTS = Step(name="imports", command=["lint-imports"], together=True)
"""The project's import contracts, as its import-linter settings declare them."""


class Gate(Module):
    """The gate: every module's steps, run on the files of the worktree it's typed in, every one even after one fails, and a pass recorded by the files it passed on, so running it again on them, or landing them, runs nothing.

    Its own steps check what every project lup sets up has: its layout, its
    promises and its import contracts. Another module declares its own as a
    field of `Steps`, and a project drops, edits or replaces any of them as it
    would any selection.
    """

    name = "gate"
    steps: Steps = Steps.of(FORMAT, PROMISES, IMPORTS)
    parts: Parts = Parts.of(Gating, GatePromises)
