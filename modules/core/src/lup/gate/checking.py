"""`lup check`: every module's steps, run on the files of the worktree it's typed in, and a pass recorded by the files it passed on.

It's the `check` verb with nothing cited (`@lup.command(verb="check",
alone=True)`), and runs where it's typed (`here=True`): a branch's own checks,
its tests among them, run in the room it's typed in, from the worktree's root,
in the environment the gate runs in, never where the project runs, which runs
the commit the operator approved (`README.md` here, *Where it runs*).
"""

import asyncio
import hashlib
import tempfile
from itertools import groupby
from pathlib import Path
from typing import ClassVar, Literal

import lup
from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.doors.done import Done
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Operator
from lup.doors.parts import Declared, Part, Program, UnrunError
from lup.gate.findings import Finding, read, variable
from lup.gate.layout import GateLayout
from lup.gate.settings import GateSettings
from lup.gate.steps import Step, Steps
from lup.programs.git import Git
from lup.types import Model


class Checking(Model):
    """The worktree the gate checks, and how."""

    fix: bool = False
    """Run each step's fix first, rewriting the files it would fail on."""
    again: bool = False
    """Run every step even where a pass is recorded for these files."""
    directory: Path | None = None
    """A directory in the worktree to check; left out, where it's typed."""


class Printed(Done):
    """A line a step printed, as a step that tells what it prints says it."""

    line: ClassVar[str] = "{text}"
    text: str


class Found(Done):
    """Something a step found without failing, to be filed."""

    line: ClassVar[str] = "found by {step}, about {about}: {title}"
    step: str
    about: str
    title: str


class StepPassed(Done):
    """A step that passed, how long it took, and what it printed where it tells it."""

    line: ClassVar[str] = "{outcome}  {step}  {seconds:.1f} s"
    outcome: Literal["passed"] = "passed"
    step: str
    seconds: float
    printed: list[Printed] = []


class FixFailed(Done):
    """A step's fix that failed, the step passing after, with what it printed."""

    line: ClassVar[str] = "the fix of {step} failed"
    step: str
    printed: list[Printed] = []


class GatePassed(Done):
    """The gate, passed on a worktree's files, each step as it went."""

    line: ClassVar[str] = "the gate passed in {seconds:.0f} s, recorded for tree {tree}"
    seconds: float
    tree: str
    """The tree git would commit the files as: running the gate again on them,
    or landing them, runs nothing."""
    fixes: list[FixFailed] = []
    steps: list[StepPassed] = []
    found: list[Found] = []


class PassedBefore(Done):
    """The gate, passed on these files before, so nothing ran."""

    line: ClassVar[str] = (
        "the gate passed on tree {tree} already: nothing ran (`--again` runs it)"
    )
    tree: str


class Ran(Model):
    """One step, as it ran: how it ended, how long it took, and what it printed and said."""

    step: Step
    status: int | None
    """Its exit status; none where its program couldn't be run at all."""
    seconds: float
    said: str = ""
    """What it printed, then what it said on its standard error; or why it
    couldn't be run."""
    findings: list[Finding] = []
    """What it found without failing, as it wrote them to the file the gate
    gave it (`lup.gate.findings`)."""

    def passed(self) -> bool:
        """Say whether it passed: its program ran and ended with status 0."""
        return self.status == 0

    def line(self, width: int = 0) -> str:
        """Return its line in the gate's report: how it ended, its name, as wide as `width`, and its time.

        >>> Ran(step=Step(name="format", command=["ruff"]), status=1, seconds=0.25).line(8)
        'failed  format     0.2 s'
        """
        outcome = "passed" if self.passed() else "failed"
        return f"{outcome}  {self.step.name:<{width}} {self.seconds:5.1f} s"


class Stepped(Model):
    """A step as a run of the gate recorded it: whether it passed, its time, and what it said where it failed or tells."""

    name: str
    passed: bool
    seconds: float
    said: str = ""
    """What it printed and said, where it failed or tells what it prints;
    nothing otherwise."""
    findings: list[Finding] = []
    """What it found without failing, to be filed."""


