"""Generate the checked-in Lup rule reference from the canonical rule registry."""

from pathlib import Path

from lup.codescan.common import RuleStrength
from lup.codescan.registry import RULE_REFERENCE, RegisteredRule, all_rules
from lup.harness.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.markdown import MarkdownTable, cell, code
from lup.workspace.paths import project_root


def suppression_cell(strength: RuleStrength) -> str:
    """What a strength offers a reader who has just been denied by a rule."""
    match strength:
        case "soft":
            return "typed directive"
        case "strong":
            return "**refused**"


def example_cell(value: str) -> str:
    """A rule's matching shape, marked as code that may itself hold backticks."""
    return f"<code>{cell(value)}</code>"


def render_rule_reference() -> str:
    """Render every executable Lup rule and typed-suppression convention."""
    rules = all_rules()
    structural = sorted(
        (rule for rule in rules if rule.family != "anti-pattern"),
        key=lambda item: item.id,
    )
    anti_patterns = sorted(
        (rule for rule in rules if rule.family == "anti-pattern"),
        key=lambda item: (item.scope, item.id),
    )

    def table(rows: list[RegisteredRule]) -> str:
        return MarkdownTable(
            headers=[
                "Rule id",
                "Family",
                "Scope",
                "Matching example",
                "Diagnostic",
                "Suppression",
                "Defined in",
            ],
            rows=[
                [
                    code(row.id),
                    row.family,
                    cell(row.scope),
                    example_cell(row.example),
                    cell(row.message),
                    suppression_cell(row.strength),
                    code(row.defined_in),
                ]
                for row in rows
            ],
        ).render()

    refined = [rule for rule in rules if rule.refinement]
    refinements = "\n\n".join(
        f"### `{rule.id}`\n\n{rule.refinement}" for rule in refined
    )

    return (
        "# Lup rule reference\n\n"
        "Every executable Lup rule family — anti-pattern, boundary, spelling, and "
        "architecture rules — is indexed here from `lup.codescan.registry`, with the "
        "module that defines and enforces each rule. An edit-hook denial cites its "
        "rule id and this reference. Lup rules enforce repository-specific "
        "architecture and editing conventions; Ruff remains the source of standard "
        "Python diagnostics. The matching examples for anti-patterns are their "
        "canonical regular-expression shapes, so this reference cannot drift from "
        "the edit hook or repository auditor.\n\n"
        "## Typed suppressions\n\n"
        "Suppress one deliberate site with `# lup: ignore[rule-id]` and a reason. "
        "Comma-separated ids cover a line that intentionally matches several rules. "
        "A typed directive in the first ten lines applies file-wide. Bare "
        "`# lup: ignore` remains parseable but is reported as untyped; a stale typed "
        "directive is blocking. `# noqa`, `# type: ignore`, and `# pyright: ignore` "
        "are separate forbidden shapes.\n\n"
        "The **Suppression** column says whether a directive reaches a rule at all. "
        "Most are soft: they name a shape that is usually wrong and occasionally the "
        "only thing that works, so a typed directive is a reasoned exception and the "
        "audit grades it. A rule marked **refused** is strong — its replacement is "
        "right every time, which leaves a directive nothing to express but a decision "
        "to keep the defect. Those rules ignore every directive, report the violation "
        "anyway, and report the directive itself as spurious; the only way past one is "
        "to write the replacement its diagnostic names.\n\n"
        "```python\n"
        "cache: dict[str, int] = {}  # lup: ignore[empty-collection] — mutable fold\n"
        "```\n\n"
        "## Structural rules\n\n"
        f"{table(structural)}\n"
        "## Edit anti-patterns\n\n"
        f"{table(anti_patterns)}\n"
        "## Audit-side refinements\n\n"
        "The edit hook sees a fragment of a proposed edit: no parse tree, no "
        "types, and a hermetic kernel that may not reach a type checker. So it "
        "decides on the spelling alone, and every rule above means exactly its "
        "matching example there. The whole-file audit reads finished source and "
        "resolves what a matched name refers to through the type oracle in "
        "`lup.codescan.oracle`, so the rules below decide more narrowly in "
        "`lup-devtools dev check` than they do at edit time — a hook denial you "
        "believe is wrong is answered by the audit, which reports the "
        "declaration that settled it. Where the oracle is unavailable the audit "
        "falls back to the hook's broad verdict, and a `# lup: ignore` left "
        "guarding a refuted line is reported as a dead directive.\n\n"
        f"{refinements}\n"
    )


RULE_REFERENCE_PATH = Path(RULE_REFERENCE)
"""Where this writes the reference, taken from the path deny messages cite so
the two cannot name different files."""

# lup: ignore[constant-declaration] — the command a reader types, whose words
# are the CLI's own rather than a preference this module holds
RULE_REFERENCE_COMMAND = "uv run lup-devtools dev rules"


def rule_reference_artifact() -> Artifact:
    """The rule reference as one artifact, gated like any other generated file."""
    return Artifact.generated(
        path=RULE_REFERENCE_PATH,
        body=render_rule_reference(),
        semantic_id="docs.rules",
        banner=GeneratedBanner(source=__name__, command=RULE_REFERENCE_COMMAND),
    )


def write_rule_reference(root: Path | None = None, *, check: bool = False) -> Path:
    """Write or verify the generated rule reference."""
    return write_generated_file(
        rule_reference_artifact(),
        root or project_root(),
        RULE_REFERENCE_COMMAND,
        check=check,
    )
