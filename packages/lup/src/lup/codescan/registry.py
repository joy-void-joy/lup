# lup: ignore[native-spelling]
# The rule index necessarily documents the spellings other rules audit.
"""One index over every Lup rule family for discovery and the rule reference.

A rule id met in a `# lup: ignore[...]` directive, a hook denial, or an
auditor finding resolves here: every family — anti-pattern, boundary,
spelling, architecture — is listed with its scope, diagnostic, and the module
that defines and enforces it. `uv run lup-devtools dev rules` renders this
registry into the checked-in `docs/rules.md` reference that deny messages
point at, so no rule is discoverable only through the scanner that owns it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

import lup.codescan.antipatterns as antipatterns
import lup.codescan.boundaries as boundaries
import lup.codescan.capabilities as capabilities

type RuleFamily = Literal["anti-pattern", "boundary", "spelling", "architecture"]

RULE_REFERENCE = "docs/rules.md"
"""Repository-relative path of the generated reference deny messages cite."""


class RegisteredRule(BaseModel):
    """One rule's discovery card: identity, family, diagnostic, and home."""

    model_config = ConfigDict(frozen=True)

    id: str
    family: RuleFamily
    scope: str
    example: str
    message: str
    defined_in: str


STRUCTURAL_RULES: list[RegisteredRule] = [
    RegisteredRule(
        id=capabilities.RULE_ID,
        family="architecture",
        scope="Python architecture",
        example="class Combined(Reader, Writer): ...",
        message=(
            "Capability ABCs stay independently constructible and cohesive; "
            "implementations do not inherit multiple capabilities or reusable behavior."
        ),
        defined_in=capabilities.__name__,
    ),
    RegisteredRule(
        id=boundaries.RULE_ID,
        family="boundary",
        scope="Neutral Python modules",
        example="from lup.adapters.codex.runtime import CodexSessionConfig",
        message=(
            "Concrete adapter imports belong only in adapters, tests, examples, and "
            "named application composition roots."
        ),
        defined_in=boundaries.__name__,
    ),
    RegisteredRule(
        id=boundaries.NATIVE_SPELLING_RULE_ID,
        family="spelling",
        scope="Neutral Python modules",
        example='instruction = "$lup:commit"',
        message=(
            "Provider command, event, environment, and manifest spellings stay at "
            "the native adapter boundary."
        ),
        defined_in=boundaries.__name__,
    ),
    RegisteredRule(
        id=boundaries.KERNEL_IMPORT_RULE_ID,
        family="boundary",
        scope="Policy kernel",
        example="from pydantic import BaseModel",
        message=(
            "The copied hook kernel imports only its pinned standard-library allowlist."
        ),
        defined_in=boundaries.__name__,
    ),
]
"""Project-shape rules enforced by the AST scanners, one card per rule id."""


def anti_pattern_rules() -> list[RegisteredRule]:
    """Project every anti-pattern rule into its registry card."""
    return [
        RegisteredRule(
            id=rule.id,
            family="anti-pattern",
            scope=scope,
            example=rule.pattern.pattern,
            message=rule.message,
            defined_in=antipatterns.__name__,
        )
        for scope, rules in (
            ("Python", antipatterns.PYTHON_ANTI_PATTERNS),
            ("TypeScript", antipatterns.TS_ANTI_PATTERNS),
        )
        for rule in rules
    ]


def all_rules() -> list[RegisteredRule]:
    """Every registered rule across all families, structural rules first."""
    return [*STRUCTURAL_RULES, *anti_pattern_rules()]
