"""The gate's steps: what must pass before work lands on `dev`, as data.

`lup-dev check` runs them in this order from a worktree's root, every one even after
one fails, those side by side that may go `together` at once, and fails if any did
(`lup_dev.gate`). Each command is the tool alone, which the gate runs through the
project's runner (`uv run` by default), so it uses the worktree's own environment and
code, never the installed judge.
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
    """A file the step builds, from the root: the gate skips the step only where it
    already passed on its `sources` as they stand, leaving that file as it is
    (`lup_dev.gate`, `Check.stale`)."""
    sources: list[str] = []
    """Patterns, from the root, of the files `builds` is made from, among those git
    would commit: what the step generates beside them, which git ignores, isn't
    one."""
    together: bool = False
    """Whether it may run at once with the steps beside it that may too, as it reads
    the worktree and writes nothing they read (`lup_dev.gate`, `Check.each`). A step
    that builds a file never runs at once with one that doesn't: what comes after it
    may read what it builds."""


class Gate(Model):
    """The gate's steps, in the order they run."""

    steps: list[Step] = [
        Step(name="rules", command=["lup-dev", "rules", "check"], together=True),
        Step(name="format", command=["ruff", "format", "--check"], together=True),
        Step(
            name="pytest",
            command=["pytest", "-n", "12", "--dist", "worksteal"],
            together=True,
        ),
        Step(name="lint-imports", command=["lint-imports"], together=True),
    ]
    """Each the tool alone, which the gate runs through the project's runner, and each
    only reading the worktree, so they run at once.

    The tests run on twelve workers (pytest-xdist, which `lup-dev` depends on, so
    it's wherever the gate runs): beside lup's page's tests, eight took the gate's
    checks 66 s, twelve 59 s and sixteen 52 s, in a room of 32 cores with nothing else
    running. Fewer than every core leaves room for other sessions' gates, which made
    the first lup's slowest runs. Work stealing keeps one slow file from holding the
    run. A project whose tests can't share a machine replaces the step.

    lup's rules first: `lup-dev rules check` with no paths checks every file its
    declaration's roles say is checked, lup's rules on the production and protected
    modules, and pyright's errors and warnings and ruff's findings on those and the
    tests, as the judge does at each write, so the gate holds them wherever it
    runs, the judge running or not. It's the one step reading `# lup: ignore`, so
    ruff and pyright aren't steps of their own, which would fail on a finding an
    `ignore` keeps.

    Building lup's own engine isn't among them: only lup's repository has one to
    build, so its step is that repository's own (`LupDevelopment`, in its
    `lup_project.py`), placed before these."""
