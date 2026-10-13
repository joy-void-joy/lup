"""`CodeRules`: which of lup's code rules run, and where one is lifted."""

from functools import reduce
from pathlib import Path

from lup_dev.catalog.rules import DefaultRules, LeftOut
from lup_dev.declaration.kinds import Exemptions, Guidance, Rules, Section
from lup_dev.declaration.module import Module
from lup_dev.declaration.requirements import Requirement


def lup_default() -> Rules:
    """Return lup's default rules: every rule of its table but those it leaves out.

    Each one left out is a drop with its reason, so the overview shows why, and a
    rule a later release adds runs unless the catalog leaves it out too.

    >>> [operation.names for operation in lup_default().operations]
    [['runtime-mention']]
    """

    def without(rules: Rules, left: LeftOut) -> Rules:
        return rules.drop(left.rule, why=left.why)

    return reduce(without, DefaultRules().left_out, Rules.all())


class CodeRules(Module):
    """lup's code rules: which run, and the paths a rule is lifted from, with why."""

    name = "code-rules"
    requirements = [
        Requirement(
            tool="node",
            version=">=22.18",
            probe=["node", "-p", "process.versions.node"],
            why="runs the rule engine",
            install="https://nodejs.org/en/download",
            package="nodejs",
        )
    ]

    rules: Rules = lup_default()
    """lup's default rules, which `Rules.default()` names here and the engine
    resolves: every rule of its table but those `lup_dev.catalog.rules` leaves out."""
    exempt: Exemptions = Exemptions()
    """Rules lifted from some paths, each with its reason: none unless the project
    says."""
    guidance: Guidance = Guidance.of(
        Section(
            name="code-rules",
            package="lup_dev.declaration.modules",
            path=Path("guidance/code_rules.md"),
        )
    )
    """What a rule is for, what a refusal says and how it's answered, and the
    `# lup:` comments."""
