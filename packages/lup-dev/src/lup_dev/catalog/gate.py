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
        Step(name="format", command=["ruff", "format", "--check"]),
        Step(name="pytest", command=["pytest", "-n", "8", "--dist", "worksteal"]),
        Step(name="lint-imports", command=["lint-imports"]),
    ]
    """Each the tool alone, which the gate runs through the project's runner.

    The tests run on eight workers (pytest-xdist, which `lup-dev` depends on, so
    it's wherever the gate runs): a project's tests mostly wait on processes
    and files rather than compute, and on lup's own eight took the suite from
    161 s to 47 s, sixteen only to 41 s. Fewer than every core leaves room for
    other sessions' gates, which made the first lup's slowest runs. Work
    stealing keeps one slow file from holding the run. A project whose tests
    can't share a machine replaces the step.

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
