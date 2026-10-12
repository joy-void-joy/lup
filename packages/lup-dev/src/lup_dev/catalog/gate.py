"""The gate's steps: what must pass before work lands on `dev`, as data.

`lup-dev check` runs them in this order from a worktree's root, every one even after
one fails, and fails if any did (`lup_dev.gate`). Each command is the tool alone,
which the gate runs through the project's runner (`uv run` by default), so it uses
the worktree's own environment and code, never the installed judge.
"""

from lup.types import Model


class Step(Model):
    """One step of the gate: a command run from the worktree's root."""

    name: str
    command: list[str]
    """The tool and its arguments, without how the project runs its tools."""
    in_environment: bool = True
    """Whether the gate runs `command` through the project's runner; otherwise
    it runs as written."""
    builds: str | None = None
    """A file the step builds, from the root: it runs only when that file is
    missing or older than one of its `sources`."""
    sources: list[str] = []
    """Patterns, from the root, of the files `builds` is made from."""


class Gate(Model):
    """The gate's steps, in the order they run."""

    steps: list[Step] = [
        Step(name="rules", command=["lup-dev", "rules", "check"]),
        Step(name="ruff", command=["ruff", "check", "--ignore-noqa"]),
        Step(name="format", command=["ruff", "format", "--check"]),
        Step(name="pyright", command=["pyright", "--warnings"]),
        Step(name="pytest", command=["pytest"]),
        Step(name="lint-imports", command=["lint-imports"]),
    ]
    """Each the tool alone, which the gate runs through the project's runner.

    lup's rules first: `lup-dev rules check` with no paths checks every file its
    declaration's roles say is checked, lup's rules on the production and protected
    modules, as the judge does at each write, so the gate holds them wherever it
    runs, the judge running or not.

    Building lup's own engine isn't among them: only lup's repository has one to
    build, so its step is that repository's own (`LupDevelopment`, in its
    `lup_project.py`), placed before these."""
