"""A gate step: what a module declares the gate runs on a worktree's files, a program run from its root.

Any module declares its steps as a field, a selection a project's or the
operator's layer changes as any field (`Steps().drop("imports", why=…)`), and
the gate runs every module's, in the declaration's order (`README.md` here,
*Steps*).
"""

from typing import Annotated, override

from pydantic import Field

from lup.declaration.grammar import Named
from lup.types import Model


class Step(Model):
    """One step of the gate: a program run from the worktree's root, in the environment the gate runs in, passing where it ends with status 0.

    >>> Step(name="format", command=["ruff", "format", "--check"], fix=["ruff", "format"]).fix
    ['ruff', 'format']
    """

    name: str
    command: Annotated[list[str], Field(min_length=1)]
    """The program and its arguments, as a list, never a line a shell reads."""
    fix: list[str] = []
    """What `--fix` runs first, before any step checks, to rewrite the files
    this step would fail on; none where it fixes nothing."""
    together: bool = False
    """Whether it only reads the worktree, so it may run at once with the
    steps beside it that say so too. A step that writes what another reads,
    as one building a file does, runs alone."""
    tells: bool = False
    """Whether what it prints is told even where it passes, as a step listing
    what's due without failing does; otherwise it's told only where it fails."""


class Steps(Named[Step]):
    """The gate steps a module declares, each by its name."""

    @override
    def named(self, entry: Step) -> str:
        return entry.name
