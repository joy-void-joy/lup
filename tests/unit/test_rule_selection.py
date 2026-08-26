"""A project's rule selection, and the surfaces it has to reach.

The failure this guards against is a seam that exists in one place and is
quietly not honoured in another: the promise that a project may retire a rule
is only worth anything if the sweep, the compiled plugin, and the generated
reference all stop naming it together. Each is pinned separately here, because
each was reached by a different call path and any one of them could be added
back without the others noticing.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import lup.devtools.dev.rules as rules_mod
import lup_template.devtools.harness.catalog as catalog
from lup.providers.claude.harness import ClaudeSpellings
from lup.providers.harness import claude_prompt_renderer
from lup.harness.codescan.antipatterns import (
    DOCUMENT_IN_HAND,
    AntiPatternSet,
    antipattern_set_for,
)
from lup.harness.codescan.common import RuleSelection
from lup.harness.codescan.registry import all_rules
from lup.devtools.dev.app import create_dev_app
from lup.devtools.dev.rules import RULE_REFERENCE_PATH, rule_reference_document
from lup_template.devtools.dev.app import declared as declared_here
from lup_template.devtools.harness.composition import TARGETS

RETIRED = RuleSelection(retired=["model-config", "default-factory"])


def test_a_retired_rule_leaves_the_table_the_sweep_reads() -> None:
    kept = AntiPatternSet().selected(RETIRED)

    assert [rule.id for rule in kept.python if rule.id in set(RETIRED.retired)] == []
    assert any(rule.id == "import-re" for rule in kept.python)


def test_selecting_nothing_keeps_every_rule_the_library_ships() -> None:
    """The default has to be the whole table, or adopting the seam changes it."""
    whole = AntiPatternSet()

    assert whole.selected(RuleSelection()).python == whole.python


def test_a_retired_rule_leaves_the_compiled_plugin() -> None:
    """The hook is compiled separately from the sweep and drifted before."""
    compiled = antipattern_set_for(
        ClaudeSpellings().read_document(DOCUMENT_IN_HAND), RETIRED
    )

    assert [
        rule.id for rule in compiled.python if rule.id in set(RETIRED.retired)
    ] == []


def test_a_retired_rule_leaves_the_generated_reference() -> None:
    """A page documenting a rule nothing enforces is worse than no page."""
    cards = {rule.id for rule in all_rules(selection=RETIRED)}

    assert cards.isdisjoint(RETIRED.retired)
    assert "constant-declaration" in cards


def test_the_reference_document_renders_from_the_selection() -> None:
    rendered = claude_prompt_renderer().render(rule_reference_document(RETIRED))

    assert "`model-config`" not in rendered
    assert "`constant-declaration`" in rendered


def test_the_documented_command_writes_the_reference_this_repository_is_held_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fourth call path, and the one that was quietly not honouring it.

    `dev rules` rendered the whole library table instead of the selection,
    so a project that retired a rule got a generated page still documenting
    it — and its own drift check, which does read the selection, then rejected
    the file the documented command had just written. Neither said which was
    wrong, and the page claimed a rule the gate there does not enforce.
    """
    monkeypatch.setattr(rules_mod, "project_root", lambda: tmp_path)
    retiring = declared_here().model_copy(
        update={
            "hooks": catalog.declared_hook_set().model_copy(update={"rules": RETIRED})
        }
    )
    app = create_dev_app(
        declared=lambda: retiring,
        native_targets=TARGETS,
        repository_writers=[],
        relocate_roots=[],
    )

    result = CliRunner().invoke(app, ["rules"])

    assert result.exit_code == 0, result.output
    written = (tmp_path / RULE_REFERENCE_PATH).read_text(encoding="utf-8")
    assert "`model-config`" not in written
    assert "`constant-declaration`" in written


def test_a_structural_rule_can_be_retired_too() -> None:
    """Structural rules reach the sweep by a path the anti-pattern table misses."""
    cards = {
        rule.id
        for rule in all_rules(selection=RuleSelection(retired=["model-free-function"]))
    }

    assert "model-free-function" not in cards
    assert "abc-capability" in cards
