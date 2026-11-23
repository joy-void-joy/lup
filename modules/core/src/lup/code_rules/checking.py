"""What a check makes of a file: lup's findings, pyright's and ruff's together, those an `ignore` keeps set apart, and the `# lup:` comments that are wrong.

Every finding is kept the same way, whichever owns it: an `ignore` naming its
rule on the line it covers (`README.md` here, *`# lup:` comments*). So the
check is the one place deciding whether a finding stands, and the gate runs no
`ruff check` or `pyright` of its own, which would fail on a finding an `ignore`
keeps.
"""

from pathlib import PurePosixPath

from lup.code_rules.directives import Directive, Ignore, Malformed
from lup.code_rules.reports import (
    Category,
    Examples,
    FileReport,
    Finding,
    Position,
    RuleInfo,
    Span,
)
from lup.types import Model


class Kept(Model):
    """A finding an `ignore` keeps, with the `ignore` keeping it."""

    finding: Finding
    ignore: Ignore


class Checked(Model):
    """One file, checked: what stands, what's kept, and its `# lup:` comments."""

    path: str
    standing: list[Finding] = []
    """What isn't kept by an `ignore`, in the order of the file."""
    kept: list[Kept] = []
    directives: list[Directive] = []

    def failing(self) -> list[Finding]:
        """Return what fails the gate: everything standing but a heuristic's guesses, which are listed alone."""
        return [each for each in self.standing if each.category != "heuristic"]


class Exemptions(Model):
    """Where lup's rules for code don't read, as patterns from the worktree's root: tests, whose shapes are a test's own; and where its rules for tests do, tests and promises. pyright and ruff read every file."""

    patterns: list[str] = []
    tests: list[str] = []
    """Where lup's rules for tests read: a test's files and a module's
    promises."""

    def reads(self, rule: RuleInfo | None, path: str) -> bool:
        """Say whether lup's `rule` reads the file at `path`: a rule for code wherever it isn't exempt, a rule for tests where a test's or a promise's checks are; a rule the table doesn't hold, one a check makes itself, everywhere."""
        if rule is None:
            return True
        if rule.reads == "tests":
            return any(PurePosixPath(path).full_match(each) for each in self.tests)
        return not self.exempt(path)

    def exempt(self, path: str) -> bool:
        """Say whether lup's rules leave the file at `path` alone.

        >>> Exemptions(patterns=["**/tests/**"]).exempt("modules/core/tests/test_a.py")
        True
        >>> Exemptions(patterns=["**/tests/**"]).exempt("modules/core/src/lup/a.py")
        False
        """
        return any(PurePosixPath(path).full_match(each) for each in self.patterns)


UNUSED_IGNORE = RuleInfo(
    id="unused-ignore",
    mistake=(
        "An `ignore` that keeps nothing hides the next finding that comes on its "
        "line, unseen."
    ),
    steer="Remove it: `lup check --fix` does.",
    category="design",
    examples=Examples(),
)
"""The finding an `ignore` keeping nothing makes, which a check makes itself."""

MALFORMED_DIRECTIVE = RuleInfo(
    id="malformed-directive",
    mistake="A `# lup:` comment written wrong does nothing, and reads as if it did.",
    steer='Write it as its problem says, or as a note: `# lup: note("…")`.',
    category="design",
    examples=Examples(),
)
"""The finding a `# lup:` comment written wrong makes, which a check makes itself."""


class Table(Model):
    """lup's rules, by name: the engine's table, and the two a check makes itself of `# lup:` comments."""

    rules: dict[str, RuleInfo] = {}

    @classmethod
    def of(cls, rules: list[RuleInfo]) -> Table:
        """Return the table holding `rules`, beside the check's own."""
        return cls(
            rules={
                rule.id: rule for rule in [*rules, UNUSED_IGNORE, MALFORMED_DIRECTIVE]
            }
        )

    def engines(self) -> list[str]:
        """Return the rules the engine's table holds, by name, without the check's own."""
        own = [UNUSED_IGNORE.id, MALFORMED_DIRECTIVE.id]
        return [each for each in self.rules if each not in own]

    def category(self, finding: Finding) -> Category:
        """Return when `finding` is told and whether it fails the gate: its rule's category for lup's rules, a design's for pyright's and ruff's."""
        rule = self.rules.get(finding.rule)
        return rule.category if finding.owner == "lup" and rule else "design"


