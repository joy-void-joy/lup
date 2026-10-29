"""One judgement over a set of changed files: role, rules, public API, directives.

Shared by the judgement before an edit lands (`before.py`) and by the checkpoint,
so a change gets the same outcome whichever way it was made (`docs/judging-writes.md`,
*What each change gets*). What a change asks the operator about, each by its name:

| Name | What |
|---|---|
| `protected` | a protected path |
| `operator` | one of the operator's documents |
| `new-file` | a production file being created |
| `whole-file` | a whole-file write over one |
| `public-api` | a change to the public API |
| `ignore` | an added `# lup: ignore` |
| `private` | a value never published on a line it touches, in any path git doesn't ignore |
| a rule's name | one of lup's rules, a finding of on the lines a change touches |

The declaration says how each is answered (`Project.held`, `Project.flagged`):
held, the change waiting for the operator's answer (an `ask`); flagged, the
change landing, for the operator to see in their review of the branch; or
neither, let through. By default a protected path, an operator's document and
an added `ignore` are held, the changes of design and a private value flagged,
and no rule either. The operator's switch for an agent, "hold each flagged
write", holds what's flagged (`Judge.holding`). Tests, scratch, docs and data
are allowed at any size.

A private value is found from the list the `Private` module's launch built on
the host (`lup_dev.private`), in every role, and told as a lup finding is,
naming its kind and never the value (`Judge.withheld`).

lup's findings are told to the agent right after the write, as a type error is,
and fail the gate until each is cleared or kept with an `ignore`, whatever the
outcome. A finding ruff fixes safely isn't reported at all. Removing a note
present when the session started is allowed and reported.
"""

from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal, get_args

