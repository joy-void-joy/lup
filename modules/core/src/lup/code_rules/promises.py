"""The code rules' promises: what an agent or the operator typing `lup code-rules check` or `fix` in a worktree, and the gate's `rules` step, can count on.

Each runs the command through the harness on a worktree in a temporary
directory. git, node (the engine), pnpm and ruff are stood in for: git answers
as a repository there would, and the engine answers the findings and `# lup:`
comments each promise draws. Each promise reads whether the check was refused,
what the engine was asked, and the files as they're left, never its words
(`README.md` here). The rules' own examples are the engine's, which build
pyright's program for real.
"""

import tempfile
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, TypeAdapter

import lup
from lup import Agent, Model, Modules, Operator, Part, Project
from lup.code_rules import (
    Examples,
    FileReport,
    Finding,
    Ignore,
    Position,
    RuleInfo,
    Span,
)
from lup.testing import (
    Accepted,
    Answering,
    ProgramRun,
    Refused,
    Responding,
    Testing,
)

# Imported as they're first used, as a promise runs: the module imports these
# promises as it's defined, and would be found half made.
lazy from lup.code_rules import CodeRules, Rules

if TYPE_CHECKING:
    from collections.abc import Generator

type Named = Literal["shape", "spelled", "guessed", "runtime-mention"]
"""The rules of the engine as the promises stand it in: one of each category,
and the one lup's default leaves out."""

TABLE = [
    RuleInfo(
        id="shape",
        mistake="A shape that isn't a model.",
        steer="Make it a model.",
        category="design",
        examples=Examples(),
    ),
    RuleInfo(
        id="spelled",
        mistake="A correct thing spelled the long way.",
        steer="Spell it the short way.",
        category="spelling",
        examples=Examples(),
    ),
    RuleInfo(
        id="guessed",
        mistake="Prose that reads as history.",
        steer="Say what is.",
        category="heuristic",
        examples=Examples(),
    ),
    RuleInfo(
        id="runtime-mention",
        mistake="A runtime named outside its adapter.",
        steer="Speak in lup's own words.",
        category="design",
        examples=Examples(),
    ),
]
"""The engine's table as the promises stand it in."""


class Worktree(Model):
    """A worktree in a temporary directory, its git directory inside it, as a clone's is."""

    root: Path

    def files(self) -> list[str]:
        """List the worktree's files, from its root, as git would."""
        return sorted(
            each.relative_to(self.root).as_posix()
            for each in self.root.rglob("*")
            if each.is_file() and ".git" not in each.relative_to(self.root).parts
        )


class Git(Model, Responding):
    """git, stood in for: answering what the code rules ask of the worktree, and cloning pyright's source as a directory holding what the build reads of it."""

    worktree: Worktree
    common: Path | None = None
    """The git directory every worktree shares, where the engine is built;
    the worktree's own `.git` where it's none."""

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer the worktree's root, its git directory, whether it's bare, its Python files, or a clone made."""
        del given
        root = self.worktree.root
        match arguments:
            case ["-C", _, "rev-parse", "--show-toplevel"]:
                return Answering(output=f"{root}\n")
            case ["-C", _, "rev-parse", "--path-format=absolute", "--git-common-dir"]:
                return Answering(output=f"{self.common or root / '.git'}\n")
            case ["-C", _, "config", "--bool", "core.bare"]:
                return Answering(output="false\n")
            case ["-C", _, "ls-files", "-z", *_]:
                return Answering(
                    output="".join(f"{each}\0" for each in self.worktree.files())
                )
            case ["clone", *_, target]:
                stubs = Path(target) / "packages" / "pyright-internal"
                (stubs / "typeshed-fallback").mkdir(parents=True)
                return Answering()
            case _:
                return None


class Asked(Model):
    """What a check asked of the engine: the rules to run, and the files."""

    rules: list[str]
    sources: list[Source]


class Source(Model):
    """A file a check asked the engine about."""

    path: str
    content: str | None = None


class Engine(Model, Responding):
    """node, stood in for: building the engine by writing its bundle where it's asked to, listing the stood-in table, and answering each file's findings and `# lup:` comments as `reports` says, none for a file it doesn't name."""

    reports: dict[str, FileReport] = {}
    comments: dict[str, list[Commented]] = {}
    """Each TypeScript file's `// lup:` comments, by its path, as TypeScript's
    parser would find them; none for a file it doesn't name."""

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer a step of the engine's build, its rules, a check, or a TypeScript file's `// lup:` comments."""
        match arguments:
            case ["--version"]:
                return Answering(output="v26.7.0\n")
            case [_, "-p", "tsconfig.json"]:
                return Answering()
            case [_, "src/main.ts", *options]:
                written = next(
                    each.removeprefix("--outfile=")
                    for each in options
                    if each.startswith("--outfile=")
                )
                Path(written).write_text("// the engine, as the promises build it\n")
                return Answering()
            case [_, "comments"]:
                asked = TypeAdapter(list[Source]).validate_json(given or b"")
                found = [self.comments.get(each.path, []) for each in asked]
                return Answering(
                    output=TypeAdapter(list[list[Commented]]).dump_json(found).decode()
                )
            case [_, "rules"]:
                return Answering(
                    output=TypeAdapter(list[RuleInfo]).dump_json(TABLE).decode()
                )
            case [_, "check", *_]:
                asked = Asked.model_validate_json(given or b"")
                answered = [
                    self.reports.get(each.path, FileReport(path=each.path))
                    for each in asked.sources
                ]
                return Answering(
                    output=TypeAdapter(list[FileReport]).dump_json(answered).decode()
                )
            case _:
                return None


class Commented(Model):
    """A TypeScript file's `// lup:` comment, as the engine answers it: where it is, what it says after `lup:`, and the line it keeps."""

    line: int
    column: int
    body: str
    covers: int


