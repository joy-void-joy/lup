"""`CodeRules`, the module: which of lup's rules a project runs, where they don't read, the gate's `rules` step, and the commands checking a worktree's files (`README.md` here)."""

import sys
from pathlib import Path
from string.templatelib import Template

import lup
from lup import (
    Agent,
    Model,
    Module,
    Named,
    Operator,
    Part,
    Parts,
    Program,
    RefusedError,
    Step,
    Steps,
)
from lup.code_rules.checking import Checked, Exemptions, Settling, Table
from lup.code_rules.engine import Engine, EngineLayout, Source, Written
from lup.code_rules.errors import CodeRulesError
from lup.code_rules.examples import Examples
from lup.code_rules.guidance import told
from lup.code_rules.promises import CodeRulesPromises
from lup.code_rules.reading import read_directives, typescript_directives
from lup.code_rules.reporting import Report
from lup.code_rules.reports import FileReport, RuleInfo
from lup.code_rules.ruff import ruff_findings
from lup.declaration.layout import RepositoryLayout
from lup.programs.git.answers import nul_separated


class Rules(Named[str]):
    """lup's code rules a project runs, by name, a selection of the engine's table: `CodeRules(rules=Rules().drop("elif", why="…"))`."""


class Exempt(Named[str]):
    """Where lup's rules don't read, as patterns from the worktree's root, as `PurePath.full_match` takes them: tests, whose shapes are a test's own. pyright and ruff still read them."""


class Checking(Model):
    """What to check: Python files, or the directories holding them."""

    paths: list[Path]
    """Python files, or directories holding them, from where it's typed: `.`
    for every Python file of the worktree git would commit."""


class Showing(Model):
    """A rule to show whole."""

    rule: str
    """Its name: `tuple-shape`."""


class Listing(Model):
    """Every rule, a line each: nothing to give."""


