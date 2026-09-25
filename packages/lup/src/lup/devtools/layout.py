"""Checkout layout: where a repository keeps its sibling worktrees.

Both the worktree workflows and the native launchers resolve the same
``tree/`` directory — the workflows to place a new checkout, the launchers
to widen a sandbox write root over it — so the layout is a fact of its own
rather than a detail of either caller.
"""

from pathlib import Path

import typer


def find_tree_dir() -> Path | None:
    """Locate the ``tree/`` directory that holds sibling worktrees, or ``None``.

    Two checkout layouts are supported. In the bare-repo layout the current
    checkout is itself a worktree living inside ``tree/``, so ``tree/`` is the
    parent. Otherwise ``tree/`` sits at the current directory or an ancestor,
    so walking upward lets the command run from anywhere inside the checkout.

    ``None`` where neither holds, so a caller that only wants the layout when
    there is one -- a guard over sibling worktrees that have none to guard --
    reads the absence rather than a raised exit meant for a command the layout
    is a precondition of.
    """
    cwd = Path.cwd().resolve()

    if cwd.parent.name == "tree":
        return cwd.parent

    for directory in (cwd, *cwd.parents):
        tree = directory / "tree"
        if tree.is_dir():
            return tree

    return None


def get_tree_dir() -> Path:
    """The ``tree/`` directory, or an exit for a command that requires one."""
    if tree := find_tree_dir():
        return tree
    typer.echo("Error: Could not find tree/ directory", err=True)
    raise typer.Exit(1)
