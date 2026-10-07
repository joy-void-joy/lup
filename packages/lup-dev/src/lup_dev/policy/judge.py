"""One judgement over a set of changed files: role, rules, public API, directives.

Shared by the judgement before an edit lands (`before.py`) and by the checkpoint,
so a change gets the same outcome whichever way it was made (`docs/judging-writes.md`,
*What each change gets*):

| Change | Outcome |
|---|---|
| A test, scratch, docs or data file, at any size | allow |
| An operator's document | ask |
| A protected path | ask |
| Production code with a rule finding on the lines the change touches | refuse |
| A new production file, or a whole-file write over one | ask |
| A change to the public API | ask |
| An added `# lup: ignore` | ask |
| Any other production change | allow, once the rules pass it |

Refuse wins over ask: the operator never reviews a version that would be refused.
Type errors and ruff's findings are information, never a refusal. Removing a note
present when the session started is allowed and reported.
"""

from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from lup.types import Model
from lup_dev.codescan.contract import (
    Checker,
    FileReport,
    Finding,
    Position,
    Source,
    Span,
)
from lup_dev.codescan.directives import (
    Checking,
    Directive,
    Fired,
    Problem,
    added_suppressions,
    missing,
)
from lup_dev.codescan.ruff import Linter
from lup_dev.errors import LupDevError
from lup_dev.policy.roles import Role, Roles
from lup_dev.policy.surface import api_changes

type AskKind = Literal[
    "protected", "operator-document", "new-file", "whole-file", "public-api", "ignore"
]
"""What a change asks the operator about."""

type Outcome = Literal["allow", "ask", "refuse"]


class EngineError(LupDevError):
    """The engine's answer doesn't cover what it was asked about."""


class Change(Model):
    """One file's change, in the three versions the judgement compares."""

    path: Path
    """The file, relative to the worktree's root."""
    before: str | None
    """Its content before the change: the last accepted; none where it's new."""
    after: str | None
    """Its content after the change; none where the change deletes it."""
    baseline: str | None
    """Its content when the session started; none where it didn't exist then."""
    whole: bool = False
    """Whether the change writes the whole of a file that existed."""


class Ask(Model):
    """One thing a change asks the operator."""

    kind: AskKind
    reason: str
    """What's asked, in one line, naming the path, the name or the rule."""

    def covered(self) -> bool:
        """Say whether an approval of the path earlier in the session covers this ask.

        A new file, a whole-file write and a public-API change show the file's
        design, which an approval already showed. A protected path, an operator's
        document and each suppression are asked every time.
        """
        return self.kind in ["new-file", "whole-file", "public-api"]


class RemovedNote(Model):
    """A `# lup:` comment present when the session started, removed since."""

    path: Path
    text: str
    """The comment as written, after `# lup:`."""


class Judgement(Model):
    """What one file's change gets, and why."""

    path: Path
    role: Role
    outcome: Outcome
    asks: list[Ask] = []
    refusing: list[Finding] = []
    """lup's findings on the lines the change touches, which refuse it."""
    untouched: list[Finding] = []
    """lup's findings on lines the change didn't touch, listed but not refusing."""
    information: list[Finding] = []
    """pyright's and ruff's findings in the file, once `ignore`s apply."""
    removed: list[RemovedNote] = []
    """Comments present when the session started that the file no longer holds."""

    def reasons(self) -> list[str]:
        """Say why the outcome, for the verdict log: rules, kinds of ask, or the role.

        >>> Judgement(path=Path("a.md"), role="docs", outcome="allow").reasons()
        ['docs']
        """
        match self.outcome:
            case "refuse":
                return sorted(dict.fromkeys(finding.rule for finding in self.refusing))
            case "ask":
                return [ask.kind for ask in self.asks]
            case "allow":
                return ["rules-pass" if self.role == "production" else self.role]


