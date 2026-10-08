"""The gate's steps: what must pass before work lands on `dev`, as data.

`lup-dev check` runs them in this order from a worktree's root, every one even after
one fails, and fails if any did (`lup_dev.gate`). Each command runs through `uv run`,
so it uses the worktree's own environment and code, never the installed judge.
"""

from lup.types import Model


class Step(Model):
    """One step of the gate: a command run from the worktree's root."""

    name: str
    command: list[str]
    builds: str | None = None
    """A file the step builds, from the root: it runs only when that file is
    missing or older than one of its `sources`."""
    sources: list[str] = []
    """Patterns, from the root, of the files `builds` is made from."""


class Gate(Model):
    """The gate's steps, in the order they run."""

    steps: list[Step] = [
        Step(
            name="engine",
            command=["uv", "run", "python", "packages/lup-dev/checker/build.py"],
            builds="packages/lup-dev/src/lup_dev/codescan/bundle/engine.js",
            sources=[
                "packages/lup-dev/checker/src/**/*",
                "packages/lup-dev/checker/build.py",
                "packages/lup-dev/checker/package.json",
                "packages/lup-dev/checker/package-lock.json",
                "packages/lup-dev/checker/tsconfig.json",
                "packages/lup-dev/src/lup_dev/catalog/rules.ts",
                "uv.lock",
            ],
        ),
        Step(name="ruff", command=["uv", "run", "ruff", "check", "--ignore-noqa"]),
        Step(name="format", command=["uv", "run", "ruff", "format", "--check"]),
        Step(name="pyright", command=["uv", "run", "pyright", "--warnings"]),
        Step(name="pytest", command=["uv", "run", "pytest"]),
        Step(name="lint-imports", command=["uv", "run", "lint-imports"]),
    ]
    """The engine first, rebuilt when its bundle is older than its sources, since
    tests that ask a stale engine fail for reasons the change didn't cause."""