class Checker(Part):
    """The code rules, run on the files of the worktree they're typed in: the gate's `rules` step, and an agent's or the operator's own check."""

    module: CodeRules
    node: Program = Program(
        name="node",
        version=">=22.18",
        probe=["--version"],
        optional=True,
        why="runs lup's typed engine, which reads pyright's own tree",
        install="https://nodejs.org",
    )
    """Optional, as each program here is, so a project's container without
    them still starts its other parts; the code rules run where they're
    typed, in a room or a terminal, which has them."""
    git: Program = Program(
        name="git",
        optional=True,
        why="lists the worktree's files, finds where the engine is built, and fetches pyright's source to build it from",
        install="https://git-scm.com",
    )
    pnpm: Program = Program(
        name="pnpm",
        optional=True,
        why="installs pyright's dependencies and the engine's bundler, once, as the engine is built",
        install="https://pnpm.io/installation",
    )
    ruff: Program = Program(
        name="ruff",
        optional=True,
        why="finds ruff's findings, which an `ignore` keeps as it keeps lup's",
        install="https://docs.astral.sh/ruff/installation/",
    )

    @lup.command(here=True)
    async def check(self, checking: Checking, by: Agent | Operator) -> str:
        """Check Python files with lup's rules, pyright and ruff, each finding kept only by an `ignore`; refused where one fails the gate.

        Given `.`, it checks every Python file of the worktree it's typed in,
        as the gate's `rules` step does. What `lup gate check --fix` fixes, and
        guesses over prose, are said apart.
        """
        report = await self.reported(checking.paths)
        if report.failing():
            raise RefusedError(report.text())
        return report.text()

    @lup.command(here=True)
    async def fix(self, checking: Checking, by: Agent | Operator) -> str:
        """Apply ruff's safe fixes, and remove each `ignore` that keeps nothing, in Python files; what the gate's `rules` step runs under `--fix`.

        Given `.`, it fixes every Python file of the worktree it's typed in.
        """
        layout = await self.located(checking.paths)
        paths = await self.files(layout.root, checking.paths)
        fixed = await self.ruff.ran(
            "check", "--fix", "--force-exclude", "--", *paths, cwd=layout.root
        )
        if fixed.status not in [0, 1]:
            message = f"ruff failed, ending with status {fixed.status}: {fixed.said()}"
            raise RefusedError(message)
        report = await self.reported(checking.paths)
        removed = [removing(layout.root, file) for file in report.checked]
        count = sum(removed)
        return f"Applied ruff's safe fixes, and removed {count} `ignore`{'' if count == 1 else 's'} keeping nothing."

    @lup.command(here=True)
    async def rules(self, listing: Listing, by: Agent | Operator) -> str:
        """List lup's rules a line each, those this project runs: its name, its category, and the mistake it prevents."""
        del listing
        table = await self.table()
        running = self.running(table)
        return "\n".join(
            f"{rule.id} ({rule.category}): {rule.mistake}"
            for rule in table.rules.values()
            if rule.id in running
        )

    @lup.command(here=True)
    async def show(self, showing: Showing, by: Agent | Operator) -> str:
        """Show one of lup's rules whole: the mistake it prevents, where it steers, when it's told, and its examples, each flagged one rewritten."""
        table = await self.table()
        rule = table.rules.get(showing.rule)
        if rule is None:
            message = (
                f"No rule is named `{showing.rule}`: `lup code-rules rules` lists them."
            )
            raise RefusedError(message)
        return shown(rule)

    @lup.command(here=True)
    async def examples(self, listing: Listing, by: Agent | Operator) -> str:
        """Check every rule's examples, the rules' specification: each flagged one gets its rule's finding and no other of lup's, its rewrite passes every rule, pyright and ruff, and each near miss gets none of its rule's; refused, naming each that doesn't.

        It runs in lup's own repository, whose gate checks its table, never a
        project's.
        """
        del listing
        layout = await self.located([])
        engine = await self.engine(layout)
        try:
            table = Table.of(await engine.rules())
            rules = [table.rules[each] for each in table.engines()]
            checking = Examples(
                engine=engine,
                ruff=self.ruff,
                venv=Path(sys.prefix),
                config=layout.pyproject,
            )
            unmet = await checking.unmet(rules)
        except CodeRulesError as failed:
            raise RefusedError(str(failed)) from failed
        if unmet:
            raise RefusedError("\n".join(each.said() for each in unmet))
        count = sum(
            len(rule.examples.flags) * 2 + len(rule.examples.passes) for rule in rules
        )
        return f"Every example of the {len(rules)} rules does what it's written to: {count} in all."

    async def located(self, paths: list[Path]) -> RepositoryLayout:
        """Return the worktree holding the first of `paths`, or the one it's typed in where there are none; refused where that's in no worktree."""
        within = next((each for each in paths), Path.cwd()).resolve()
        directory = within if within.is_dir() else within.parent
        layout = await RepositoryLayout.located(self.git, directory)
        if layout is None:
            message = f"{directory} is in no git worktree, so there's nothing to check"
            raise RefusedError(message)
        return layout

    async def engine(self, layout: RepositoryLayout) -> Engine:
        """Return the engine, built in the repository's git directory every worktree shares."""
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
        return Engine(
            node=self.node,
            git=self.git,
            pnpm=self.pnpm,
            layout=EngineLayout(common=Path(common.text().strip())),
        )

    async def table(self) -> Table:
        """Return lup's rules as the engine's table holds them, building it where it isn't."""
        layout = await self.located([])
        engine = await self.engine(layout)
        try:
            return Table.of(await engine.rules())
        except CodeRulesError as failed:
            raise RefusedError(str(failed)) from failed

    def running(self, table: Table) -> list[str]:
        """Return the rules this project runs, by name, as its declaration selects them."""
        known = table.engines()
        placed = self.module.rules.resolve(known, known)
        return [each.entry for each in placed]

    async def files(
        self, root: Path, paths: list[Path], suffixes: list[str] | None = None
    ) -> list[str]:
        """Return the files to check, from `root`: those `paths` name or hold, of those git would commit, ending with one of `suffixes`, Python's by default."""
        endings = suffixes or [".py"]
        within = [path.resolve().relative_to(root).as_posix() for path in paths]
        listed = await self.git.ran(
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *within,
        )
        if listed.status != 0:
            message = f"git can't list {root}'s files: {listed.said()}"
            raise RefusedError(message)
        names = nul_separated(listed.output)
        return sorted(
            dict.fromkeys(
                name
                for name in names
                if Path(name).suffix in endings and (root / name).is_file()
            )
        )

    async def reported(self, paths: list[Path]) -> Report:
        """Check the Python files `paths` name or hold, and return what was found."""
        layout = await self.located(paths)
        engine = await self.engine(layout)
        files = await self.files(layout.root, paths)
        try:
            table = Table.of(await engine.rules())
            reports = await engine.checked(
                layout.root,
                Path(sys.prefix),
                self.running(table),
                [Source(path=each) for each in files],
            )
            ruffs = await ruff_findings(self.ruff, layout.root, files)
        except CodeRulesError as failed:
            raise RefusedError(str(failed)) from failed
        written = [
            Written(path=each, content=(layout.root / each).read_text())
            for each in await self.files(layout.root, paths, [".ts", ".tsx"])
        ]
        try:
            commented = await engine.comments(written) if written else []
        except CodeRulesError as failed:
            raise RefusedError(str(failed)) from failed
        typescript = [
            FileReport(path=each.path, directives=typescript_directives(found))
            for each, found in zip(written, commented, strict=True)
        ]
        settling = Settling(
            table=table,
            exemptions=Exemptions(patterns=list(self.module.exempt.given())),
        )
        checked = [
            settling.settled(
                report.model_copy(
                    update={
                        "directives": read_directives(
                            (layout.root / report.path).read_text()
                        )
                    }
                ),
                [each for each in ruffs if each.path == report.path],
            )
            for report in reports
        ]
        notes = [settling.settled(report, []) for report in typescript]
        return Report(checked=[*checked, *notes], table=table)


