"""`CodeRules`: which of lup's code rules run, and where one is lifted."""

from lup_dev.declaration.kinds import Exemptions, Rules
from lup_dev.declaration.module import Module
from lup_dev.declaration.requirements import Requirement


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
        )
    ]

    rules: Rules = Rules.default()
    """lup's default rules, which the engine resolves."""
    exempt: Exemptions = Exemptions()
    """Rules lifted from some paths, each with its reason: none unless the project
    says."""