from lup.types import Model
from lup_dev.codescan.contract import (
    Checker,
    FileReport,
    Finding,
    Parser,
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
from lup_dev.declaration.kinds import Level
from lup_dev.declaration.project import Asking
from lup_dev.errors import LupDevError
from lup_dev.inbox.store import (
    ApiChanged,
    Asked,
    Found,
    Held,
    Reading,
    Taken,
)
from lup_dev.policy.roles import Role, Roles
from lup_dev.policy.surface import ApiChange, api_changes
from lup_dev.private.found import found as values_in
from lup_dev.private.withheld import Withheld, said

PRIVATE: Asking = "private"
"""The name a private value on a touched line asks by, and the rule its finding
is told under."""

type RoleAsk = Literal["protected", "operator", "role"]
"""What a path's role asks, held or flagged by its level alone (`Levels`): a
protected path and an operator's document by their own names, any other role
as `role`."""

type DesignAsk = Literal["new-file", "whole-file", "public-api"]
"""What a change asks about the code's design, which a role whose level is
`automatic` or `hidden` lets through, the operator not reviewing it; an
`ignore`, a value never published and a rule ask whatever the level, being
about exceptions and publishing rather than review."""

type AskKind = Asking | RoleAsk | Literal["rule"]
"""What a change asks the operator about: a path's role (`RoleAsk`), a kind of
change (`Asking`), or one of lup's rules, a finding of which the project holds
or flags."""

type Outcome = Literal["allow", "ask"]


class EngineError(LupDevError):
    """The engine's answer doesn't cover what it was asked about."""


class Change(Model):
    """One file's change, in the three versions the judgement compares."""

    path: Path
    """The file, relative to the worktree's root."""
    before: str | None
    """Its content before the change: the last accepted; none where it creates it."""
    after: str | None
    """Its content after the change; none where the change deletes it."""
    baseline: str | None
    """Its content when the session started; none where it didn't exist then."""
    whole: bool = False
    """Whether the change writes the whole of a file that existed."""
    published: bool = True
    """Whether git would publish the file: false for a path the repository
    ignores, which no value never published is looked for in."""


class Ask(Model):
    """One thing a change asks the operator."""

    kind: AskKind
    reason: str
    """What's asked, in one line, naming the path, the name or the rule: the
    file from its worktree's root, as the operator reads it beside the file and
    the agent under the file's absolute path."""
    rule: str | None = None
    """The rule a finding of asks, for a `rule` ask; none for any other."""
    line: int | None = None
    """The line an `ignore` the change adds, or a private value, is on, counted
    from 1, in the content after it; none for any other ask."""
    api: ApiChange | None = None
    """The change to the public API, with the line naming it, for a `public-api`
    ask; none for any other."""

    def name(self) -> str:
        """Return the name the declaration holds or flags it by: its kind, or its rule's.

        >>> Ask(kind="rule", rule="regex", reason="r").name()
        'regex'
        """
        return self.rule if self.kind == "rule" and self.rule else self.kind

    def covered(self) -> bool:
        """Say whether an approval of the path earlier in the session covers this ask.

        A file being created, a whole-file write and a public-API change show the
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
    """What's held: the change waits for the operator's answer."""
    flags: list[Ask] = []
    """What's flagged: the change lands, and the operator sees it in their review
    of the branch."""
    findings: list[Finding] = []
    """lup's findings on the lines the change touches: told right after the write,
    and failing the gate until each is cleared or kept with an `ignore`."""
    untouched: list[Finding] = []
    """lup's findings on lines the change didn't touch, told apart."""
    information: list[Finding] = []
    """pyright's and ruff's findings in the file, once `ignore`s apply, but for
    those ruff fixes safely."""
    removed: list[RemovedNote] = []
    """Comments present when the session started that are gone from the file."""

    def reading(self) -> Reading:
        """Return the judge's reading of the file, which the review opens it by: its role, what it asks, held or flagged, each where it is in the file, and lup's findings on the lines the change touches.

        A rule the declaration holds or flags asks through its findings, each
        taken as the declaration takes its rule; one it names neither way is
        told.

        >>> held = Ask(kind="ignore", reason="adds an ignore", line=3)
        >>> judged = Judgement(path=Path("a.py"), role="production", outcome="ask")
        >>> judged.model_copy(update={"asks": [held]}).reading().asks
        [Asked(name='ignore', taken='held', line=3, side='after', api=None)]
        """
        held = [ask.name() for ask in self.asks]
        flagged = [ask.name() for ask in self.flags]

        def taken(rule: str) -> Taken:
            if rule in held:
                return "held"
            return "flagged" if rule in flagged else "told"

        def asked(ask: Ask, how: Held) -> Asked:
            if ask.api is None:
                return Asked(name=ask.name(), taken=how, line=ask.line)
            return Asked(
                name=ask.name(),
                taken=how,
                line=ask.api.line,
                side=ask.api.side(),
                api=ApiChanged(kind=ask.api.kind, name=ask.api.name),
            )

        through = ["rule", PRIVATE]
        return Reading(
            role=self.role,
            asks=[
                *(asked(ask, "held") for ask in self.asks if ask.kind not in through),
                *(
                    asked(ask, "flagged")
                    for ask in self.flags
                    if ask.kind not in through
                ),
            ],
            findings=[
                Found(
                    rule=found.rule,
                    message=found.message,
                    steer=found.steer,
                    start=found.span.start.line,
                    end=found.span.end.line,
                    taken=taken(found.rule),
                )
                for found in self.findings
            ],
        )

    def reasons(self) -> list[str]:
        """Say why the outcome, for the verdict log: the kinds of ask; or, for an allow, the rules its findings are of, else the role.

        >>> Judgement(path=Path("a.md"), role="docs", outcome="allow").reasons()
        ['docs']
        """
        match self.outcome:
            case "ask":
                return [ask.name() for ask in self.asks]
            case "allow" if self.flags:
                return [ask.name() for ask in self.flags]
            case "allow" if self.findings:
                return sorted(dict.fromkeys(finding.rule for finding in self.findings))
            case "allow":
                return ["rules-pass" if self.role == "production" else self.role]


def touched_lines(before: str | None, after: str) -> list[int]:
    r"""List the lines of `after` a change from `before` touches, counted from 1.

    Every line of a file being created. For a deletion, the line standing where
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
        fixable=problem.fixable,
        reminder=problem.reminder,
    )