class Ruff(Model, Responding):
    """ruff, stood in for: finding nothing, and fixing nothing."""

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer a check with no findings, or a fix with nothing to fix."""
        del given
        match arguments:
            case ["check", "--output-format", "json", *_]:
                return Answering(output="[]")
            case ["check", "--fix", *_]:
                return Answering()
            case _:
                return None


class Pnpm(Model, Responding):
    """pnpm, stood in for: every install succeeding."""

    def answered(self, arguments: list[str], given: bytes | None) -> Answering | None:
        """Answer an install."""
        del given
        match arguments:
            case ["install", *_]:
                return Answering()
            case _:
                return None


type Found = Literal["shape", "spelled", "guessed", "reportGeneralTypeIssues"]
"""A rule a finding a promise draws is of: one of lup's of each category, or
pyright's."""


class Drawn(Model):
    """A finding a promise draws: of which rule, on which of a file's lines of code, and whether an `ignore` keeps it."""

    rule: Found
    code: Annotated[int, Field(ge=0, le=4)]
    """Which line of code it's on, counted from 0."""
    kept: bool


def finding(path: str, rule: str, line: int) -> Finding:
    """Return a finding of `rule` on `line` of the file at `path`, as the engine reports it."""
    at = Position(line=line, column=1)
    return Finding(
        path=path,
        span=Span(start=at, end=at),
        owner="pyright" if rule.startswith("report") else "lup",
        rule=rule,
        message="what the check saw",
        detail="what the check saw",
    )


class Laid(Model):
    """A file of lines of code, the `ignore`s kept on each stacked alone above it, and the engine's findings on each, as a promise lays it out."""

    drawn: list[Drawn]

    def text(self) -> str:
        """Return the file: above each line of code, an `ignore` alone for each rule kept on it."""

        def lines() -> Generator[str]:
            for code, rules in enumerate(self.kept()):
                for rule in rules:
                    yield f'# lup: ignore("{rule}", why="kept")\n'
                yield f"held_{code} = 1\n"

        return "".join(lines())

    def kept(self) -> list[list[str]]:
        """Return the rules kept on each line of code, each once."""
        codes = max((each.code for each in self.drawn), default=0) + 1
        return [
            list(dict.fromkeys(e.rule for e in self.drawn if e.kept and e.code == code))
            for code in range(codes)
        ]

    def report(self, path: str) -> FileReport:
        """Return what the engine reports of the file: each finding drawn, on the line its code is on."""
        kept = self.kept()
        lines = [
            sum(len(rules) + 1 for rules in kept[: code + 1])
            for code in range(len(kept))
        ]
        return FileReport(
            path=path,
            findings=[
                finding(path, each.rule, lines[each.code]) for each in self.drawn
            ],
        )


def ran(runs: list[ProgramRun], program: str, word: str) -> list[ProgramRun]:
    """Return the runs of `program` whose words start with `word`, or, for node, run a script with it: `node <bundle> check` is a check."""
    return [
        each
        for each in runs
        if each.program == program
        and word in each.arguments[: 2 if program == "node" else 1]
    ]


def project(dropped: list[Named] | None = None) -> Project:
    """Return a project of lup's default modules and the code rules, the rules of `dropped` left out where it's given."""
    selected = (
        CodeRules()
        if dropped is None
        else CodeRules(rules=Rules.all().drop(*dropped, why="the promise drops it"))
    )
    return Project(modules=Modules.default().add(selected))


