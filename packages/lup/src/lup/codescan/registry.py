# lup: ignore[native-spelling]
# The rule index necessarily documents the spellings other rules audit.
"""One index over every Lup rule family for discovery and the rule reference.

A rule id met in a `# lup: ignore[...]` directive, a hook denial, or an
auditor finding resolves here: every family — anti-pattern, boundary,
spelling, architecture — is listed with its scope, diagnostic, and the module
that defines and enforces it. `uv run lup-devtools dev rules` renders this
registry into the checked-in `docs/rules.md` reference that deny messages
point at, so no rule is discoverable only through the scanner that owns it.

A rule the typed grammar refines carries that refinement on its card, because
the reference is where the two surfaces are reconciled: the edit hook decides
on the spelling alone and the whole-file audit may decide otherwise once a
type oracle has resolved what the spelling refers to.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

import lup.codescan.antipatterns as antipatterns
import lup.codescan.boundaries as boundaries
import lup.codescan.capabilities as capabilities
import lup.codescan.dispatch as dispatch
import lup.codescan.grammar as grammar
import lup.codescan.portable as portable

type RuleFamily = Literal["anti-pattern", "boundary", "spelling", "architecture"]

RULE_REFERENCE = "docs/rules.md"
"""Repository-relative path of the generated reference deny messages cite."""


class RegisteredRule(BaseModel):
    """One rule's discovery card: identity, family, diagnostic, and home.

    ``refinement`` is empty for a rule that decides the same way everywhere.
    Where it is set, the edit hook's verdict is the broad one the ``example``
    shows and the whole-file audit narrows it — the card says how, so a
    contributor who meets a denial the repository sweep does not report can
    tell which surface is speaking.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    family: RuleFamily
    scope: str
    example: str
    message: str
    defined_in: str
    refinement: str = ""


# lup: ignore[library-default] — one card per rule the library's own scanners define
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
        id=dispatch.RULE_ID,
        family="architecture",
        scope="Python architecture",
        example="if isinstance(part, TextPart): ...",
        message=(
            "A union we declare answers through its members: the base names the "
            "operation and each variant answers or declines it. Branching on the "
            "variant's own type — isinstance, a case arm, an assert_never net — "
            "leaves a filter that goes stale the moment a variant is added. "
            "Narrowing untyped data at a boundary is the different case and is "
            "not reported: the rule fires only on project classes that inherit "
            "pydantic.BaseModel."
        ),
        defined_in=dispatch.__name__,
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
        id=portable.RULE_ID,
        family="spelling",
        scope="Portable harness declarations",
        example='models.TextPart(text="Edit `.claude/settings.json`")',
        message=(
            "Prose every native tree renders names no platform: the vocabulary is "
            "whatever the adapters spell, so a location, product, or tool a runtime "
            "can spell reaches prose through a typed part instead."
        ),
        defined_in=portable.__name__,
    ),
    RegisteredRule(
        id=boundaries.LIBRARY_DEFAULT_RULE_ID,
        family="boundary",
        scope="Neutral library modules",
        example='READ_ONLY_COMMANDS = ("ls", "cat", "grep")',
        message=(
            "A data table a library declares is a choice made for every adopter: it "
            "reaches them as an overridable default — a parameter default, a pydantic "
            "field default, or the sentinel a mutable default is written as — so they "
            "replace the vocabulary instead of editing the library. Suppress only a "
            "canonical table, whose value is fixed outside this repository."
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


def anti_pattern_rules(
    rules: antipatterns.AntiPatternSet | None = None,
) -> list[RegisteredRule]:
    """Project every anti-pattern rule into its registry card."""
    declared = rules or antipatterns.AntiPatternSet()
    refined = {rule.id: rule.refinement for rule in grammar.GRAMMAR_RULES}
    return [
        RegisteredRule(
            id=rule.id,
            family="anti-pattern",
            scope=scope,
            example=rule.pattern.pattern,
            message=rule.message,
            defined_in=antipatterns.__name__,
            refinement=refined[rule.id] if rule.id in refined else "",
        )
        for scope, scoped in (
            ("Python", declared.python),
            ("TypeScript", declared.typescript),
        )
        for rule in scoped
    ]


def all_rules(
    rules: antipatterns.AntiPatternSet | None = None,
) -> list[RegisteredRule]:
    """Every registered rule across all families, structural rules first."""
    return [*STRUCTURAL_RULES, *anti_pattern_rules(rules)]
