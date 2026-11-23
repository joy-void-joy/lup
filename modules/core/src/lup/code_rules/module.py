"""`CodeRules`, the module: which of lup's rules a project runs, where they don't read, the gate's `rules` step, and the commands checking a worktree's files (`README.md` here)."""

import asyncio
import hashlib
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from string.templatelib import Template
from typing import ClassVar

from pydantic import Field

import lup
from lup import (
    Agent,
    Blocks,
    Done,
    Line,
    Markdown,
    Model,
    Module,
    Named,
    Operator,
    Part,
    Parts,
    Program,
    RefusedError,
    Span,
    Step,
    Steps,
)
from lup.code_rules.checking import Checked, Exemptions, Settling, Table
from lup.code_rules.engine import Engine, EngineLayout, Source, WarmEngine, Written
from lup.code_rules.errors import CodeRulesError
from lup.code_rules.examples import Examples
from lup.code_rules.guidance import told
from lup.code_rules.promises import CodeRulesPromises, FindingsPromises
from lup.code_rules.reading import read_directives, typescript_directives
from lup.code_rules.reporting import Report
from lup.code_rules.reports import FileReport, RuleInfo
from lup.code_rules.ruff import ruff_findings
from lup.code_rules.telling import Conversation, Ended, Outcome, Telling, key
from lup.declaration.layout import RepositoryLayout
from lup.programs.git.answers import nul_separated
from lup.sessions import CallFinished, CallStarting


class Rules(Named[str]):
    """lup's code rules a project runs, by name, a selection of the engine's table: `CodeRules(rules=Rules().drop("elif", why="…"))`."""


class Tests(Named[str]):
    """Where lup's rules for tests read, as patterns from the worktree's root, as `PurePath.full_match` takes them: a test's files and a module's promises."""


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


class Quieting(Model):
    """Whether to hold back what's told after writes, or lift it."""

    lift: bool = False
    """Lift the quiet: what stands in the files written while it held is told
    once, beside the next call."""


class Quiet(Model):
    """Where each agent's quiet is kept while it holds, in the session's room, which the room's part telling findings reads at each call: a file each, by lup's id for the agent."""

    directory: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "lup-code-rules" / "quiet"
    )

    def file(self, agent: str) -> Path:
        """Return the file saying `agent` is quiet, where it's there."""
        return (
            self.directory / hashlib.blake2b(agent.encode(), digest_size=8).hexdigest()
        )

    def holds(self, agent: str) -> bool:
        """Say whether `agent` asked to be quiet, and hasn't lifted it."""
        return self.file(agent).is_file()


class Reading(Part):
    """What every part running the code rules has: the module's settings, the programs the engine and ruff run through, and reading the worktree's files with them."""

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
            exemptions=Exemptions(
                patterns=list(self.module.exempt.given()),
                tests=list(self.module.tests.given()),
            ),
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


class Guess(Done):
    """A heuristic's guess over prose, listed without failing, to read again."""

    line: ClassVar[str] = "{path}:{row}:{column} - {owner} {rule}: {said}"
    path: str
    row: int
    column: int
    owner: str
    rule: str
    said: str


class RulesChecked(Done):
    """Python files checked, no finding failing, and each guess over prose listed."""

    line: ClassVar[str] = "no finding fails in {files} files"
    files: int
    guesses: list[Guess] = []


class RulesFixed(Done):
    """Ruff's safe fixes applied, and each `ignore` keeping nothing removed."""

    line: ClassVar[str] = (
        "applied ruff's safe fixes, and removed {removed} ignores keeping nothing"
    )
    removed: int


class Quieted(Done):
    """What's told after an agent's writes, held back until they lift it."""

    line: ClassVar[str] = "quiet: nothing is told after your writes until `--lift`"


class Lifted(Done):
    """The quiet lifted: what still stands is told beside the next call."""

    line: ClassVar[str] = (
        "lifted: what still stands in the files you wrote comes beside your next call"
    )


class ExamplesMet(Done):
    """Every rule's examples doing what they're written to."""

    line: ClassVar[str] = (
        "every example of the {rules} rules does what it's written to: "
        "{examples} in all"
    )
    rules: int
    examples: int


