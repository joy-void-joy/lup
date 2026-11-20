"""Every rule's examples, checked against the engine, pyright and ruff: the rules' specification, which a change to a rule keeps (`README.md` here, *The engine*).

Each rule's examples are code it flags, each rewritten the steer's way, and
near misses it leaves alone. They're written as a small package of their own
in a temporary directory, its pyright as strict as lup's, read with the
environment the check runs in, and checked in one run of the engine:
- a flagged example gets a finding of its rule and of no other of lup's;
- its rewrite gets none of lup's, pyright's or ruff's, ruff configured as the
  worktree configures it;
- a near miss gets none of its rule's.
"""

import tempfile
from pathlib import Path
from typing import Literal

from lup import Program
from lup.types import Model
from lup_code_rules.engine import Engine, Source
from lup_code_rules.reports import FileReport, Finding, RuleInfo
from lup_code_rules.ruff import ruff_findings


class Example(Model):
    """One example of a rule, as a file of the examples' package."""

    rule: str
    kind: Literal["flags", "rewritten", "passes"]
    index: int
    path: str
    """Its file, from the package's root."""
    code: str


class Unmet(Model):
    """An example that doesn't do what it's written to, and what it got."""

    example: Example
    got: list[Finding]

    def said(self) -> str:
        """Return a line saying which example it is, what it should have got, and what it got."""
        should = {
            "flags": f"a finding of `{self.example.rule}` and no other of lup's",
            "rewritten": "no finding of lup's, pyright's or ruff's",
            "passes": f"no finding of `{self.example.rule}`",
        }[self.example.kind]
        got = ", ".join(f"{each.owner} {each.rule}" for each in self.got) or "nothing"
        return f"`{self.example.rule}`'s {self.example.kind} example {self.example.index + 1} should get {should}, and got {got}"


class Examples(Model):
    """Checking every rule's examples, through the engine and ruff."""

    engine: Engine
    ruff: Program
    venv: Path
    """The environment the examples are read with: the one the check runs in."""
    config: Path
    """The worktree's `pyproject.toml`, which ruff reads the rewrites with."""
    unread: list[str] = [
        "reportMissingImports",
        "reportMissingModuleSource",
        "reportMissingTypeStubs",
    ]
    """pyright's findings about the environment rather than the code, which a
    rewrite leaves to whoever installs what it imports: `rich-progress`
    steers to a library this repository doesn't install."""
    docstring: str = '"""An example."""\n\n'
    """What each example's file starts with, so it's a module as ruff wants one."""
    pyproject: str = (
        "[tool.pyright]\n"
        'typeCheckingMode = "strict"\n'
        'pythonVersion = "3.15"\n'
        'include = ["example"]\n'
        'reportUnusedVariable = "warning"\n'
    )
    """The examples' package's pyright settings: as strict as lup's own."""

    async def unmet(self, rules: list[RuleInfo]) -> list[Unmet]:
        """Return every example of `rules` that doesn't do what it's written to, in the table's order."""
        written = [
            *(
                example
                for number, rule in enumerate(rules)
                for index, flagged in enumerate(rule.examples.flags)
                for example in [
                    self.example(rule, "flags", number, index, flagged.code),
                    self.example(rule, "rewritten", number, index, flagged.rewritten),
                ]
            ),
            *(
                self.example(rule, "passes", number, index, code)
                for number, rule in enumerate(rules)
                for index, code in enumerate(rule.examples.passes)
            ),
        ]
        with tempfile.TemporaryDirectory(prefix="lup-examples-") as scratch:
            root = self.laid_out(Path(scratch), written)
            reports = await self.engine.checked(
                root,
                self.venv,
                [rule.id for rule in rules],
                [Source(path=each.path) for each in written],
            )
            rewritten = [each.path for each in written if each.kind == "rewritten"]
            ruffs = await ruff_findings(self.ruff, root, rewritten, config=self.config)
        by_path = {report.path: report for report in reports}
        return [
            unmet
            for each in written
            if (unmet := self.checked(each, by_path[each.path], ruffs)) is not None
        ]

    def laid_out(self, scratch: Path, written: list[Example]) -> Path:
        """Write the examples' package in `scratch`, its pyright settings, its root and each example's file, and return where, links resolved, as the engine names its files."""
        root = scratch.resolve()
        (root / "pyproject.toml").write_text(self.pyproject)
        package = root / "example"
        package.mkdir()
        (package / "__init__.py").write_text('"""Examples."""\n')
        for each in written:
            (root / each.path).write_text(self.docstring + each.code)
        return root

    def example(
        self,
        rule: RuleInfo,
        kind: Literal["flags", "rewritten", "passes"],
        number: int,
        index: int,
        code: str,
    ) -> Example:
        """Return `rule`'s example of `kind`, the `index`th, as a file named by the rule's place in the table."""
        return Example(
            rule=rule.id,
            kind=kind,
            index=index,
            path=f"example/rule_{number}_{kind}_{index}.py",
            code=code,
        )

    def checked(
        self, example: Example, report: FileReport, ruffs: list[Finding]
    ) -> Unmet | None:
        """Return how `example` falls short, from its report and ruff's findings, or none where it does what it's written to."""
        found = report.findings
        lups = [each for each in found if each.owner == "lup"]
        match example.kind:
            case "flags":
                ruled = sorted(dict.fromkeys(each.rule for each in lups))
                met = ruled == [example.rule]
                got = lups
            case "rewritten":
                read = [each for each in found if each.rule not in self.unread]
                got = [*read, *(each for each in ruffs if each.path == example.path)]
                met = not got
            case "passes":
                got = [each for each in lups if each.rule == example.rule]
                met = not got
        return None if met else Unmet(example=example, got=got)
