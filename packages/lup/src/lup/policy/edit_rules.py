"""The shape an edit vocabulary takes, and its erasure into kernel rows.

The kernel decides one file change by walking gates — anti-patterns, protected
paths, review markers, whole-file writes, deletion, size — and each gate has a
verdict it reaches when nothing overrides it. Which verdict is *right* for a
project is a judgement about that project's toolchain, exactly as the shell
vocabulary is, so it arrives from outside. This module declares the shape that
judgement takes, and :func:`erase_edit_rules` flattens it into the
``EditRuleRow`` tuples the kernel interprets.

Two things differ from :mod:`lup.policy.shell_rules`, and both follow from
what an edit is.

A shell table *is* the policy: a command absent from it reaches no judgment.
An edit table is a set of **overrides layered over the kernel's own verdicts**,
because every gate already has an answer and a project usually wants to move
one of them, not restate all twelve. So an empty table decides exactly what
the kernel decided before this existed, and a project states only its
differences.

Matching is **last-match-wins**, the rule `.gitignore` uses: rules are read in
order and the last one that matches decides, so a broad statement is written
first and its exceptions after it. The alternative — most-specific-wins —
makes a table's meaning depend on a specificity ordering a reader has to
reconstruct, and two rules of equal specificity have no answer at all.

    EDIT_RULES = [
        EditRule(
            name="content-gates-stop-at-prose",
            gates=["full-write", "size"],
            effect="allow",
            reason="prose and data are reviewed in the diff, not at the hook",
        ),
        EditRule(
            name="python-source-is-still-read",
            gates=["full-write"],
            suffixes=[".py", ".pyi"],
            effect="ask",
            reason="full-file writes require approval",
        ),
    ]

Every axis is a list, and an empty one means "every value" rather than "no
value" — a rule constrains only what it names. A rule that states no ``effect``
moves only the threshold it carries, which is what lets a project widen the
size gate for one suffix without restating who decides it.
"""

from typing import Literal

from lup.policy.kernel.decision import DecisionEffect
from lup.policy.kernel.rows import EditOperation, EditRuleRow, PathRoleName
from lup.tables import SelectableRule

type EditGate = Literal[
    "acceptance-guard",
    "anti-pattern",
    "protected-path",
    "feedback-removed",
    "claim-removed",
    "feedback-added",
    "autonomous-full-write",
    "package-marker",
    "full-write",
    "pure-deletion",
    "autonomous-edit",
    "size",
    "small-edit",
]
"""Every verdict the edit kernel reaches, named so a project can move it.

Naming all of them — including the two that deny removing review feedback — is
deliberate. A gate a project cannot reach is a gate whose rightness this
library asserted on that project's behalf, and the ones worth asserting are
the ones a project would never want to move anyway. Leaving them nameable
costs nothing and keeps the escape hatch honest: a table that softens
``feedback-removed`` says so in a file somebody reviews, which is strictly
better than a fork that says it in the kernel.
"""


class EditRule(SelectableRule, frozen=True):
    """One class of edit a project has judged, layered over the ones before it.

    ``gates``, ``suffixes``, ``roles`` and ``operations`` are the axes a rule
    may constrain; each empty list means the rule is silent about that axis and
    matches every value of it. ``effect`` states who decides for the matched
    class, and ``maximum_added_lines`` moves the size gate's threshold for it.

    Both are optional and independent: a rule with an ``effect`` and no
    threshold moves the verdict alone, a rule with a threshold and no
    ``effect`` moves how much counts as small while leaving the verdict where
    it was, and a rule with neither matches nothing anyone reads — which
    :func:`erase_edit_rules` drops rather than erasing a row that can never
    decide.
    """

    name: str
    gates: list[EditGate] = []
    suffixes: list[str] = []
    roles: list[PathRoleName] = []
    operations: list[EditOperation] = []
    effect: DecisionEffect | None = None
    maximum_added_lines: int | None = None
    reason: str = ""

    def selection_id(self) -> str:
        return self.name

    def decides(self) -> bool:
        """Whether this rule states anything a gate would read."""
        return self.effect is not None or self.maximum_added_lines is not None


def erase_edit_rules(rules: list[EditRule]) -> list[EditRuleRow]:
    """Flatten the declared table into the kernel's primitive rows, in order.

    Order is the whole semantics here, so nothing is sorted, grouped, or
    de-duplicated: the rows reach the kernel in the sequence they were
    declared, and the kernel takes the last match. Rules that state neither an
    effect nor a threshold are dropped, because a row that cannot decide can
    only shadow one that could.
    """
    return [
        EditRuleRow(
            name=rule.name,
            gates=list(rule.gates),
            suffixes=[suffix.lower() for suffix in rule.suffixes],
            roles=list(rule.roles),
            operations=list(rule.operations),
            effect=rule.effect or "",
            maximum_added_lines=rule.maximum_added_lines,
            reason=rule.reason,
        )
        for rule in rules
        if rule.decides()
    ]