class Checker(Reading):
    """The code rules, run on the files of the worktree they're typed in: the gate's `rules` step, and an agent's or the operator's own check."""

    @lup.command(here=True)
    async def check(self, checking: Checking, by: Agent | Operator) -> RulesChecked:
        """Check Python files with lup's rules, pyright and ruff.

        Each finding is kept only by an `ignore`; refused where one fails the
        gate, saying each. Given `.`, it checks every Python file of the worktree it's typed in,
        as the gate's `rules` step does. What `lup check --fix` fixes, and
        guesses over prose, are said apart.
        """
        report = await self.reported(checking.paths)
        if report.failing():
            raise RefusedError(report.text())
        return RulesChecked(
            files=len(report.checked),
            guesses=[
                Guess(
                    path=each.path,
                    row=each.span.start.line,
                    column=each.span.start.column,
                    owner=each.owner,
                    rule=each.rule,
                    said=each.detail or each.message,
                )
                for each in report.everything()
                if each.category == "heuristic"
            ],
        )

    @lup.command(here=True)
    async def fix(self, checking: Checking, by: Agent | Operator) -> RulesFixed:
        """Apply ruff's safe fixes, and remove each idle `ignore`.

        Each `ignore` that keeps nothing, in Python files: what the gate's
        `rules` step runs under `--fix`. Given `.`, it fixes every Python file of the worktree it's typed in.
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
        return RulesFixed(removed=sum(removed))

    @lup.view(here=True)
    async def rules(self, listing: Listing, by: Agent | Operator) -> Blocks:
        """List the rules this project runs, a line each.

        Each with its name, its category, and the mistake it prevents.
        """
        del listing
        table = await self.table()
        running = self.running(table)
        return Blocks.of(
            *(
                Line(
                    id=rule.id,
                    spans=[
                        Span(text=rule.id, tone="strong"),
                        Span(text=f" ({rule.category})", tone="muted"),
                        Span(text=f": {rule.mistake}"),
                    ],
                )
                for rule in table.rules.values()
                if rule.id in running
            )
        )

    @lup.view(here=True)
    async def show(self, showing: Showing, by: Agent | Operator) -> Blocks:
        """Show one of lup's rules whole.

        The mistake it prevents, where it steers, when it's told, and its
        examples, each flagged one rewritten.
        """
        table = await self.table()
        rule = table.rules.get(showing.rule)
        if rule is None:
            message = (
                f"No rule is named `{showing.rule}`: `lup code-rules rules` lists them."
            )
            raise RefusedError(message)
        return Blocks.of(Markdown(id=rule.id, text=shown(rule)))

    @lup.command(here=True)
    async def quiet(self, quieting: Quieting, by: Agent) -> Quieted | Lifted:
        """Hold back what's told after your writes, until you lift it.

        For a refactor you know leaves the code broken for a while; `--lift`
        tells once, beside your next call, what still stands in the files you
        wrote meanwhile.
        """
        held = Quiet().file(by.id)
        if quieting.lift:
            held.unlink(missing_ok=True)
            return Lifted()
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_text(by.id)
        return Quieted()

    @lup.view(here=True)
    async def outcomes(self, listing: Listing, by: Agent | Operator) -> Blocks:
        """Show what became of each rule's findings told after writes.

        In this repository, rule by rule: how many were told, then fixed, kept
        with an `ignore`, or left standing, most told first; what a review of
        the rules reads.
        """
        del listing
        layout = await self.located([])
        engine = await self.engine(layout)
        record = engine.layout.outcomes
        read = [
            Outcome.model_validate_json(each)
            for each in (record.read_text().splitlines() if record.is_file() else [])
            if each.strip()
        ]
        if not read:
            return Blocks.of(
                Line.of(
                    "nothing",
                    "nothing told after a write is recorded in this repository yet",
                    "muted",
                )
            )
        rules = list(dict.fromkeys(f"{each.owner} {each.rule}" for each in read))

        def counted(rule: str, became: str) -> int:
            return sum(
                f"{each.owner} {each.rule}" == rule and each.became == became
                for each in read
            )

        rows = sorted(rules, key=lambda rule: -counted(rule, "told"))
        return Blocks.of(
            Line.of("heading", "rule: told, fixed, kept, left", "muted"),
            *(
                Line(
                    id=rule,
                    spans=[
                        Span(text=rule, tone="strong"),
                        Span(
                            text=(
                                f": {counted(rule, 'told')}, {counted(rule, 'fixed')}, "
                                f"{counted(rule, 'kept')}, "
                                f"{counted(rule, 'told') - counted(rule, 'fixed') - counted(rule, 'kept')}"
                            )
                        ),
                    ],
                )
                for rule in rows
            ),
        )

    @lup.command(here=True)
    async def examples(self, listing: Listing, by: Agent | Operator) -> ExamplesMet:
        """Check every rule's examples, the rules' specification.

        Each flagged one gets its rule's finding and no other of lup's, its
        rewrite passes every rule, pyright and ruff, and each near miss gets
        none of its rule's; refused, naming each that doesn't. It runs in lup's own repository, whose gate checks its table, never a
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
        return ExamplesMet(rules=len(rules), examples=count)


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


