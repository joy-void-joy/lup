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

A pass is recorded by the files it passed on (`Standing`, `Passes`): the tree git
would commit the worktree's files as, tracked and untracked but not ignored, with
the person's own layer of the declaration beside them where the worktree has one,
in the repository's own git directory. A later run on the same files finds it and
runs nothing, so the gate run again on unchanged files costs nothing, and neither
does a push of them (`--again` runs it anyway). A pass is recorded only where the
files after the steps are those the steps checked. `--at` runs the gate on a
commit, in a worktree made at it and removed after (`at_commit`), unless a pass is
recorded for its files: lup's remote helper runs it before a push updates the
integration branch (`lup_dev.remote.helper`).

This is the gate's first shape (`DESIGN.md`, *Keeping the operator in the loop*): comparing against a
branch's base (`--changed`), nested projects' own environments and bounds in time
and memory come later.
"""

import hashlib
import shutil
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from filelock import FileLock, Timeout

from lup import programs
from lup.types import Model
from lup_dev.catalog.gate import Step
from lup_dev.clock import Clock
from lup_dev.declaration.load import load, person_layer
from lup_dev.declaration.requirements import Checked, Needed, Tools, check
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.runner import Runner
from lup_dev.errors import LupDevError
from lup_dev.git import Git, GitError
from lup_dev.layout import GitDirectoryLayout
from lup_dev.stored import read_model, write_model

if TYPE_CHECKING:
    from collections.abc import Callable


class GateError(LupDevError):
    """The gate can't run as asked."""


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
    *Findings*), applied by the session landing the work
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


class Standing(Model):
    """A worktree's files as they stand: what the gate passes on, and a pass is found by."""

    tree: str
    """The tree git would commit them as: the worktree's tracked files and its
    untracked ones git doesn't ignore, as `git add --all` stages them."""
    layer: str | None = None
    """The digest of the person's own layer of the declaration, which git
    ignores, where the worktree has one: it can change the gate's steps."""

    @property
    def name(self) -> str:
        """Name these files as their pass is stored: the tree, then the layer's digest where there's one.

        >>> Standing(tree="4b825dc", layer="9f86d08").name
        '4b825dc-9f86d08'
        """
        return self.tree if self.layer is None else f"{self.tree}-{self.layer}"


def layer(root: Path) -> str | None:
    """Return the digest of the person's own layer of the declaration for the worktree at `root` (`person_layer`), or none where there's none."""
    local = person_layer(root)
    if not local.is_file():
        return None
    return hashlib.sha256(local.read_bytes()).hexdigest()


def standing(root: Path) -> Standing:
    """Return the files of the worktree at `root` as they stand.

    git stages them in an index of its own, a copy of the worktree's so only
    what changed is read again; the worktree's own index stays as it was.
    """
    git = Git(cwd=root)
    own = Path(git.text("rev-parse", "--path-format=absolute", "--git-path", "index"))
    with tempfile.TemporaryDirectory(prefix="lup-standing-") as scratch:
        index = Path(scratch) / "index"
        if own.is_file():
            shutil.copyfile(own, index)
        staging = git.model_copy(update={"index": index})
        staging.run("add", "--all")
        tree = staging.text("write-tree")
    return Standing(tree=tree, layer=layer(root))


class Passed(Model):
    """The gate passed on a worktree's files: which, when, and the steps that ran."""

    files: Standing
    at: datetime
    steps: list[str] = []
    """The gate's steps that passed or were skipped as up to date, in order;
    none where the gate passed in a worktree made for it, whose `lup-dev`
    recorded nothing itself (`at_commit`)."""

    def said(self) -> str:
        """Say this pass, as the gate answers with it.

        >>> from datetime import UTC
        >>> print(Passed(files=Standing(tree="4b825dc642cb6eb9a060e54bf8d69288fbee4904"), at=datetime(2026, 10, 17, 9, 30, tzinfo=UTC)).said())
        The gate passed on these files already, at 2026-10-17 09:30 UTC (tree `4b825dc642cb6eb9a060e54bf8d69288fbee4904`): nothing ran. `--again` runs it anyway.
        """
        return (
            f"The gate passed on these files already, at "
            f"{self.at:%Y-%m-%d %H:%M %Z} (tree `{self.files.tree}`): nothing "
            "ran. `--again` runs it anyway."
        )


