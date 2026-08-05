"""Generate the checked-in Lup rule reference from the canonical rule registry."""

import html
from pathlib import Path

from lup.codescan.registry import RegisteredRule, all_rules
from lup.harness.banner import GeneratedBanner
from lup.harness.materialization import write_generated_file
from lup.harness.models import Artifact
from lup.workspace.paths import project_root


def markdown_cell(value: str) -> str:
    """Escape generated text for one Markdown table cell."""
    return html.escape(value).translate(str.maketrans({"|": "&#124;", "\n": " "}))


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
        lines = [
            "| Rule id | Family | Scope | Matching example | Diagnostic | Defined in |",
            "|---|---|---|---|---|---|",
            *[
                "| "
                f"`{row.id}` | {row.family} | {markdown_cell(row.scope)} | "
                f"<code>{markdown_cell(row.example)}</code> | "
                f"{markdown_cell(row.message)} | `{row.defined_in}` |"
                for row in rows
            ],
        ]
        return "\n".join(lines)

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
        "```python\n"
        "cache: dict[str, int] = {}  # lup: ignore[empty-collection] — mutable fold\n"
        "```\n\n"
        "## Structural rules\n\n"
        f"{table(structural)}\n\n"
        "## Edit anti-patterns\n\n"
        f"{table(anti_patterns)}\n\n"
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


RULE_REFERENCE_PATH = Path("docs/rules.md")
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