@contextmanager
def worktree(*files: str) -> Generator[Worktree]:
    """Make a worktree in a temporary directory holding `files`, each a Python file by its path from the root, and its git directory."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        (root / ".git").mkdir()
        for each in files:
            (root / each).parent.mkdir(parents=True, exist_ok=True)
            (root / each).write_text("held = 1\n")
        yield Worktree(root=root)


@cache
def built() -> Path:
    """Return a git directory the engine is built in once, for every run of the promises that don't promise its build: building it in each run's own worktree would cost each run the copy."""
    kept = tempfile.TemporaryDirectory(prefix="lup-code-rules-")
    built_in.append(kept)
    return Path(kept.name)


built_in: list[tempfile.TemporaryDirectory[str]] = []
"""The git directory `built` made, kept for as long as the promises run."""


def standing(
    at: Worktree,
    reports: dict[str, FileReport] | None = None,
    *,
    fresh: bool = False,
) -> dict[str, Git | Engine | Ruff | Pnpm]:
    """Return git, the engine, pnpm and ruff stood in for over the worktree `at`, the engine answering `reports`, and built in `built()`'s git directory unless `fresh`, in the worktree's own."""
    return {
        "git": Git(worktree=at, common=None if fresh else built()),
        "node": Engine(reports=reports or {}),
        "pnpm": Pnpm(),
        "ruff": Ruff(),
    }


class Checking(Model):
    """What `check` and `fix` are given, as they take it."""

    paths: list[Path]


class CodeRulesPromises(Part):
    """What someone typing `lup code-rules check` or `fix` in a worktree, and the gate's `rules` step, can count on."""

    @lup.promise
    async def a_check_is_refused_exactly_where_a_finding_that_fails_the_gate_stands(
        self, by: Testing
    ) -> None:
        """A check is refused where a finding stands that isn't a heuristic's guess, whether lup's or pyright's; one an `ignore` naming its rule on its line keeps stands no more."""
        drawn = by.any(list[Drawn])
        party = by.any(Agent) if by.any(bool) else Operator()
        path = "main.py"
        laid = Laid(drawn=drawn)
        kept = laid.kept()
        failing = any(
            each.rule not in kept[each.code] and each.rule != "guessed"
            for each in drawn
        )
        with worktree(path) as at:
            (at.root / path).write_text(laid.text())
            started = await by.started(
                project(), programs=standing(at, {path: laid.report(path)})
            )
            checked = await started.run(
                "code-rules", "check", Checking(paths=[at.root]), party
            )
        assert isinstance(checked, Refused if failing else Accepted)

    @lup.promise
    async def an_ignore_keeping_nothing_fails_the_check(self, by: Testing) -> None:
        """An `ignore` keeping no finding of its rule on the line it covers fails the check, so it can't sit there hiding the next one."""
        alone = by.any(bool)
        party = by.any(Agent) if by.any(bool) else Operator()
        path = "main.py"
        ignore = '# lup: ignore("shape", why="none")'
        text = f"{ignore}\nheld = 1\n" if alone else f"held = 1  {ignore}\n"
        with worktree(path) as at:
            (at.root / path).write_text(text)
            started = await by.started(project(), programs=standing(at))
            checked = await started.run(
                "code-rules", "check", Checking(paths=[at.root]), party
            )
        assert isinstance(checked, Refused)

    @lup.promise
    async def a_check_runs_the_rules_the_declaration_selects(self, by: Testing) -> None:
        """A check asks the engine for exactly the rules the project's declaration selects, every rule of the table but those it drops and those lup's default leaves out."""
        dropped = by.any(list[Literal["shape", "spelled", "guessed"]])
        party = by.any(Agent) if by.any(bool) else Operator()
        with worktree("main.py") as at:
            started = await by.started(
                project(["runtime-mention", *dict.fromkeys(dropped)]),
                programs=standing(at),
            )
            await started.run("code-rules", "check", Checking(paths=[at.root]), party)
            checks = [
                Asked.model_validate_json(each.given or b"")
                for each in ran(started.heard.runs, "node", "check")
            ]
        expected = [
            each.id
            for each in TABLE
            if each.id not in dropped and each.id != "runtime-mention"
        ]
        assert [sorted(each.rules) for each in checks] == [sorted(expected)]

    @lup.promise
    async def the_engine_is_built_once_and_found_after(self, by: Testing) -> None:
        """The engine is built where a check first runs, pyright's source fetched once, and every check after in the repository finds it built."""
        checks = 1 + by.any(bool) + by.any(bool)
        party = by.any(Agent) if by.any(bool) else Operator()
        with worktree("main.py") as at:
            started = await by.started(project(), programs=standing(at, fresh=True))
            for _ in range(checks):
                await started.run(
                    "code-rules", "check", Checking(paths=[at.root]), party
                )
            clones = ran(started.heard.runs, "git", "clone")
            bundled = ran(started.heard.runs, "node", "src/main.ts")
        assert len(clones) == 1
        assert len(bundled) == 1

    @lup.promise
    async def a_test_gets_none_of_lups_findings(self, by: Testing) -> None:
        """A file under a test directory gets none of lup's rules' findings, but pyright's still stand there."""
        typed = by.any(bool)
        party = by.any(Agent) if by.any(bool) else Operator()
        path = "tests/test_main.py"
        rules = ["shape", "reportGeneralTypeIssues"] if typed else ["shape"]
        report = FileReport(
            path=path, findings=[finding(path, each, 1) for each in rules]
        )
        with worktree(path) as at:
            started = await by.started(project(), programs=standing(at, {path: report}))
            checked = await started.run(
                "code-rules", "check", Checking(paths=[at.root]), party
            )
        assert isinstance(checked, Refused if typed else Accepted)

    @lup.promise
    async def a_typescript_comment_written_wrong_fails_the_check(
        self, by: Testing
    ) -> None:
        """A TypeScript file's `// lup:` comment is read with the grammar a Python file's is: a `defer` with no way back fails the check, a note never does."""
        wrong = by.any(bool)
        party = by.any(Agent) if by.any(bool) else Operator()
        path = "page/main.ts"
        body = 'defer(why="no way back")' if wrong else "why not a map?"
        said = Commented(line=1, column=1, body=body, covers=2)
        with worktree("main.py") as at:
            (at.root / "page").mkdir()
            (at.root / path).write_text(f"// lup: {body}\nexport const held = 1;\n")
            programs = standing(at)
            programs["node"] = Engine(comments={path: [said]})
            started = await by.started(project(), programs=programs)
            checked = await started.run(
                "code-rules", "check", Checking(paths=[at.root]), party
            )
        assert isinstance(checked, Refused if wrong else Accepted)

    @lup.promise
    async def a_fix_removes_each_ignore_keeping_nothing_and_no_other(
        self, by: Testing
    ) -> None:
        """`fix` removes each `ignore` keeping nothing, its whole line where it stands alone and the comment alone where it follows code, and leaves every other line as it was."""
        placed = by.any(list[Placed])
        party = by.any(Agent) if by.any(bool) else Operator()
        path = "main.py"
        written = Written(placed=placed)
        with worktree(path) as at:
            (at.root / path).write_text(written.text(fixed=False))
            started = await by.started(
                project(), programs=standing(at, {path: written.report(path)})
            )
            await started.run("code-rules", "fix", Checking(paths=[at.root]), party)
            left = (at.root / path).read_text()
        assert left == written.text(fixed=True)