class Sorted(Model):
    """A change's asks, sorted: those held for the operator, and those flagged."""

    held: list[Ask] = []
    flagged: list[Ask] = []


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
    holding: bool = False
    """Whether every flagged ask is held: the operator's switch for the agent
    writing, "hold each flagged write"."""
    withheld: Withheld | None = None
    """The values never published from the repository, as the `Private`
    module's launch listed them on the host; none where no list was built,
    which finds none."""

    def judge(self, changes: list[Change], *, inform: bool = True) -> list[Judgement]:
        """Judge each change, asking the engine about every version at once.

        With `inform`, test files are checked too, for their type errors and
        ruff's findings; without, only what decides an outcome is checked. Raise
        `EngineError` where the declaration holds or flags a rule the engine's
        table doesn't hold.
        """
        self.named_rules()
        rules = [change for change in changes if self.roles.ruled(change.path)]
        informed = [
            change
            for change in changes
            if inform
            and self.roles.checked(change.path)
            and not self.roles.ruled(change.path)
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
            self.with_private(
                change,
                self.one(
                    change,
                    Versions(
                        after=after.get(change.path),
                        before=before.get(change.path),
                        baseline=baseline.get(change.path),
                        ruff=[found for found in ruff if found.path == change.path],
                    ),
                ),
            )
            for change in changes
        ]

    def parsed(self, changes: list[Change], parser: Parser) -> list[Judgement]:
        """Judge each change from the parse `parser` makes of its versions alone, with no types: what it asks by its path, its content, its public names and its directives.

        Every version is read in one request and none is type-checked, so it
        costs a parse where `judge` costs a check. No rule runs, and ruff
        doesn't: its findings are its directives' own problems, and a rule the
        declaration holds or flags, which asks through its findings, asks
        nothing here.
        """
        ruled = [change for change in changes if self.roles.ruled(change.path)]
        wanted = list(
            dict.fromkeys(
                Source(path=change.path, content=content)
                for change in ruled
                for content in [change.after, change.before, change.baseline]
                if content is not None
            )
        )
        read = dict(zip(wanted, parser.parsed(self.root, wanted), strict=True))

        def report(path: Path, content: str | None) -> FileReport | None:
            return read.get(Source(path=path, content=content))

        return [
            self.with_private(
                change,
                self.one(
                    change,
                    Versions(
                        after=report(change.path, change.after),
                        before=report(change.path, change.before),
                        baseline=report(change.path, change.baseline),
                    ),
                ),
            )
            for change in changes
        ]

    def named_rules(self) -> None:
        """Refuse a rule the declaration holds or flags that the engine's table doesn't hold, naming those it does; the engine is asked only where some rule is named."""
        declaration = self.roles.declaration
        named = [
            name
            for name in [*declaration.held, *declaration.flagged]
            if name not in get_args(Asking.__value__)
        ]
        if not named:
            return
        known = [rule.id for rule in self.checker.rules()]
        unknown = [name for name in named if name not in known]
        if unknown:
            message = (
                f"the declaration holds or flags {unknown}, which lup's rules don't "
                f"name; its rules are {', '.join(known)}"
            )
            raise EngineError(message)

    def reports(self, sources: list[Source]) -> dict[Path, FileReport]:
        """Ask the engine about `sources`, and return its reports by path.

        Each check carries the declaration's rule selection, for the engine to
        resolve, and its runner, for the engine to read types in the environment
        it gives: the declaration the worktree is judged by, or the one standing in
        for it.
        """
        if not sources:
            return {}
        declaration = self.roles.declaration
        reports = {
            report.path: report
            for report in self.checker.check(
                self.root, sources, declaration.rules, declaration.runner
            )
        }
        unreported = [source.path for source in sources if source.path not in reports]
        if unreported:
            message = f"the engine reported nothing on {unreported}"
            raise EngineError(message)
        return reports

    def one(self, change: Change, versions: Versions) -> Judgement:
        """Judge one change, from the engine's reports on its versions, by its path's role and the role's level (`Levels`)."""
        role = self.roles.role(change.path)
        level = self.roles.declaration.levels.get(role, "review")
        removed = [
            RemovedNote(path=change.path, text=directive.identity().text)
            for directive in missing(
                versions.after.directives if versions.after else [],
                versions.baseline.directives if versions.baseline else [],
            )
        ]
        match role:
            case "protected":
                pattern = self.roles.protecting(change.path)
                secret = self.roles.secret(change.path)
                why = f" ({pattern})" if pattern else ", the project's declaration"
                reason = (
                    f"{change.path} is a protected path{why}"
                    if pattern is not None or secret is None
                    else f"{change.path} has the name of a file holding secrets ({secret})"
                )
                ask = Ask(kind="protected", reason=reason)
                if change.after is None or not self.roles.ruled(change.path):
                    sorted_ = self.sorted([ask], level)
                    return Judgement(
                        path=change.path,
                        role=role,
                        outcome="ask" if sorted_.held else "allow",
                        asks=sorted_.held,
                        flags=sorted_.flagged,
                        removed=removed,
                    )
                return self.ruled(change, versions, removed, [ask], level)
            case "operator":
                reason = f"{change.path} is one of the operator's documents"
                sorted_ = self.sorted([Ask(kind="operator", reason=reason)], level)
                return Judgement(
                    path=change.path,
                    role=role,
                    outcome="ask" if sorted_.held else "allow",
                    asks=sorted_.held,
                    flags=sorted_.flagged,
                )
            case "production":
                if change.after is None:
                    return self.leveled(change, role, level, removed)
                own = self.asked(change, role, level)
                return self.ruled(change, versions, removed, own, level)
            case _:
                return self.leveled(change, role, level, [], self.information(versions))

    def asked(self, change: Change, role: Role, level: Level) -> list[Ask]:
        """Return what a change asks by its path's role alone, where the role has no ask of its own: a `role` ask, where its level holds or flags every write; nothing else."""
        if level not in ["held", "flagged"]:
            return []
        reason = (
            f"{change.path} is a {role} path, whose every write the project's "
            f"`Levels` {'holds' if level == 'held' else 'flags'}"
        )
        return [Ask(kind="role", reason=reason)]

    def leveled(
        self,
        change: Change,
        role: Role,
        level: Level,
        removed: list[RemovedNote],
        information: list[Finding] | None = None,
    ) -> Judgement:
        """Judge a change no rule reads by its path's role alone: let through, or, where the role's level holds or flags every write, asking `role`."""
        sorted_ = self.sorted(self.asked(change, role, level), level)
        return Judgement(
            path=change.path,
            role=role,
            outcome="ask" if sorted_.held else "allow",
            asks=sorted_.held,
            flags=sorted_.flagged,
            removed=removed,
            information=information or [],
        )

    def private(self, change: Change) -> list[Finding]:
        """Return each value never published in what a change writes, as a lup finding naming its kind, never the value: in its content, and in the path of a file it creates.

        None where no list was built, where the change deletes the file, or
        where git ignores its path, which nothing publishes.
        """
        if self.withheld is None or change.after is None or not change.published:
            return []

        def finding(line: int, column: int, end: int, what: str, steer: str) -> Finding:
            return Finding(
                path=change.path,
                span=Span(
                    start=Position(line=line, column=column),
                    end=Position(line=line, column=end),
                ),
                owner="lup",
                rule=PRIVATE,
                message=what,
                steer=steer,
            )

        within = [
            finding(each.line, each.column, each.end, said_.what, said_.steer)
            for each in values_in(change.after, self.withheld)
            for said_ in [said(each.held.kind)]
        ]
        named = [
            finding(1, 1, 1, f"{said_.what}, in the file's path", said_.steer)
            for each in values_in(str(change.path), self.withheld)
            if change.before is None
            for said_ in [said(each.held.kind)]
        ]
        return [*named, *within]

    def with_private(self, change: Change, judgement: Judgement) -> Judgement:
        """Add to `judgement` each value never published the change writes: on a line it touches, a finding told and an ask by `private`, held or flagged as the declaration says; elsewhere, a finding told apart."""
        every = self.private(change)
        if not every:
            return judgement
        touched = touched_lines(change.before, change.after or "")
        on = [each for each in every if touches(each, touched)]
        asks = self.sorted(
            [
                Ask(
                    kind=PRIVATE,
                    reason=f"{change.path}:{each.span.start.line} - {each.message}",
                    line=each.span.start.line,
                )
                for each in on
            ]
        )
        held = [*judgement.asks, *asks.held]
        return judgement.model_copy(
            update={
                "outcome": "ask" if held else judgement.outcome,
                "asks": held,
                "flags": [*judgement.flags, *asks.flagged],
                "findings": [*judgement.findings, *on],
                "untouched": [
                    *judgement.untouched,
                    *(each for each in every if not touches(each, touched)),
                ],
            }
        )

    def sorted(self, asks: list[Ask], level: Level = "review") -> Sorted:
        """Sort a change's asks as the declaration says, its path's role's level being `level`: an ask of the role's held or flagged by that level (`Levels`); one about the code's design let through where the level is `automatic` or `hidden`, the operator not reviewing the role; every other held or flagged by its name (`Project.held`, `Project.flagged`), and the rest let through. Every flagged one is held where the operator holds each flagged write of the agent (`holding`)."""
        held = self.roles.declaration.held
        flagged = self.roles.declaration.flagged

        def taken(ask: Ask) -> Level | None:
            if ask.kind in get_args(RoleAsk.__value__):
                return level if level in ["held", "flagged"] else None
            if ask.kind in get_args(DesignAsk.__value__) and level in [
                "automatic",
                "hidden",
            ]:
                return None
            name = ask.name()
            return "held" if name in held else "flagged" if name in flagged else None

        return Sorted(
            held=[
                ask
                for ask in asks
                if (way := taken(ask)) == "held" or (self.holding and way == "flagged")
            ],
            flagged=[
                ask for ask in asks if taken(ask) == "flagged" and not self.holding
            ],
        )

    def kept(self, versions: Versions) -> list[Finding]:
        """Return the engine's and ruff's findings in the after version that hold in its file (`Roles.kept`)."""
        if versions.after is None:
            return []
        return self.roles.kept(
            versions.after, [*versions.after.findings, *versions.ruff]
        )

    def information(self, versions: Versions) -> list[Finding]:
        """Return the type errors and ruff's findings the agent hears as information.

        A finding ruff fixes safely isn't among them: the session landing the work
        applies the fix. It still counts for the `ignore` that names it.
        """
        return [
            found
            for found in self.kept(versions)
            if found.owner != "lup" and not found.fixable
        ]

    def ruled(
        self,
        change: Change,
        versions: Versions,
        removed: list[RemovedNote],
        always: list[Ask],
        level: Level = "review",
    ) -> Judgement:
        """Judge a change lup's rules read: what it asks, and its findings, which are told.

        Production code and protected modules alike; `always` is what the path
        asks whatever the change, which no approval covers; `level` its role's,
        which its asks are sorted by (`sorted`).
        """
        after = change.after or ""
        design = [
            *self.design(change, versions),
            *self.suppressions(change.path, versions),
        ]
        covered = change.path in self.approved
        lup = self.lup_findings(change.path, versions)
        touched = touched_lines(change.before, after)
        findings = [found for found in lup if touches(found, touched)]
        untouched = [found for found in lup if not touches(found, touched)]
        information = self.information(versions)
        ruled = [
            Ask(
                kind="rule",
                rule=found.rule,
                reason=(
                    f"{change.path}:{found.span.start.line} - "
                    f"{found.rule}: {found.message}"
                ),
            )
            for found in findings
        ]
        sorted_ = self.sorted(
            [
                *always,
                *(ask for ask in design if not (covered and ask.covered())),
                *ruled,
            ],
            level,
        )
        return Judgement(
            path=change.path,
            role=self.roles.role(change.path),
            outcome="ask" if sorted_.held else "allow",
            asks=sorted_.held,
            flags=sorted_.flagged,
            findings=findings,
            untouched=untouched,
            information=information,
            removed=removed,
        )

    def lup_findings(self, path: Path, versions: Versions) -> list[Finding]:
        """Return lup's findings once `ignore`s apply, and the directives' problems.

        A problem `lup-dev rules fix` removes, an unused `ignore`, isn't among
        them: the session landing the work removes it, as they apply ruff's safe
        fixes.
        """
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
            if not problem.fixable
        ]
        kept = [found for found in self.kept(versions) if found.owner == "lup"]
        return [*kept, *problems]

    def design(self, change: Change, versions: Versions) -> list[Ask]:
        """List the design asks of a production change: created, whole, public API."""
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
            Ask(
                kind="public-api",
                reason=f"{change.path} {each.describe()}",
                api=each,
            )
            for each in api
        ]
        return [*new, *whole, *public]

    def suppressions(self, path: Path, versions: Versions) -> list[Ask]:
        """List an ask for each `# lup: ignore` the change adds, on its line."""
        if versions.after is None:
            return []
        before = versions.before.directives if versions.before else []
        return [
            Ask(
                kind="ignore",
                reason=f"adds `# lup: {added.identity().text}` to {path}",
                line=added.line,
            )
            for added in added_suppressions(before, versions.after.directives)
        ]
