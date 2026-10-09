"""The gate as one command: every step, each outcome, a failure that can't be missed.

`lup-dev check` runs the gate's steps (`lup_dev.catalog.gate`) from a worktree's
root, in order, and every one even after one fails, so one run shows everything
wrong. A step that builds a file runs only when that file is missing or older than
its sources: the engine's bundle is rebuilt when its table or source changed, since
tests asking a stale engine fail for reasons the change didn't cause. The report
gives each step's outcome, then each failure's output in full, then which steps
failed; the command exits non-zero when any did, so the gate's verdict is its exit
code rather than something read off its output. With `--fix`, ruff's safe fixes
and the formatter rewrite the worktree first (`Fixes`); without, it only checks.

This is the gate's first shape (`DESIGN.md`, *The gate*): comparing against a
branch's base (`--changed`), nested projects' own environments and bounds in time
and memory come later.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

import sh

from lup.types import Model
from lup_dev.catalog.gate import Gate, Step


class Ran(Model):
    """How one command ended: its exit code, and everything it printed."""

    code: int
    output: str
    """Its standard output and error together, in full."""


class Runner(ABC):
    """Runs a step's command."""

    @abstractmethod
    def run(self, command: list[str], cwd: Path) -> Ran:
        """Run `command` from `cwd`, and say how it ended."""


class Shell(Runner):
    """Runs a command as a process, its output captured whole."""

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        program, *arguments = command
        try:
            ran = sh.Command(program)(
                *arguments,
                _cwd=str(cwd),
                _ok_code=list(range(256)),
                _err_to_out=True,
                _tty_out=False,
                _return_cmd=True,
            )
        except sh.CommandNotFound:
            return Ran(
                code=127, output=f"`{program}` isn't installed, or not on PATH\n"
            )
        return Ran(code=ran.exit_code, output=ran.stdout.decode(errors="replace"))


class Fixes(Model):
    """What `lup-dev check --fix` runs before the gate's steps, rewriting files.

    ruff's safe fixes, then the formatter: what the agent is never told of
    (`docs/judging-writes.md`, *Type errors and ruff's findings*), applied by the
    session landing the work on the merged result (`AGENTS.md`). `--fix-only`
    applies them without reporting what's left, which the gate's own ruff step
    reports. Without `--fix`, as in CI, the gate only checks.
    """

    steps: list[Step] = [
        Step(
            name="fix",
            command=["uv", "run", "ruff", "check", "--fix-only", "--ignore-noqa"],
        ),
        Step(name="reformat", command=["uv", "run", "ruff", "format"]),
    ]


class Outcome(Model):
    """How one step of the gate went."""

    step: str
    result: Literal["passed", "failed", "skipped"]
    code: int | None = None
    """The command's exit code; none where it didn't run."""
    output: str = ""
    why: str = ""
    """Why it was skipped."""


class Check(Model, arbitrary_types_allowed=True):
    """The gate, run over one worktree."""

    root: Path
    runner: Runner
    gate: Gate = Gate()
    fixes: list[Step] = []
    """Steps that rewrite files, run before the gate's: `Fixes`, with `--fix`."""

    def stale(self, step: Step) -> bool:
        """Say whether a step that builds a file must run: it is missing or older."""
        if step.builds is None:
            return True
        built = self.root / step.builds
        if not built.is_file():
            return True
        made = built.stat().st_mtime
        return any(
            source.is_file() and source.stat().st_mtime > made
            for pattern in step.sources
            for source in self.root.glob(pattern)
        )

    def one(self, step: Step) -> Outcome:
        """Run one step, or skip it where what it builds is up to date."""
        if not self.stale(step):
            why = f"{step.builds} is newer than its sources"
            return Outcome(step=step.name, result="skipped", why=why)
        ran = self.runner.run(step.command, self.root)
        result = "passed" if ran.code == 0 else "failed"
        return Outcome(step=step.name, result=result, code=ran.code, output=ran.output)

    def run(self) -> list[Outcome]:
        """Run the fixes, then every step, in order, whatever the ones before gave."""
        return [self.one(step) for step in [*self.fixes, *self.gate.steps]]


def failed(outcomes: list[Outcome]) -> list[str]:
    """Name the steps that failed."""
    return [outcome.step for outcome in outcomes if outcome.result == "failed"]


def report(outcomes: list[Outcome]) -> str:
    """Report each step's outcome, each failure's output in full, then the verdict.

    >>> print(report([Outcome(step="ruff", result="passed", code=0)]))
    passed   ruff
    <BLANKLINE>
    The gate passed.
    """

    def line(outcome: Outcome) -> str:
        detail = (
            f" (exit {outcome.code})"
            if outcome.result == "failed"
            else f" ({outcome.why})"
            if outcome.why
            else ""
        )
        return f"{outcome.result:<8} {outcome.step}{detail}"

    def output(outcome: Outcome) -> str:
        return (
            f"--- {outcome.step} (exit {outcome.code}) ---\n{outcome.output.rstrip()}"
        )

    summary = "\n".join(line(outcome) for outcome in outcomes)
    failures = [output(outcome) for outcome in outcomes if outcome.result == "failed"]
    names = failed(outcomes)
    verdict = f"The gate failed: {', '.join(names)}." if names else "The gate passed."
    return "\n\n".join([summary, *failures, verdict])