class Run(Model):
    """A run of the gate, recorded by the files it ran on, as git would commit them, and what crossed into it from outside them: whether it passed, and how each step went."""

    tree: str
    """The tree git would commit the worktree's files as."""
    passed: bool
    steps: list[Stepped] = []

    @classmethod
    def of(cls, tree: str, ran: list[Ran]) -> Run:
        """Return the run of the steps `ran` on `tree`, each told where it failed or tells."""
        return cls(
            tree=tree,
            passed=all(each.passed() for each in ran),
            steps=[
                Stepped(
                    name=each.step.name,
                    passed=each.passed(),
                    seconds=each.seconds,
                    said=each.said if not each.passed() or each.step.tells else "",
                    findings=each.findings,
                )
                for each in ran
            ],
        )


class Gating(Part):
    """The gate, run on the worktree it's typed in."""

    declared: Declared
    git: Program = Program(
        name="git",
        why="reads the worktree's files as git would commit them, and finds the git directory its passes are kept in",
        install="https://git-scm.com",
        optional=True,
    )
    """Optional, so a project's container without git starts its other parts;
    the gate runs in a worktree, which git always has."""

    @lup.command(verb="check", says="run the gate", alone=True, here=True)
    async def check(
        self, checking: Checking, by: Agent | Operator
    ) -> GatePassed | PassedBefore:
        """Run every module's gate steps on this worktree's files.

        Each runs from the worktree's root, every one even after one fails, and
        says how it went; refused where one fails, saying what it printed. A pass is recorded by the files it passed on, so running it again on
        them, here or in another worktree, runs nothing (`--again` runs it
        anyway). `--fix` runs each step's fix first.
        """
        start = asyncio.get_running_loop().time()
        within = checking.directory or Path.cwd()
        worktree = await Git.located(within, self.git)
        if worktree is None:
            message = (
                f"{within} is in no git worktree, so the gate has no files to check"
            )
            raise RefusedError(message)
        layout = RepositoryLayout.of(worktree)
        steps = self.declared.held(Steps)
        fixed = (
            [await self.ran(step, step.fix, layout.root) for step in steps if step.fix]
            if checking.fix
            else []
        )
        recorded = GateLayout(common=worktree.common)
        tree = await worktree.staged()
        key = keyed(tree, layout.local)
        if not checking.again and passed(recorded, key) is not None:
            return PassedBefore(tree=tree)
        ran = [
            each
            for batch in batches(steps)
            for each in await asyncio.gather(
                *(self.ran(step, step.command, layout.root) for step in batch)
            )
        ]
        took = asyncio.get_running_loop().time() - start
        failed = [each.step.name for each in ran if not each.passed()]
        kept(recorded, key, Run.of(tree, ran))
        if failed:
            raise RefusedError(reported(fixed, ran, took), about=failed)
        return GatePassed(
            seconds=took,
            tree=tree,
            fixes=[
                FixFailed(
                    step=each.step.name,
                    printed=[Printed(text=line) for line in each.said.splitlines()],
                )
                for each in fixed
                if not each.passed()
            ],
            steps=[
                StepPassed(
                    step=each.step.name,
                    seconds=each.seconds,
                    printed=[
                        Printed(text=line)
                        for line in (each.said.splitlines() if each.step.tells else [])
                    ],
                )
                for each in ran
            ],
            found=[
                Found(step=each.step.name, about=finding.about, title=finding.title)
                for each in ran
                for finding in each.findings
            ],
        )

    async def ran(self, step: Step, words: list[str], root: Path) -> Ran:
        """Run `words`, `step`'s check or its fix, from `root`, and say how it ended, however it did, with what it found, written to a file of its own the gate names in its environment (`lup.gate.findings`)."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        [name, *arguments] = words
        program = self.git.model_copy(
            update={
                "name": name,
                "version": None,
                "probe": [],
                "why": f"runs the gate's step `{step.name}`",
                "install": "",
            }
        )
        with tempfile.TemporaryDirectory(prefix="lup-findings-") as scratch:
            file = Path(scratch) / "findings"
            try:
                finished = await program.ran(
                    *arguments, cwd=root, env={variable(): str(file)}
                )
            except UnrunError as unrun:
                return Ran(
                    step=step, status=None, seconds=loop.time() - start, said=str(unrun)
                )
            found = read(file)
        said = finished.text() + finished.error.decode(errors="replace")
        return Ran(
            step=step,
            status=finished.status,
            seconds=loop.time() - start,
            said=said,
            findings=found,
        )


def keyed(tree: str, local: Path) -> str:
    """Return what a pass on files git would commit as `tree` is recorded by: those files, and the layers of the declaration outside them, the repository's own at `local` and the machine's, which change what runs.

    A landing reads a branch's pass by it too, so a pass recorded in a room is
    found wherever the same files are checked.
    """
    machine = MachineLayout(configuration=GateSettings().xdg_config_home)
    digest = hashlib.sha256(tree.encode())
    for layer in [local, machine.layer]:
        digest.update(b"\0")
        digest.update(layer.read_bytes() if layer.is_file() else b"")
    return digest.hexdigest()


def last(recorded: GateLayout, key: str) -> Run | None:
    """Return the last run `recorded` keeps under `key`, passed or not; none where the gate hasn't run on those files, or where its file is a link, or leads out of the git directory, which the gate never writes.

    A room writes the git directory, so what's read here is a room's word on
    how its gate went, which steers and guards nothing; read on the operator's
    machine, it's never a file elsewhere a link points at.
    """
    found = recorded.runs / f"{key}.json"
    if (
        not found.is_file()
        or found.is_symlink()
        or not found.resolve().is_relative_to(recorded.common.resolve())
    ):
        return None
    return Run.model_validate_json(found.read_bytes())


def passed(recorded: GateLayout, key: str) -> Run | None:
    """Return the run `recorded` keeps under `key` where it passed; none where there's none, or it failed."""
    found = last(recorded, key)
    return found if found is not None and found.passed else None