class Placed(Model):
    """An `ignore` a promise places on a line of code: standing alone above it or after it, and keeping a finding there or none."""

    alone: bool
    keeps: bool


class Written(Model):
    """A file of one assignment a line, each with its `ignore`."""

    placed: list[Placed]

    def text(self, *, fixed: bool) -> str:
        """Return the file as it's written, or as `fix` should leave it, each `ignore` keeping nothing removed."""

        def lines() -> Generator[str]:
            for number, each in enumerate(self.placed):
                ignore = '# lup: ignore("shape", why="placed")'
                kept = each.keeps or not fixed
                if each.alone and kept:
                    yield f"{ignore}\n"
                yield f"held_{number} = 1{f'  {ignore}' if kept and not each.alone else ''}\n"

        return "".join(lines())

    def report(self, path: str) -> FileReport:
        """Return what the engine reports of the file as written: each `ignore`, where it is, and a finding of its rule on the line it covers where it keeps one."""

        def placed() -> Generator[Placing]:
            line = 1
            for number, each in enumerate(self.placed):
                code = f"held_{number} = 1"
                covers = line + 1 if each.alone else line
                column = 1 if each.alone else len(code) + 3
                at = Position(line=covers, column=1)
                finding = Finding(
                    path=path,
                    span=Span(start=at, end=at),
                    owner="lup",
                    rule="shape",
                    message="what the check saw",
                )
                ignore = Ignore(
                    line=line, column=column, covers=covers, rule="shape", why="placed"
                )
                yield Placing(ignore=ignore, finding=finding if each.keeps else None)
                line = covers + 1

        found = list(placed())
        return FileReport(
            path=path,
            findings=[each.finding for each in found if each.finding is not None],
            directives=[each.ignore for each in found],
        )


class Placing(Model):
    """An `ignore` as the engine reports it, and the finding of its rule it keeps, where it keeps one."""

    ignore: Ignore
    finding: Finding | None = None
