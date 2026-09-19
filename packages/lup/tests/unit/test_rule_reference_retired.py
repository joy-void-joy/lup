"""The rule reference stays a valid artifact when a project retires every rule."""

from lup.devtools.dev.rules import rule_reference_artifact
from lup.harness.codescan.common import RuleSelection
from lup.harness.codescan.registry import all_rules


def test_a_reference_with_every_rule_retired_ends_in_one_newline() -> None:
    """With no refinement to list, the paragraph opener's own separator used
    to be all that ended the file, and the artifact tree refuses that."""
    everything = RuleSelection(retired=[rule.id for rule in all_rules()])
    body = rule_reference_artifact(everything).content
    assert body.endswith("\n")
    assert not body.endswith("\n\n")
