"""The gate as one command: every step, each outcome, a failure that can't be missed.

`lup-dev check` reads the declaration of the worktree it runs in
(`lup_dev.declaration`), and checks its modules' requirements all at once before
any step: a required tool missing stops the gate, naming every one missing, the
module needing it and how to install it, and an optional one missing is said once,
its feature off. Then it runs the declaration's steps from the root, in order, and
every one even after one fails, so one run shows everything wrong. Each step's
command is the tool alone, run through the project's runner (`uv run …` by
default), or as written for a step that says it isn't run in the environment.

A step that builds a file runs only when that file is missing or older than its
sources: the engine's bundle is rebuilt when its table or source changed, since
tests asking a stale engine fail for reasons the change didn't cause. The report
gives each step's outcome, then each failure's output in full, then which steps
failed; the command exits non-zero when any did, so the gate's verdict is its exit
code rather than something read off its output. With `--fix`, ruff's safe fixes
and the formatter rewrite the worktree first (`Fixes`); without, it only checks.

This is the gate's first shape (`DESIGN.md`, *Code rules and the gate*): comparing against a
branch's base (`--changed`), nested projects' own environments and bounds in time
and memory come later.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, override

from lup import programs
from lup.types import Model
from lup_dev.catalog.gate import Step
from lup_dev.declaration.load import load
from lup_dev.declaration.requirements import Checked, Needed, Tools, check
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.runner import Runner


class Ran(Model):
    """How one command ended: its exit code, and everything it printed."""

    code: int
    output: str
    """Its standard output and error together, in full."""


class Processes(ABC):
    """Where the gate's commands run: the seam its tests stub."""

    @abstractmethod
    def run(self, command: list[str], cwd: Path) -> Ran:
        """Run `command` from `cwd`, and say how it ended."""


class Shell(Processes):
    """Runs a command as a process, its output captured whole."""

    @override
    def run(self, command: list[str], cwd: Path) -> Ran:
        program, *arguments = command
        try:
            ran = programs.run(program, *arguments, cwd=cwd, checked=False, merged=True)
        except programs.ProgramMissingError:
            return Ran(
                code=127, output=f"`{program}` isn't installed, or not on PATH\n"
            )
        return Ran(code=ran.status, output=ran.output.decode(errors="replace"))


class Fixes(Model):
    """What `lup-dev check --fix` runs before the gate's steps, rewriting files.

    ruff's safe fixes, then each `# lup: ignore` that keeps nothing removed, then
    the formatter: what the agent is never told of (`docs/judging-writes.md`,
    *Type errors and ruff's findings*), applied by the session landing the work
    on the merged result (`AGENTS.md`). `--fix-only` applies ruff's without
    reporting what's left, which the gate's `rules` step reports. Without
    `--fix`, as in CI, the gate only checks. Each runs through the project's
    runner, as the gate's steps do.
    """

    steps: list[Step] = [
        Step(name="fix", command=["ruff", "check", "--fix-only", "--ignore-noqa"]),
        Step(name="ignores", command=["lup-dev", "rules", "fix"]),
        Step(name="reformat", command=["ruff", "format"]),
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


class Gated(Model):
    """The gate, run: the optional requirements it went without, and each step's outcome."""

    off: list[Checked] = []
    """Optional requirements not met, whose features are off."""
    outcomes: list[Outcome]


def invoked(step: Step, runner: Runner) -> list[str]:
    """Return what `step` runs: its tool through `runner`, unless it says not.

    The gate runs each step so, and the installer the step building lup's engine.

    >>> from lup_dev.declaration.runner import Uv
    >>> invoked(Step(name="ruff", command=["ruff", "check"]), Uv())
    ['uv', 'run', 'ruff', 'check']
    >>> invoked(Step(name="make", command=["make"], in_environment=False), Uv())
    ['make']
    """
    if step.in_environment:
        return runner.command(step.command)
    return step.command


class Check(Model, arbitrary_types_allowed=True):
    """The gate, run over one worktree."""

    root: Path
    processes: Processes
    tools: Tools
    """Where the requirements are looked for."""
    runner: Runner
    """How the project runs its tools: each step's command runs through it."""
    steps: list[Step]
    requirements: list[Needed] = []
    """Every selected module's requirements, checked before any step runs."""
    fixes: list[Step] = []
    """Steps that rewrite files, run before the gate's: `Fixes`, with `--fix`."""

    @classmethod
    def declared(
        cls, root: Path, processes: Processes, tools: Tools, *, fix: bool = False
    ) -> Check:
        """Return the gate the declaration at `root` resolves to.

        Raise `ProjectError` where it can't be loaded or doesn't resolve: the gate
        never falls back to the defaults.
        """
        resolved = resolve(load(root).project)
        return cls(
            root=root,
            processes=processes,
            tools=tools,
            runner=resolved.runner,
            steps=resolved.gate,
            requirements=resolved.requirements,
            fixes=Fixes().steps if fix else [],
        )

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
        ran = self.processes.run(invoked(step, self.runner), self.root)
        result = "passed" if ran.code == 0 else "failed"
        return Outcome(step=step.name, result=result, code=ran.code, output=ran.output)

    def run(self) -> Gated:
        """Check every requirement at once, then run the fixes and every step, in order.

        Raise `RequirementError` naming every required one missing, before
        anything runs. Every step runs whatever the ones before gave.
        """
        report = check(self.requirements, self.tools).require()
        steps = [*self.fixes, *self.steps]
        return Gated(off=report.off, outcomes=[self.one(step) for step in steps])


def failed(outcomes: list[Outcome]) -> list[str]:
    """Name the steps that failed."""
    return [outcome.step for outcome in outcomes if outcome.result == "failed"]


def report(gated: Gated) -> str:
    """Report what's off, each step's outcome, each failure's output, the verdict.

    >>> print(report(Gated(outcomes=[Outcome(step="ruff", result="passed", code=0)])))
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

    outcomes = gated.outcomes
    off = [f"{'off':<8} {checked.described()}" for checked in gated.off]
    summary = "\n".join([*off, *(line(outcome) for outcome in outcomes)])
    failures = [output(outcome) for outcome in outcomes if outcome.result == "failed"]
    names = failed(outcomes)
    verdict = f"The gate failed: {', '.join(names)}." if names else "The gate passed."
    return "\n\n".join([summary, *failures, verdict])
