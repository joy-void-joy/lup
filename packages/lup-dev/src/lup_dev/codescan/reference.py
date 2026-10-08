"""`docs/rules.md`: lup's rules for people, compiled from the engine's rule table.

It's the one generated file lup commits (`docs/judging-writes.md`, *How a rule is
declared*). `lup-dev rules docs` writes it, and a test in the gate compiles it again
and fails when the committed copy is stale.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lup_dev.codescan.contract import Rule

HEADER = [
    (
        "<!-- Generated from `packages/lup-dev/src/lup_dev/catalog/rules.ts` by "
        "`lup-dev rules docs`. Edit the table, not this file. -->"
    ),
    "",
    "# lup's rules",
    "",
    (
        "Each rule names the mistake it prevents and where it steers instead, and "
        "shows code it flags, the same code done the steer's way, and near misses it "
        "leaves alone. The examples are the rules' specification: the engine's tests "
        "run every one. How a rule is declared, and why, is in "
        "`docs/judging-writes.md`; the conventions the rules enforce are in "
        "`docs/conventions.md`."
    ),
    "",
    (
        'To keep one finding, write `# lup: ignore("<rule>", why="<reason>")` on its '
        "line or alone on the line above; adding one asks the operator."
    ),
]
"""The reference's opening, before its rules."""


def reference(rules: list[Rule]) -> str:
    """Compile the reference to `rules`, as Markdown."""

    def block(code: str) -> list[str]:
        return ["```python", *code.splitlines(), "```", ""]

    def section(rule: Rule) -> list[str]:
        flags = [
            line
            for flagged in rule.examples.flags
            for line in [
                *block(flagged.code),
                "Done the steer's way:",
                "",
                *block(flagged.rewritten),
            ]
        ]
        passes = [line for code in rule.examples.passes for line in block(code)]
        return [
            "",
            f"## `{rule.id}`",
            "",
            rule.mistake,
            "",
            f"**Steer:** {rule.steer}",
            "",
            "**Flags:**",
            "",
            *flags,
            *(["**Leaves alone:**", "", *passes] if passes else []),
        ]

    lines = [*HEADER, *(line for rule in rules for line in section(rule))]
    return "\n".join(lines).rstrip() + "\n"