class Settling(Model):
    """What settling a file's findings reads: lup's rules, where they don't read, and which of ruff's repeat pyright's."""

    table: Table
    exemptions: Exemptions
    duplicated: list[str] = ["F821"]
    """ruff's codes repeating a pyright finding on the same name, told once,
    as pyright's: an undefined name."""

    def settled(self, report: FileReport, ruffs: list[Finding]) -> Checked:
        """Return the file `report` reports on, with `ruffs` beside its findings, settled: each finding categorised, those an `ignore` keeps set apart, and what's wrong with its `# lup:` comments found.

        A file the exemptions cover gets none of lup's rules for code's
        findings, and only a test's or a promise's file its rules for tests'. An
        `ignore` that keeps nothing is itself a finding, `unused-ignore`, which
        the gate's `--fix` removes; a malformed comment is
        `malformed-directive`. pyright's unused import is left out where
        ruff's, which its safe fix removes, is on the same line.
        """
        found = [
            each.model_copy(update={"category": self.table.category(each)})
            for each in [*report.findings, *ruffs]
            if (
                each.owner != "lup"
                or self.exemptions.reads(self.table.rules.get(each.rule), report.path)
            )
            and each.rule not in self.duplicated
        ]
        fixed = [
            each.span.start.line
            for each in found
            if each.rule == "F401" and each.fixable
        ]
        found = [
            each
            for each in found
            if not (each.rule == "reportUnusedImport" and each.span.start.line in fixed)
        ]
        ignores = [each for each in report.directives if isinstance(each, Ignore)]

        def keeping(finding: Finding) -> Ignore | None:
            """Return the `ignore` keeping `finding`, or none where none does."""
            return next(
                (
                    each
                    for each in ignores
                    if each.rule == finding.rule
                    and each.covers == finding.span.start.line
                ),
                None,
            )

        kept = [
            Kept(finding=each, ignore=ignore)
            for each in found
            if (ignore := keeping(each)) is not None
        ]
        used = [each.ignore for each in kept]
        problems = [
            *(unused(report.path, each) for each in ignores if each not in used),
            *(
                malformed(report.path, each)
                for each in report.directives
                if isinstance(each, Malformed)
            ),
        ]
        standing = sorted(
            [*(each for each in found if keeping(each) is None), *problems],
            key=lambda each: (each.span.start.line, each.span.start.column),
        )
        return Checked(
            path=report.path,
            standing=standing,
            kept=kept,
            directives=report.directives,
        )


def unused(path: str, ignore: Ignore) -> Finding:
    """Return the finding an `ignore` keeping nothing makes: fixable, since the gate's `--fix` removes it."""
    at = Position(line=ignore.line, column=ignore.column)
    detail = f"keeps no finding of `{ignore.rule}` on line {ignore.covers}"
    return Finding(
        path=path,
        span=Span(start=at, end=at),
        owner="lup",
        rule=UNUSED_IGNORE.id,
        message=f"{detail}. {UNUSED_IGNORE.mistake}",
        steer=UNUSED_IGNORE.steer,
        detail=detail,
        fixable=True,
    )


def malformed(path: str, comment: Malformed) -> Finding:
    """Return the finding a `# lup:` comment written wrong makes."""
    at = Position(line=comment.line, column=comment.column)
    return Finding(
        path=path,
        span=Span(start=at, end=at),
        owner="lup",
        rule=MALFORMED_DIRECTIVE.id,
        message=f"{comment.problem}. {MALFORMED_DIRECTIVE.mistake}",
        steer=MALFORMED_DIRECTIVE.steer,
        detail=comment.problem,
    )