def touched_lines(before: str | None, after: str) -> list[int]:
    r"""List the lines of `after` a change from `before` touches, counted from 1.

    Every line of a new file. For a deletion, the line now at the place where
    lines were removed, or the last line where they were at the end, since
    joining code there can make a finding.

    >>> touched_lines("a\nb\nc\n", "a\nB\nc\nd\n")
    [2, 4]
    """
    lines = after.splitlines()
    if before is None:
        return list(range(1, len(lines) + 1))
    matcher = SequenceMatcher(a=before.splitlines(), b=lines, autojunk=False)
    last = max(len(lines), 1)

    def joined(start: int) -> range:
        line = min(start + 1, last)
        return range(line, line + 1)

    spans = [
        range(start + 1, end + 1) if end > start else joined(start)
        for tag, _, _, start, end in matcher.get_opcodes()
        if tag != "equal"
    ]
    return sorted(dict.fromkeys(line for span in spans for line in span))


def touches(finding: Finding, touched: list[int]) -> bool:
    """Say whether any line `finding` spans is among `touched`."""
    return any(
        line in touched
        for line in range(finding.span.start.line, finding.span.end.line + 1)
    )


def finding(path: Path, problem: Problem) -> Finding:
    """Report a directive's problem as a lup finding on its line."""
    place = Position(line=problem.line, column=1)
    return Finding(
        path=path,
        span=Span(start=place, end=place),
        owner="lup",
        rule=problem.rule,
        message=problem.message,
        steer=problem.steer,
    )


class Versions(Model):
    """The engine's reports on the versions of one file a judgement compares."""

    after: FileReport | None = None
    before: FileReport | None = None
    baseline: FileReport | None = None
    ruff: list[Finding] = []