def kept(recorded: GateLayout, key: str, done: Run) -> None:
    """Keep `done` in `recorded` under `key`, in place of the run before it on those files, written beside its place and moved there whole, so a gate reading it meanwhile never reads half of it."""
    recorded.runs.mkdir(parents=True, exist_ok=True)
    found = recorded.runs / f"{key}.json"
    writing = found.with_suffix(".writing")
    writing.write_text(done.model_dump_json())
    writing.replace(found)


def batches(steps: list[Step]) -> list[list[Step]]:
    """Group `steps` as they run: each run of steps beside one another that may go together at once, every other alone, in their order.

    >>> def step(name: str, together: bool) -> Step:
    ...     return Step(name=name, command=["true"], together=together)
    >>> [[each.name for each in batch] for batch in batches([
    ...     step("page", False), step("rules", True), step("format", True), step("build", False)
    ... ])]
    [['page'], ['rules', 'format'], ['build']]
    """
    return [
        batch
        for together, run in groupby(steps, key=lambda each: each.together)
        for batch in ([list(run)] if together else [[each] for each in run])
    ]


def reported(fixed: list[Ran], ran: list[Ran], took: float) -> str:
    """Return the gate's report: each fix that failed with what it said, each step's line in order, what a failing step or one that tells printed, and how the gate went."""
    width = max((len(each.step.name) for each in ran), default=0)
    lines = [
        *(
            f"the fix of {each.step.name} failed:\n{each.said}"
            for each in fixed
            if not each.passed()
        ),
        *(
            f"{each.line(width)}\n{each.said}"
            if not each.passed() or each.step.tells
            else each.line(width)
            for each in ran
        ),
        *(
            f"found by {each.step.name}, about {finding.about}: {finding.title}"
            for each in ran
            for finding in each.findings
        ),
    ]
    failed = [each.step.name for each in ran if not each.passed()]
    ended = (
        f"The gate failed in {took:.0f} s, on {', '.join(failed)}."
        if failed
        else f"The gate passed in {took:.0f} s."
    )
    return "\n".join([*lines, "", ended])