class Findings(Reading, room=True):
    """What an agent is told of lup's rules, pyright and ruff right after each write, in their session's own room, on the worktree as it stands.

    It keeps, in memory for as long as the session's room runs, each written
    file's text before the write, and what each conversation was told, so
    each finding is told once (`telling.py`).
    """

    before: dict[str, str] = {}
    """Each file a write is about to change, by its path from the root: its
    text before the write."""
    conversations: dict[str, Conversation] = {}
    """What each conversation was told, by lup's id for its agent."""
    known: Table | None = None
    """The engine's table, read once."""
    warm: WarmEngine | None = None
    """The engine kept running for the worktree, once a check has started it."""
    passes: dict[str, asyncio.Task[list[FileReport]]] = {}
    """Each conversation's importers pass under way since their last write."""

    @lup.on(CallStarting)
    async def remembered(self, starting: CallStarting) -> str | None:
        """Keep the text of each file a write is about to change, so what it changes can be told apart from what was there."""
        root = (await self.located([])).root
        for path in written(root, starting.writes):
            file = root / path
            self.before[path] = file.read_text() if file.is_file() else ""
        return None

    @lup.on(CallFinished)
    async def told(self, finished: CallFinished) -> str | None:
        """Tell what the write introduced on the lines it changed, each finding once in the conversation; at a call that writes nothing, what a half-finished edit left that still stands."""
        conversation = self.conversations.setdefault(finished.agent.id, Conversation())
        layout = await self.located([])
        root = layout.root
        paths = written(root, finished.writes)
        if Quiet().holds(finished.agent.id):
            conversation.quietly = list(dict.fromkeys([*conversation.quietly, *paths]))
            return None
        lifted = await self.lifted(conversation, layout)
        importing = self.imported(finished.agent.id, conversation, root)
        said = await self.heard_write(finished, conversation, layout, paths)
        return "\n\n".join(each for each in [lifted, said, importing] if each) or None

    async def lifted(
        self, conversation: Conversation, layout: RepositoryLayout
    ) -> str | None:
        """Return, once, what stands in the files the conversation wrote while quiet, which they weren't told, now that the quiet's lifted."""
        quietly = [
            each for each in conversation.quietly if (layout.root / each).is_file()
        ]
        conversation.quietly = []
        if not quietly:
            return None
        try:
            checked = await self.checked_now(layout, quietly)
        except CodeRulesError as failed:
            return f"lup couldn't check what you wrote while quiet: {failed}"
        texted = {each.path: (layout.root / each.path).read_text() for each in checked}
        standing = [
            finding
            for each in checked
            for finding in each.failing()
            if finding.category == "design"
            and not finding.fixable
            and key(finding, texted[each.path].splitlines()) not in conversation.told
        ]
        for each in checked:
            self.before[each.path] = texted[each.path]
        return self.telling().said(
            conversation,
            standing,
            texted,
            {},
            title="What stands in the files you wrote while quiet",
        )

    def imported(
        self, agent: str, conversation: Conversation, root: Path
    ) -> str | None:
        """Return what an importers pass that finished since `agent`'s last write found, the type errors in the files importing what they wrote, once."""
        passing = self.passes.get(agent)
        if passing is None or not passing.done():
            return None
        del self.passes[agent]
        if passing.cancelled() or passing.exception() is not None:
            return None
        errors = [
            finding
            for report in passing.result()
            for finding in report.findings
            if finding.owner == "pyright"
            and not finding.rule.startswith(self.telling().following)
        ]
        found = {
            each.path: (root / each.path).read_text()
            for each in errors
            if (root / each.path).is_file()
        }
        return self.telling().said(
            conversation,
            errors,
            found,
            {},
            title="Type errors in the files importing what you changed",
        )

    async def heard_write(
        self,
        finished: CallFinished,
        conversation: Conversation,
        layout: RepositoryLayout,
        paths: list[str],
    ) -> str | None:
        """Return what the write `finished` reports introduced, or, where it wrote nothing, what a half-finished edit left that still stands; and start the pass over the files importing what it wrote."""
        root = layout.root
        if not paths:
            standing = texts(root, conversation)
            released = self.telling().released(conversation, standing)
            return self.telling().said(
                conversation,
                released,
                standing,
                {},
                title="Left by your last writes, and still standing",
            )
        try:
            checked = await self.checked_now(layout, paths)
        except CodeRulesError as failed:
            return f"lup couldn't check what you wrote: {failed}"
        telling = self.telling()
        texted = {each.path: (root / each.path).read_text() for each in checked}
        ended = [
            ending
            for each in checked
            for ending in telling.became(conversation, each, texted[each.path])
        ]
        introduced = [
            finding
            for each in checked
            for finding in telling.heard(
                conversation, each, self.before.get(each.path, ""), texted[each.path]
            )
        ]
        elsewhere = {
            each.path: telling.elsewhere(
                conversation, each, introduced, texted[each.path]
            )
            for each in checked
        }
        said = telling.said(conversation, introduced, texted, elsewhere)
        told = [
            Ended(key=key(each, texted[each.path].splitlines()), became="told")
            for each in introduced
        ]
        self.recorded(finished.agent.id, [*ended, *told])
        warm = self.warm
        python = [each.path for each in checked]
        if warm is not None and python:
            before = self.passes.pop(finished.agent.id, None)
            if before is not None:
                before.cancel()
            self.passes[finished.agent.id] = asyncio.create_task(warm.importers(python))
        return said

    def recorded(self, agent: str, ended: list[Ended]) -> None:
        """Append what became of each finding to the record kept for the next review of the rules, in the repository's git directory."""
        if not ended or self.warm is None:
            return
        record = self.warm.engine.layout.outcomes
        now = datetime.now(UTC)
        lines = [
            Outcome(
                at=now,
                agent=agent,
                path=each.key.path,
                owner=each.key.owner,
                rule=each.key.rule,
                text=each.key.text,
                became=each.became,
            ).model_dump_json()
            for each in ended
        ]
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("a") as appended:
            appended.write("".join(f"{each}\n" for each in lines))

    def telling(self) -> Telling:
        """Return how findings are told, over the engine's table."""
        return Telling(table=self.known or Table())

    async def checked_now(
        self, layout: RepositoryLayout, paths: list[str]
    ) -> list[Checked]:
        """Check the Python files of `paths` with the engine kept running for the worktree, and return them settled."""
        root = layout.root
        python = [each for each in paths if each.endswith(".py")]
        if not python:
            return []
        engine = await self.engine(layout)
        if self.known is None:
            self.known = Table.of(await engine.rules())
        if self.warm is None:
            named = hashlib.blake2b(str(root).encode(), digest_size=8).hexdigest()
            place = Path(tempfile.gettempdir()) / "lup-code-rules"
            self.warm = WarmEngine(
                engine=engine,
                root=root,
                venv=Path(sys.prefix),
                socket=place / f"{named}.sock",
                log=place / f"{named}.log",
            )
        reports = await self.warm.checked(
            self.running(self.known), [Source(path=each) for each in python]
        )
        ruffs = await ruff_findings(self.ruff, root, python)
        settling = Settling(
            table=self.known,
            exemptions=Exemptions(
                patterns=list(self.module.exempt.given()),
                tests=list(self.module.tests.given()),
            ),
        )
        return [
            settling.settled(
                report.model_copy(
                    update={
                        "directives": read_directives((root / report.path).read_text())
                    }
                ),
                [each for each in ruffs if each.path == report.path],
            )
            for report in reports
        ]


def written(root: Path, writes: list[Path]) -> list[str]:
    """Return the files `writes` names that are in the worktree at `root`, by their paths from it."""
    inside = [each.resolve() for each in writes if each.resolve().is_relative_to(root)]
    return [each.relative_to(root).as_posix() for each in inside]


def texts(root: Path, conversation: Conversation) -> dict[str, str]:
    """Return the text of each file what waits in `conversation` is in, as it stands."""
    paths = dict.fromkeys(each.path for each in conversation.held)
    return {
        path: (root / path).read_text() for path in paths if (root / path).is_file()
    }


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
    """Patterns rarely right, told as they're written.

    lup's code rules: patterns that are rarely the right choice, told to an
    agent as they write them, kept with `# lup: ignore`, and checked at the
    gate with pyright's and ruff's findings. Each rule reads pyright's own typed tree, through an engine built where it
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
    tests: Tests = Tests.of(
        "**/tests/**", "**/test_*.py", "**/conftest.py", "**/promises.py"
    )
    steps: Steps = Steps.of(RULES)
    parts: Parts = Parts.of(
        Checker, Findings, Guide, CodeRulesPromises, FindingsPromises
    )
