"""`lup gate check`: every module's steps, run on the files of the worktree it's typed in, and a pass recorded by the files it passed on.

It runs where it's typed (`@lup.command(here=True)`): a branch's own checks,
its tests among them, run in the room it's typed in, from the worktree's root,
in the environment the gate runs in, never where the project runs, which runs
the commit the operator approved (`README.md` here, *Where it runs*).
"""

import asyncio
import hashlib
import shutil
import tempfile
from itertools import groupby
from pathlib import Path

import lup
from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.doors.door import RefusedError
from lup.doors.parties import Agent, Operator
from lup.doors.parts import Declared, Part, Program, UnrunError
from lup.gate.layout import GateLayout
from lup.gate.settings import GateSettings
from lup.gate.steps import Step, Steps
from lup.types import Model


class Checking(Model):
    """The worktree the gate checks, and how."""

    fix: bool = False
    """Run each step's fix first, rewriting the files it would fail on."""
    again: bool = False
    """Run every step even where a pass is recorded for these files."""
    directory: Path | None = None
    """A directory in the worktree to check; left out, where it's typed."""


class Ran(Model):
    """One step, as it ran: how it ended, how long it took, and what it printed and said."""

    step: Step
    status: int | None
    """Its exit status; none where its program couldn't be run at all."""
    seconds: float
    said: str = ""
    """What it printed, then what it said on its standard error; or why it
    couldn't be run."""

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


class Timed(Model):
    """A step's time in a pass recorded."""

    name: str
    seconds: float


class Pass(Model):
    """A pass of the gate, recorded by what it passed on: the files, as git would commit them, and what crossed into it from outside them."""

    tree: str
    """The tree git would commit the worktree's files as."""
    steps: list[Timed] = []


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

    @lup.command(here=True)
    async def check(self, checking: Checking, by: Agent | Operator) -> str:
        """Run every module's gate steps on this worktree's files, each from its root, every one even after one fails, and say how each went; refused where one fails.

        A pass is recorded by the files it passed on, so running it again on
        them, here or in another worktree, runs nothing (`--again` runs it
        anyway). `--fix` runs each step's fix first.
        """
        start = asyncio.get_running_loop().time()
        within = checking.directory or Path.cwd()
        layout = await RepositoryLayout.located(self.git, within)
        if layout is None:
            message = (
                f"{within} is in no git worktree, so the gate has no files to check"
            )
            raise RefusedError(message)
        steps = self.declared.held(Steps)
        fixed = (
            [await self.ran(step, step.fix, layout.root) for step in steps if step.fix]
            if checking.fix
            else []
        )
        recorded = await self.recorded(layout)
        tree = await self.tree(layout.root)
        key = keyed(tree, layout)
        if not checking.again and passed(recorded, key) is not None:
            return (
                f"The gate passed on these files already (tree `{tree}`), so "
                "nothing ran. `--again` runs it anyway."
            )
        ran = [
            each
            for batch in batches(steps)
            for each in await asyncio.gather(
                *(self.ran(step, step.command, layout.root) for step in batch)
            )
        ]
        took = asyncio.get_running_loop().time() - start
        report = reported(fixed, ran, took)
        failed = [each.step.name for each in ran if not each.passed()]
        if failed:
            raise RefusedError(report, about=failed)
        kept(
            recorded,
            key,
            Pass(
                tree=tree,
                steps=[
                    Timed(name=each.step.name, seconds=each.seconds) for each in ran
                ],
            ),
        )
        return (
            f"{report}\nIt's recorded for these files (tree `{tree}`), so running "
            "it again on them, or landing them, runs nothing."
        )

    async def ran(self, step: Step, words: list[str], root: Path) -> Ran:
        """Run `words`, `step`'s check or its fix, from `root`, and say how it ended, however it did."""
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
        try:
            finished = await program.ran(*arguments, cwd=root)
        except UnrunError as unrun:
            return Ran(
                step=step, status=None, seconds=loop.time() - start, said=str(unrun)
            )
        said = finished.text() + finished.error.decode(errors="replace")
        return Ran(
            step=step, status=finished.status, seconds=loop.time() - start, said=said
        )

    async def recorded(self, layout: RepositoryLayout) -> GateLayout:
        """Return where the repository at `layout` keeps its passes: in the git directory every worktree shares."""
        common = await self.git.ran(
            "-C",
            str(layout.root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
        if common.status != 0:
            message = (
                f"git can't say where {layout.root} keeps its history: {common.said()}"
            )
            raise RefusedError(message)
        return GateLayout(common=Path(common.text().strip()))

    async def tree(self, root: Path) -> str:
        """Return the tree git would commit the worktree at `root`'s files as, every change and every file it doesn't ignore added, its own index left as it is."""
        index = await self.git.ran(
            "-C",
            str(root),
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "index",
        )
        with tempfile.TemporaryDirectory() as scratch:
            kept = Path(scratch) / "index"
            if index.status == 0:
                copied(Path(index.text().strip()), kept)
            apart = {"GIT_INDEX_FILE": str(kept)}
            added = await self.git.ran("-C", str(root), "add", "--all", env=apart)
            written = await self.git.ran("-C", str(root), "write-tree", env=apart)
        if added.status != 0 or written.status != 0:
            message = (
                f"git can't read {root}'s files as it would commit them: "
                f"{added.said() or written.said()}"
            )
            raise RefusedError(message)
        return written.text().strip()


def copied(index: Path, to: Path) -> None:
    """Copy the worktree's own index to `to`, where it has one, so git reads the files it holds unchanged from it rather than each again; a worktree with none starts from nothing."""
    if index.is_file():
        shutil.copyfile(index, to)


def keyed(tree: str, layout: RepositoryLayout) -> str:
    """Return what a pass on the worktree at `layout`, whose files git would commit as `tree`, is recorded by: those files, and the layers of the declaration outside them, the repository's own and the machine's, which change what runs."""
    machine = MachineLayout(configuration=GateSettings().xdg_config_home)
    digest = hashlib.sha256(tree.encode())
    for layer in [layout.local, machine.layer]:
        digest.update(b"\0")
        digest.update(layer.read_bytes() if layer.is_file() else b"")
    return digest.hexdigest()


def passed(recorded: GateLayout, key: str) -> Pass | None:
    """Return the pass `recorded` keeps under `key`; none where there's none."""
    found = recorded.passes / f"{key}.json"
    return Pass.model_validate_json(found.read_bytes()) if found.is_file() else None


def kept(recorded: GateLayout, key: str, done: Pass) -> None:
    """Keep `done` in `recorded` under `key`, written beside its place and moved there whole, so a gate reading it meanwhile never reads half of it."""
    recorded.passes.mkdir(parents=True, exist_ok=True)
    found = recorded.passes / f"{key}.json"
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
    ]
    failed = [each.step.name for each in ran if not each.passed()]
    ended = (
        f"The gate failed in {took:.0f} s, on {', '.join(failed)}."
        if failed
        else f"The gate passed in {took:.0f} s."
    )
    return "\n".join([*lines, "", ended])