class Passes(Model, arbitrary_types_allowed=True):
    """The gate's passes in a repository, one file each, named by the files passed on."""

    directory: Path
    clock: Clock
    """When a pass is recorded."""

    @classmethod
    def of(cls, root: Path, clock: Clock) -> Passes:
        """Return the passes of the repository the worktree at `root` belongs to, kept in its own git directory (`GitDirectoryLayout`)."""
        common = Git(cwd=root).text(
            "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        return cls(
            directory=GitDirectoryLayout(common=Path(common)).passes, clock=clock
        )

    def found(self, files: Standing) -> Passed | None:
        """Return the pass recorded for `files`, or none."""
        return read_model(self.directory / f"{files.name}.json", Passed)

    def record(self, files: Standing, steps: list[str]) -> Passed:
        """Record that the gate passed on `files`, running `steps`, and return the pass."""
        passed = Passed(files=files, at=self.clock.now(), steps=steps)
        write_model(self.directory / f"{files.name}.json", passed)
        return passed


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
    found: Passed | None = None
    """The pass recorded for the worktree's files as they stood, where it
    answered and nothing ran."""
    recorded: Passed | None = None
    """The pass this run recorded, where it passed."""
    moved: bool = False
    """The worktree's files changed while the steps ran, so the pass isn't
    recorded."""


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
    passes: Passes | None = None
    """Where a pass is found and recorded; none to run every step every time."""

    @classmethod
    def declared(
        cls,
        root: Path,
        processes: Processes,
        tools: Tools,
        *,
        fix: bool = False,
        passes: Passes | None = None,
    ) -> Check:
        """Return the gate the declaration at `root` resolves to.

        Raise `ProjectError` where it can't be loaded or doesn't resolve: the gate
        never falls back to the defaults.
        """
        resolved = resolve(load(root, local=person_layer(root)).project)
        return cls(
            root=root,
            processes=processes,
            tools=tools,
            runner=resolved.runner,
            steps=resolved.gate,
            requirements=resolved.requirements,
            fixes=Fixes().steps if fix else [],
            passes=passes,
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

    def run(self, *, again: bool = False) -> Gated:
        """Check every requirement at once, then run the fixes and every step, in order.

        Raise `RequirementError` naming every required one missing, before
        anything runs. Every step runs whatever the ones before gave. With
        fixes, the steps that build a file run first where it's stale, since a
        fix may read what they build (`lup-dev rules fix` reads lup's engine),
        and again in their place only where a fix made it stale again.

        With `passes`, a pass recorded for the worktree's files as they stand
        answers, and nothing runs, unless `again`: the fixes too, since on files
        the gate passed they change nothing. A run that passes is recorded for
        the files its steps checked, those after the fixes, where they're the
        same after the steps.
        """
        passes = self.passes
        if passes is not None and not again:
            found = passes.found(standing(self.root))
            if found is not None:
                return Gated(outcomes=[], found=found)
        report = check(self.requirements, self.tools).require()
        building = [
            step
            for step in self.steps
            if self.fixes and step.builds is not None and self.stale(step)
        ]
        built = [self.one(step) for step in building]
        fixed = [self.one(step) for step in self.fixes]
        checked = None if passes is None else standing(self.root)
        outcomes = [self.one(step) for step in self.steps]
        gated = Gated(off=report.off, outcomes=[*built, *fixed, *outcomes])
        if passes is None or checked is None or failed(gated.outcomes):
            return gated
        if standing(self.root) != checked:
            return gated.model_copy(update={"moved": True})
        recorded = passes.record(checked, [outcome.step for outcome in outcomes])
        return gated.model_copy(update={"recorded": recorded})


def failed(outcomes: list[Outcome]) -> list[str]:
    """Name the steps that failed."""
    return [outcome.step for outcome in outcomes if outcome.result == "failed"]


def report(gated: Gated) -> str:
    """Report what's off, each step's outcome, each failure's output, the verdict, and whether the pass is recorded.

    A pass found, where nothing ran, is said alone.

    >>> print(report(Gated(outcomes=[Outcome(step="ruff", result="passed", code=0)])))
    passed   ruff
    <BLANKLINE>
    The gate passed.
    """
    if gated.found is not None:
        return gated.found.said()

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
    kept = (
        f" It's recorded for these files (tree `{gated.recorded.files.tree}`), so "
        "running it again on them, or pushing them, runs nothing."
        if gated.recorded is not None
        else " The worktree's files changed while it ran, so it isn't recorded."
        if gated.moved
        else ""
    )
    return "\n\n".join([summary, *failures, verdict + kept])


def at_commit(
    root: Path,
    revision: str,
    processes: Processes,
    passes: Passes,
    runner: Runner,
    *,
    say: Callable[[str], None],
    stop: Callable[[Path], None],
    again: bool = False,
) -> Passed | Ran:
    """Run the gate on the commit `revision` names, in a worktree made at it, unless a pass is recorded for its files.

    The worktree at `root` asks: `revision` is read there, and its person's own
    layer joins the commit's files, as it would checked out there. The gate run
    is the commit's own `lup-dev check`, through `runner`, the asking
    worktree's, as the judge runs a tool (`Runner.judging`), so it never
    relocks; what it prints is returned whole. Before the worktree made goes,
    `stop` ends what the run left behind for it, its engine. A pass the run
    doesn't record itself, as a commit's `lup-dev` from before passes were kept
    doesn't, is recorded here, without its steps.

    Raise `GateError` where `revision` names no commit.
    """
    git = Git(cwd=root)
    commit = git.commit(revision)
    if commit is None:
        message = f"`{revision}` names no commit in {root}"
        raise GateError(message)
    files = Standing(
        tree=git.text("rev-parse", f"{commit}^{{tree}}"), layer=layer(root)
    )
    found = None if again else passes.found(files)
    if found is not None:
        return found
    common = git.text("rev-parse", "--path-format=absolute", "--git-common-dir")
    locks = GitDirectoryLayout(common=Path(common)).gates
    locks.mkdir(parents=True, exist_ok=True)
    for each in leftovers(git, locks):
        say(f"Removed {each}, a worktree a run of the gate on a commit left behind.")
    made = Path(tempfile.mkdtemp(prefix=MADE))
    with FileLock(locks / f"{made.name}.lock"):
        try:
            git.run("worktree", "add", "--detach", "--quiet", str(made), commit)
        except GitError:
            made.rmdir()
            raise
        try:
            say(f"The gate runs on {commit}, in a worktree made for it at {made}.")
            command = ["lup-dev", "check", *(["--again"] if again else [])]
            ran = processes.run(runner.judging(command), made)
        finally:
            stop(made)
            git.run("worktree", "remove", "--force", str(made))
    (locks / f"{made.name}.lock").unlink(missing_ok=True)
    if ran.code == 0 and passes.found(files) is None:
        passes.record(files, [])
    return ran


MADE = "lup-gate-"
"""What the name of each worktree a run of the gate on a commit makes starts with, in the system's temporary directory."""


def leftovers(git: Git, locks: Path) -> list[Path]:
    """Remove each worktree a run of the gate on a commit made and left behind, its run gone, and return them.

    A run that's gone holds no lock on its worktree (`GitDirectoryLayout.gates`),
    as one still running does, so the two are told apart, and a run killed
    mid-gate, as a push timed out from its session might be, leaves nothing for
    long. git's records of worktrees whose directories are gone are pruned too.
    """
    scratch = Path(tempfile.gettempdir())
    made = [
        each
        for each in git.worktrees()
        if each.parent == scratch and each.name.startswith(MADE)
    ]
    gone = [each for each in made if not running(locks / f"{each.name}.lock")]
    for each in gone:
        git.run("worktree", "remove", "--force", str(each))
        (locks / f"{each.name}.lock").unlink(missing_ok=True)
    git.run("worktree", "prune")
    return gone


def running(lock: Path) -> bool:
    """Say whether a run of the gate holds the lock at `lock`, on the worktree it made."""
    held = FileLock(lock, timeout=0)
    try:
        held.acquire()
    except Timeout:
        return True
    held.release()
    return False