def removing(root: Path, checked: Checked) -> int:
    """Remove from the file `checked` each `ignore` keeping nothing, and return how many: the line where it stands alone, else the comment from its `#`."""
    unused = {
        each.span.start.line: each.span.start.column
        for each in checked.standing
        if each.rule == "unused-ignore"
    }
    if not unused:
        return 0
    file = root / checked.path
    lines = file.read_text().splitlines(keepends=True)

    def kept(number: int, text: str) -> str:
        """Return line `number`, `text`, without the `ignore` on it where one keeping nothing is."""
        column = unused.get(number)
        if column is None:
            return text
        # lup: ignore("string-slice", why="cuts the line at the column pyright's tokenizer gave the comment, which no format of the line's own says")
        before = text[: column - 1].rstrip()
        return f"{before}\n" if before else ""

    file.write_text("".join(kept(number, text) for number, text in enumerate(lines, 1)))
    return len(unused)


def shown(rule: RuleInfo) -> str:
    """Return a rule whole: its mistake, its steer, its category, and each example."""
    flagged = [
        f"Flags:\n\n{example.code}\nDone the steer's way:\n\n{example.rewritten}"
        for example in rule.examples.flags
    ]
    passes = [f"Leaves alone:\n\n{example}" for example in rule.examples.passes]
    return "\n".join(
        [
            f"{rule.id} ({rule.category})",
            "",
            rule.mistake,
            "",
            f"steer: {rule.steer}",
            "",
            *flagged,
            *passes,
        ]
    )


class Guide(Part):
    """What a session is told of the code rules and `# lup:` comments, at its start."""

    module: CodeRules

    @lup.guidance
    async def code_rules(self) -> Template:
        """Say what the code rules catch, the few worth knowing before writing, how to check a file, and the `# lup:` comments."""
        return told(self.module.name)


RULES = Step(
    name="rules",
    command=["lup", "code-rules", "check", "."],
    fix=["lup", "code-rules", "fix", "."],
    together=True,
    tells=True,
)
"""Every Python file of the worktree checked with lup's rules, pyright and ruff,
each finding kept only by an `ignore`; its fix applies ruff's safe fixes and
removes each `ignore` keeping nothing. What it lists without failing, guesses
over prose, is told even where it passes."""


class CodeRules(Module):
    """lup's code rules: patterns that are rarely the right choice, told to an agent as they write them, kept with `# lup: ignore`, and checked at the gate with pyright's and ruff's findings.

    Each rule reads pyright's own typed tree, through an engine built where it
    first runs. Tests are exempt from lup's rules, not from pyright's or ruff's.
    """

    name = "code-rules"
    rules: Rules = Rules.all().drop(
        "runtime-mention",
        why=(
            "lup's own architecture, a runtime named only in its adapter: in a "
            "project choosing its runtime by a setting, it fires on every choice"
        ),
    )
    """Every rule of the engine's table but `runtime-mention`, so a rule a later
    release adds runs unless a project drops it."""
    exempt: Exempt = Exempt.of("**/tests/**", "**/test_*.py", "**/conftest.py")
    steps: Steps = Steps.of(RULES)
    parts: Parts = Parts.of(Checker, Guide, CodeRulesPromises)