class Judge(Model, arbitrary_types_allowed=True):
    """Judges changes to the files of one worktree."""

    root: Path
    roles: Roles
    checker: Checker
    linter: Linter
    conditions: list[str] | None = None
    """The names the project's conditions module binds; none if it declares none."""
    approved: list[Path] = []
    """Paths the operator approved this session, whose design asks are covered."""

    def judge(self, changes: list[Change], *, inform: bool = True) -> list[Judgement]:
        """Judge each change, asking the engine about every version at once.

        With `inform`, test files are checked too, for their type errors and
        ruff's findings; without, only what decides an outcome is checked.
        """
        rules = [
            change
            for change in changes
            if self.roles.is_python(change.path)
            and self.roles.role(change.path) == "production"
        ]
        informed = [
            change
            for change in changes
            if inform
            and self.roles.is_python(change.path)
            and self.roles.role(change.path) == "test"
        ]
        checked = [change for change in [*rules, *informed] if change.after is not None]
        after = self.reports([Source(path=c.path, content=c.after) for c in checked])
        before = self.reports(
            [
                Source(path=c.path, content=c.before)
                for c in rules
                if c.before is not None
            ]
        )
        baseline = self.reports(
            [
                Source(path=c.path, content=c.baseline)
                for c in rules
                if c.baseline is not None
            ]
        )
        ruff = self.linter.findings(
            self.root, [Source(path=c.path, content=c.after) for c in checked]
        )
        return [
            self.one(
                change,
                Versions(
                    after=after.get(change.path),
                    before=before.get(change.path),
                    baseline=baseline.get(change.path),
                    ruff=[found for found in ruff if found.path == change.path],
                ),
            )
            for change in changes
        ]

    def reports(self, sources: list[Source]) -> dict[Path, FileReport]:
        """Ask the engine about `sources`, and return its reports by path."""
        if not sources:
            return {}
        reports = {
            report.path: report for report in self.checker.check(self.root, sources)
        }
        unreported = [source.path for source in sources if source.path not in reports]
        if unreported:
            message = f"the engine reported nothing on {unreported}"
            raise EngineError(message)
        return reports

    def one(self, change: Change, versions: Versions) -> Judgement:
        """Judge one change, from the engine's reports on its versions."""
        role = self.roles.role(change.path)
        removed = [
            RemovedNote(path=change.path, text=directive.identity().text)
            for directive in missing(
                versions.after.directives if versions.after else [],
                versions.baseline.directives if versions.baseline else [],
            )
        ]
        if role == "production" and change.after is None:
            return Judgement(
                path=change.path, role=role, outcome="allow", removed=removed
            )
        match role:
            case "protected":
                pattern = self.roles.project.protected.matching(change.path)
                why = f" ({pattern})" if pattern else ", the project's declaration"
                reason = f"{change.path} is a protected path{why}"
                ask = Ask(kind="protected", reason=reason)
                return Judgement(path=change.path, role=role, outcome="ask", asks=[ask])
            case "operator":
                reason = f"{change.path} is one of the operator's documents"
                ask = Ask(kind="operator-document", reason=reason)
                return Judgement(path=change.path, role=role, outcome="ask", asks=[ask])
            case "production":
                return self.production(change, versions, removed)
            case _:
                kept = self.kept(versions)
                information = [found for found in kept if found.owner != "lup"]
                return Judgement(
                    path=change.path,
                    role=role,
                    outcome="allow",
                    information=information,
                )

    def kept(self, versions: Versions) -> list[Finding]:
        """Return every owner's findings in the after version, once `ignore`s apply."""
        if versions.after is None:
            return []
        directives = versions.after.directives
        return [
            found
            for found in [*versions.after.findings, *versions.ruff]
            if not any(
                directive.keeps(found.rule, found.span.start.line)
                for directive in directives
            )
        ]

    def production(
        self, change: Change, versions: Versions, removed: list[RemovedNote]
    ) -> Judgement:
        """Judge a change to production code: rules first, then what it asks."""
        after = change.after or ""
        asks = [
            *self.design(change, versions),
            *self.suppressions(change.path, versions),
        ]
        if change.path in self.approved:
            asks = [ask for ask in asks if not ask.covered()]
        lup = self.lup_findings(change.path, versions)
        touched = touched_lines(change.before, after)
        refusing = [found for found in lup if touches(found, touched)]
        untouched = [found for found in lup if not touches(found, touched)]
        information = [found for found in self.kept(versions) if found.owner != "lup"]

        def outcome() -> Outcome:
            if refusing:
                return "refuse"
            return "ask" if asks else "allow"

        return Judgement(
            path=change.path,
            role="production",
            outcome=outcome(),
            asks=asks,
            refusing=refusing,
            untouched=untouched,
            information=information,
            removed=removed,
        )

    def lup_findings(self, path: Path, versions: Versions) -> list[Finding]:
        """Return lup's findings once `ignore`s apply, and the directives' problems."""
        if versions.after is None:
            return []
        fired = [*versions.after.findings, *versions.ruff]
        checking = Checking(
            fired=[
                Fired(rule=found.rule, line=found.span.start.line) for found in fired
            ],
            conditions=self.conditions,
        )
        directives: list[Directive] = versions.after.directives
        problems = [
            finding(path, problem)
            for directive in directives
            for problem in directive.problems(checking)
        ]
        kept = [found for found in self.kept(versions) if found.owner == "lup"]
        return [*kept, *problems]

    def design(self, change: Change, versions: Versions) -> list[Ask]:
        """List the design asks of a production change: new, whole, public API."""
        new_file = f"{change.path} is a new production file"
        new = [Ask(kind="new-file", reason=new_file)] if change.before is None else []
        replaced = change.whole and change.before is not None
        whole_file = f"the write replaces the whole of {change.path}"
        whole = [Ask(kind="whole-file", reason=whole_file)] if replaced else []
        if versions.after is None:
            return [*new, *whole]
        api = api_changes(
            versions.baseline.surface if versions.baseline else None,
            versions.before.surface if versions.before else None,
            versions.after.surface,
        )
        public = [
            Ask(kind="public-api", reason=f"{change.path} {each.describe()}")
            for each in api
        ]
        return [*new, *whole, *public]

    def suppressions(self, path: Path, versions: Versions) -> list[Ask]:
        """List an ask for each `# lup: ignore` the change adds."""
        if versions.after is None:
            return []
        before = versions.before.directives if versions.before else []
        return [
            Ask(
                kind="ignore", reason=f"adds `# lup: {added.identity().text}` to {path}"
            )
            for added in added_suppressions(before, versions.after.directives)
        ]
