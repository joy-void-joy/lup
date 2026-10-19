"""One judgement: each row of the allow table, and what decides it."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import (
    CodeRules,
    Core,
    Exemption,
    Exemptions,
    Modules,
    Paths,
    Project,
    Rules,
)
from lup_dev.declaration.resolve import Declaration
from lup_dev.inbox.store import ApiChanged, Asked, Found, Reading, Taken
from lup_dev.policy.judge import (
    Change,
    EngineError,
    Judge,
    Judgement,
    touched_lines,
)
from lup_dev.policy.report import information
from lup_dev.policy.roles import Roles
from lup_dev.private.withheld import Held, Withheld

if TYPE_CHECKING:
    from conftest import Kit


def excluding(*patterns: str) -> Project:
    paths = Paths().add(excluded=list(patterns))
    return Project(modules=Modules.default().edit(Core(paths=paths)))


CORE = (
    '"""Core."""\n\n\n'
    "class Client:\n"
    "    def ask(self, prompt: str) -> str:\n"
    "        return prompt\n\n\n"
    "def helper(x: int) -> int:\n"
    "    return x\n"
)


EVERY_HELD = Project(
    held=["protected", "operator", "new-file", "whole-file", "public-api", "ignore"],
    flagged=[],
)
"""Every kind of change held, so a test reads what each change asks."""


class Judging:
    """Judges one change at a time with the kit's fake engine and linter."""

    def __init__(self, kit: Kit, root: Path) -> None:
        self.kit = kit
        self.root = root

    def __call__(
        self,
        change: Change,
        *,
        approved: list[Path] | None = None,
        conditions: list[str] | None = None,
        project: Project | None = None,
        holding: bool = False,
        withheld: Withheld | None = None,
    ) -> Judgement:
        judging = Judge(
            root=self.root,
            roles=Roles(
                root=self.root, declaration=Declaration.of(project or EVERY_HELD)
            ),
            checker=self.kit.engine,
            linter=self.kit.linter,
            conditions=conditions,
            approved=approved or [],
            holding=holding,
            withheld=withheld,
        )
        [judgement] = judging.judge([change])
        return judgement


@pytest.fixture
def judge(kit: Kit, tmp_path: Path) -> Judging:
    return Judging(kit, tmp_path)


def edit(
    path: str,
    before: str | None,
    after: str | None,
    *,
    baseline: str | None = "same",
    whole: bool = False,
) -> Change:
    return Change(
        path=Path(path),
        before=before,
        after=after,
        baseline=before if baseline == "same" else baseline,
        whole=whole,
    )


def test_tests_scratch_docs_and_data_are_allowed_at_any_size(judge: Judging) -> None:
    big = "x = 1  # BAD tuple-shape\n" * 500
    for path in ["tests/test_a.py", "tmp/a.py", "docs/a.md", "data/a.json"]:
        judgement = judge(edit(path, None, big))
        assert judgement.outcome == "allow", path
        assert judgement.findings == []


def test_the_operators_documents_ask(judge: Judging) -> None:
    judgement = judge(edit("DESIGN.md", "a\n", "b\n"))
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["operator"]


def test_a_protected_path_asks(judge: Judging) -> None:
    judgement = judge(edit("pyproject.toml", "a\n", "b\n"))
    assert judgement.outcome == "ask"
    # Named from the worktree's root: the agent reads it under the file's absolute path, the operator beside the file.
    assert (
        judgement.asks[0].reason
        == "pyproject.toml is a protected path (**/pyproject.toml)"
    )


PROTECTED = ".claude/hooks/check.py"


def test_a_clean_change_to_a_protected_module_is_ruled_and_still_asks(
    judge: Judging,
) -> None:
    after = CORE + "y: int = 'a'  # TYPE\n"
    judgement = judge(edit(PROTECTED, CORE, after))
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["protected"]
    assert judgement.role == "protected"
    assert [finding.owner for finding in judgement.information] == ["pyright"]


def test_a_finding_in_a_protected_module_is_told_and_the_change_still_asks(
    judge: Judging,
) -> None:
    after = CORE + "y = 2  # BAD regex\n"
    judgement = judge(edit(PROTECTED, CORE, after))
    assert judgement.outcome == "ask"
    assert [finding.rule for finding in judgement.findings] == ["regex"]
    assert [ask.kind for ask in judgement.asks] == ["protected"]
    assert judgement.reasons() == ["protected"]


def test_a_protected_module_asks_every_time_and_with_its_design_asks(
    judge: Judging,
) -> None:
    path = Path(PROTECTED)
    after = CORE + "\n\nclass Room:\n    pass\n"
    approved = judge(edit(PROTECTED, CORE, after), approved=[path])
    assert [ask.kind for ask in approved.asks] == ["protected"]
    fresh = judge(edit(PROTECTED, CORE, after))
    assert [ask.kind for ask in fresh.asks] == ["protected", "public-api"]
    created = judge(edit(PROTECTED, None, '"""New."""\n', baseline=None))
    assert [ask.kind for ask in created.asks] == ["protected", "new-file"]


def test_an_excluded_module_is_allowed_with_nothing_reported(judge: Judging) -> None:
    project = excluding("vendor/**")
    after = "x = 1  # BAD regex\ny: int = 'a'  # TYPE\nimport os  # RUFF F401\n"
    judgement = judge(
        edit("vendor/lib.py", None, after, baseline=None), project=project
    )
    assert judgement.outcome == "allow"
    assert judgement.reasons() == ["excluded"]
    assert judgement.findings == judgement.information == judgement.untouched == []


def test_an_excluded_protected_module_asks_without_its_findings(
    judge: Judging,
) -> None:
    project = excluding(".claude/hooks/**")
    judgement = judge(
        edit(PROTECTED, CORE, CORE + "y = 2  # BAD regex\n"), project=project
    )
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["protected"]
    assert judgement.findings == []


def test_an_exempt_rule_is_lifted_from_its_paths_alone(judge: Judging) -> None:
    lifted = Exemption(rule="regex", paths=["src/pkg/**"], why="a grammar")
    lifting = CodeRules(exempt=Exemptions().add(lifted))
    project = Project(modules=Modules.default().edit(lifting))
    after = CORE + "y = 2  # BAD regex\nz = 3  # BAD tuple-shape\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after), project=project)
    assert [found.rule for found in judgement.findings] == ["tuple-shape"]
    elsewhere = judge(edit("src/other.py", None, after, baseline=None), project=project)
    assert sorted(found.rule for found in elsewhere.findings) == [
        "regex",
        "tuple-shape",
    ]


def test_protected_files_that_arent_python_only_ask(judge: Judging) -> None:
    judgement = judge(edit(".claude/settings.json", "{}\n", "{} # BAD regex\n"))
    assert judgement.outcome == "ask"
    assert judgement.findings == []


def test_deleting_a_protected_path_asks_and_deleting_code_is_allowed(
    judge: Judging,
) -> None:
    assert judge(edit(".github/ci.yml", "a\n", None)).outcome == "ask"
    assert judge(edit("src/pkg/core.py", CORE, None)).outcome == "allow"


def test_a_finding_on_a_touched_line_is_told_and_the_write_allowed(
    judge: Judging,
) -> None:
    before = CORE + "y = 2  # BAD regex\n"
    after = before + "z = 3  # BAD tuple-shape\n"
    judgement = judge(edit("src/pkg/core.py", before, after))
    assert judgement.outcome == "allow"
    assert [finding.rule for finding in judgement.findings] == ["tuple-shape"]
    assert judgement.reasons() == ["tuple-shape"]
    assert [finding.rule for finding in judgement.untouched] == ["regex"]


def test_every_check_carries_the_declarations_rule_selection(
    judge: Judging, kit: Kit
) -> None:
    project = Project(
        modules=Modules.default().edit(CodeRules(rules=Rules().drop("regex")))
    )
    selected = Declaration.of(project).rules
    judge(edit("src/pkg/core.py", CORE, CORE + "z = 3\n"), project=project)
    assert len(kit.engine.selections) == 3  # after, before and the baseline
    assert all(each == selected for each in kit.engine.selections)
    [code_rules] = selected
    assert code_rules.module == "code-rules"
    assert [
        operation.names
        for operation in code_rules.rules.operations
        if operation.verb == "drop"
    ] == [["runtime-mention"], ["regex"]]


def test_findings_on_untouched_lines_are_told_apart(judge: Judging) -> None:
    before = CORE + "y = 2  # BAD regex\n"
    after = before.replace("return x", "return x + 1")
    judgement = judge(edit("src/pkg/core.py", before, after))
    assert judgement.outcome == "allow"
    assert [finding.rule for finding in judgement.untouched] == ["regex"]


def test_a_new_production_file_asks(judge: Judging) -> None:
    judgement = judge(edit("src/pkg/new.py", None, '"""New."""\n', baseline=None))
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["new-file"]


def test_every_line_of_a_new_file_is_touched(judge: Judging) -> None:
    judgement = judge(
        edit("src/pkg/new.py", None, "a = 1\nb = 2  # BAD regex\n", baseline=None)
    )
    assert [finding.rule for finding in judgement.findings] == ["regex"]


def test_writing_a_whole_existing_file_asks(judge: Judging) -> None:
    judgement = judge(edit("src/pkg/core.py", CORE, CORE + "\n", whole=True))
    assert [ask.kind for ask in judgement.asks] == ["whole-file"]


def test_a_new_class_asks(judge: Judging) -> None:
    after = CORE + "\n\nclass Room:\n    pass\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "ask"
    assert judgement.asks[0].reason == "src/pkg/core.py adds the class `Room`"


def test_a_changed_signature_of_a_definition_from_the_sessions_start_asks(
    judge: Judging,
) -> None:
    after = CORE.replace(
        "def helper(x: int) -> int", "def helper(x: int, y: int = 0) -> int"
    )
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert [ask.reason for ask in judgement.asks] == [
        "src/pkg/core.py changes the signature of `helper`"
    ]


def test_a_definition_created_this_session_changes_freely(judge: Judging) -> None:
    session_start = CORE
    before = CORE + "\n\ndef fresh(a: int) -> int:\n    return a\n"
    after = before.replace("def fresh(a: int)", "def fresh(a: int, b: int)")
    judgement = judge(edit("src/pkg/core.py", before, after, baseline=session_start))
    assert judgement.outcome == "allow"


def test_names_added_to_or_removed_from_a_package_root_ask(judge: Judging) -> None:
    init = '"""Pkg."""\n__all__ = ["Client"]\n'
    added = judge(
        edit(
            "src/pkg/__init__.py",
            init,
            init.replace('["Client"]', '["Client", "Room"]'),
        )
    )
    assert [ask.reason for ask in added.asks] == [
        "src/pkg/__init__.py adds `Room` to the package's root"
    ]
    removed = judge(edit("src/pkg/__init__.py", init, init.replace('["Client"]', "[]")))
    assert [ask.reason for ask in removed.asks] == [
        "src/pkg/__init__.py removes `Client` from the package's root"
    ]


def test_an_added_ignore_asks_naming_its_rule_and_reason(judge: Judging) -> None:
    after = (
        CORE
        + "y = (1, 2)  # BAD tuple-shape"
        + '  # lup: ignore("tuple-shape", why="sh takes tuples")\n'
    )
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "ask"
    assert judgement.asks[0].reason == (
        'adds `# lup: ignore("tuple-shape", why="sh takes tuples")` to src/pkg/core.py'
    )
    assert judgement.findings == []


def test_an_ignore_whose_rule_doesnt_fire_is_never_told(judge: Judging) -> None:
    after = CORE + 'y = 1  # lup: ignore("tuple-shape", why="nothing here")\n'
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "ask"
    assert judgement.findings == []
    assert judgement.untouched == []


def test_a_finding_beside_an_ask_is_told_and_the_change_still_asks(
    judge: Judging,
) -> None:
    judgement = judge(
        edit("src/pkg/new.py", None, "x = 1  # BAD regex\n", baseline=None)
    )
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["new-file"]
    assert [finding.rule for finding in judgement.findings] == ["regex"]


def test_an_approval_covers_the_paths_design_asks_but_not_its_suppressions(
    judge: Judging,
) -> None:
    path = Path("src/pkg/core.py")
    after = CORE + "\n\nclass Room:\n    pass\n"
    assert judge(edit(str(path), CORE, after), approved=[path]).outcome == "allow"
    ignored = (
        CORE + 'y = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
    )
    assert judge(edit(str(path), CORE, ignored), approved=[path]).outcome == "ask"


ONLY_PROTECTED = Project(held=["protected", "operator"], flagged=[])


def test_asking_only_about_protected_paths_allows_every_other_ask(
    judge: Judging,
) -> None:
    ignored = (
        CORE + 'y = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
    )
    changes = [
        edit("src/pkg/new.py", None, '"""New."""\n', baseline=None),
        edit("src/pkg/core.py", CORE, CORE + "\n", whole=True),
        edit("src/pkg/core.py", CORE, CORE + "\n\nclass Room:\n    pass\n"),
        edit("src/pkg/core.py", CORE, ignored),
    ]
    for change in changes:
        judgement = judge(change, project=ONLY_PROTECTED)
        assert judgement.outcome == "allow", change.path
        assert judgement.asks == []


def test_asking_only_about_protected_paths_still_asks_about_them(
    judge: Judging,
) -> None:
    config = judge(edit("pyproject.toml", "a\n", "b\n"), project=ONLY_PROTECTED)
    assert [ask.kind for ask in config.asks] == ["protected"]
    created = judge(
        edit(PROTECTED, None, '"""New."""\n', baseline=None), project=ONLY_PROTECTED
    )
    assert created.outcome == "ask"
    assert [ask.kind for ask in created.asks] == ["protected"]


def test_asking_only_about_protected_paths_still_asks_about_the_operators_documents(
    judge: Judging,
) -> None:
    for path in ["DESIGN.md", "AGENTS.md"]:
        judgement = judge(edit(path, "a\n", "b\n"), project=ONLY_PROTECTED)
        assert judgement.outcome == "ask", path
        assert [ask.kind for ask in judgement.asks] == ["operator"]


def test_asking_only_about_protected_paths_still_tells_a_finding(
    judge: Judging,
) -> None:
    judgement = judge(
        edit("src/pkg/new.py", None, "x = 1  # BAD regex\n", baseline=None),
        project=ONLY_PROTECTED,
    )
    assert judgement.outcome == "allow"
    assert [finding.rule for finding in judgement.findings] == ["regex"]


DESIGN_CHANGES = [
    edit("src/pkg/new.py", None, '"""New."""\n', baseline=None),
    edit("src/pkg/core.py", CORE, CORE + "\n", whole=True),
    edit("src/pkg/core.py", CORE, CORE + "\n\nclass Room:\n    pass\n"),
]


def test_by_default_a_change_of_design_is_flagged_and_lands(judge: Judging) -> None:
    for change, kind in zip(
        DESIGN_CHANGES, ["new-file", "whole-file", "public-api"], strict=True
    ):
        judgement = judge(change, project=Project())
        assert judgement.outcome == "allow", kind
        assert judgement.asks == []
        assert [ask.kind for ask in judgement.flags] == [kind]
        assert judgement.reasons() == [kind]


def test_by_default_protected_paths_documents_and_ignores_are_held(
    judge: Judging,
) -> None:
    ignored = (
        CORE + 'y = (1, 2)  # BAD tuple-shape  # lup: ignore("tuple-shape", why="sh")\n'
    )
    changes = {
        "protected": edit("pyproject.toml", "a\n", "b\n"),
        "operator": edit("DESIGN.md", "a\n", "b\n"),
        "ignore": edit("src/pkg/core.py", CORE, ignored),
    }
    for kind, change in changes.items():
        judgement = judge(change, project=Project())
        assert judgement.outcome == "ask", kind
        assert [ask.kind for ask in judgement.asks] == [kind]
        assert judgement.flags == []


def test_holding_each_flagged_write_holds_what_is_flagged(judge: Judging) -> None:
    for change in DESIGN_CHANGES:
        judgement = judge(change, project=Project(), holding=True)
        assert judgement.outcome == "ask", change.path
        assert judgement.flags == []
        assert len(judgement.asks) == 1


def test_a_rule_named_held_holds_its_finding_and_still_tells_it(
    judge: Judging,
) -> None:
    judgement = judge(
        edit("src/pkg/core.py", CORE, CORE + "x = 1  # BAD regex\n"),
        project=Project(held=["regex"], flagged=[]),
    )
    assert judgement.outcome == "ask"
    assert [ask.name() for ask in judgement.asks] == ["regex"]
    assert judgement.asks[0].reason.startswith("src/pkg/core.py:11 - regex")
    assert [finding.rule for finding in judgement.findings] == ["regex"]
    assert judgement.reasons() == ["regex"]


def test_a_rule_named_flagged_lands_and_is_flagged(judge: Judging) -> None:
    judgement = judge(
        edit("src/pkg/core.py", CORE, CORE + "x = 1  # BAD regex\n"),
        project=Project(held=[], flagged=["regex"]),
    )
    assert judgement.outcome == "allow"
    assert [ask.name() for ask in judgement.flags] == ["regex"]


def test_a_rule_named_on_an_untouched_line_neither_holds_nor_flags(
    judge: Judging,
) -> None:
    before = CORE + "x = 1  # BAD regex\n"
    judgement = judge(
        edit("src/pkg/core.py", before, before + "y = 2\n"),
        project=Project(held=["regex"], flagged=[]),
    )
    assert judgement.outcome == "allow"
    assert [finding.rule for finding in judgement.untouched] == ["regex"]


def test_a_rule_lups_rules_dont_name_fails_the_judgement(judge: Judging) -> None:
    with pytest.raises(EngineError, match=r"\['no-such-rule'\].*regex, tuple-shape"):
        judge(
            edit("src/pkg/core.py", CORE, CORE + "\n"),
            project=Project(held=["no-such-rule"]),
        )


def test_type_errors_and_ruffs_findings_are_information(judge: Judging) -> None:
    after = CORE + "y: int = 'a'  # TYPE\nimport os  # RUFF F401\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "allow"
    assert sorted(finding.owner for finding in judgement.information) == [
        "pyright",
        "ruff",
    ]


def test_a_finding_ruff_fixes_safely_isnt_reported(judge: Judging) -> None:
    after = CORE + "import os  # FIXABLE F401\nimport sys  # RUFF E711\n"
    for path in ["src/pkg/core.py", "tests/test_a.py"]:
        judgement = judge(edit(path, CORE, after))
        assert judgement.outcome == "allow", path
        assert [finding.rule for finding in judgement.information] == ["E711"], path


def test_an_ignore_naming_a_fixable_finding_is_still_used(judge: Judging) -> None:
    before = (
        CORE + 'import os  # FIXABLE F401  # lup: ignore("F401", why="re-exported")\n'
    )
    judgement = judge(edit("src/pkg/core.py", before, before + "z = 1\n"))
    assert judgement.outcome == "allow"
    assert judgement.untouched == []
    assert judgement.information == []


def test_ignore_applies_to_ruffs_findings_too(judge: Judging) -> None:
    before = CORE + 'import os  # RUFF F401  # lup: ignore("F401", why="re-exported")\n'
    after = before + "z = 1\n"
    judgement = judge(edit("src/pkg/core.py", before, after))
    assert judgement.information == []


def test_a_test_files_type_errors_are_information(judge: Judging) -> None:
    judgement = judge(
        edit("tests/test_a.py", None, "x: int = 'a'  # TYPE\n# BAD regex\n")
    )
    assert judgement.outcome == "allow"
    assert [finding.owner for finding in judgement.information] == ["pyright"]


def test_removing_a_note_present_at_the_sessions_start_is_allowed_and_reported(
    judge: Judging,
) -> None:
    start = CORE + "# lup: the retry count is the provider's limit\n"
    judgement = judge(edit("src/pkg/core.py", start, CORE, baseline=start))
    assert judgement.outcome == "allow"
    assert [note.text for note in judgement.removed] == [
        "the retry count is the provider's limit"
    ]


def test_removing_a_note_added_this_session_isnt_reported(judge: Judging) -> None:
    before = CORE + "# lup: mine\n"
    judgement = judge(edit("src/pkg/core.py", before, CORE, baseline=CORE))
    assert judgement.removed == []


def test_a_defer_naming_an_undeclared_condition_is_told(judge: Judging) -> None:
    after = CORE + 'x = 1  # lup: defer(when=ready, why="wait")\n'
    assert (
        judge(edit("src/pkg/core.py", CORE, after), conditions=["ready"]).outcome
        == "allow"
    )
    judgement = judge(edit("src/pkg/core.py", CORE, after), conditions=["other"])
    assert [finding.rule for finding in judgement.findings] == ["defer-condition"]


# The reading the review opens a file by.


TAKEN: list[tuple[str, int, Taken]] = [
    ("regex", 11, "held"),
    ("tuple-shape", 12, "flagged"),
    ("string-split", 13, "told"),
]
"""Each finding the reading test's change makes: its rule, its line, and how the
declaration there takes it."""


def test_a_reading_says_what_a_file_asks_held_or_flagged_each_on_its_line(
    judge: Judging,
) -> None:
    project = Project(
        held=["protected", "operator", "ignore", "regex"],
        flagged=["new-file", "whole-file", "public-api", "tuple-shape"],
    )
    after = (
        CORE.replace("def ask(self, prompt: str)", "def ask(self, prompt: int)")
        + "y = 2  # BAD regex\n"
        + "z = 3  # BAD tuple-shape\n"
        + "w = 4  # BAD string-split\n"
        + "\n\n"
        + "class Room:\n"
        + '    # lup: ignore("string-split", why="a fixed format")\n'
        + "    pass\n"
    )
    reading = judge(edit("src/pkg/core.py", CORE, after), project=project).reading()
    assert reading == Reading(
        role="production",
        asks=[
            Asked(name="ignore", taken="held", line=17),
            Asked(
                name="public-api",
                taken="flagged",
                line=16,
                api=ApiChanged(kind="class-added", name="Room"),
            ),
            Asked(
                name="public-api",
                taken="flagged",
                line=5,
                api=ApiChanged(kind="signature-changed", name="Client.ask"),
            ),
        ],
        findings=[
            Found(
                rule=rule,
                message=f"{rule} fires here",
                steer="do it the other way",
                start=line,
                end=line,
                taken=taken,
            )
            for rule, line, taken in TAKEN
        ],
    )


def test_a_reading_places_a_name_taken_out_of_a_package_root_where_it_was(
    judge: Judging,
) -> None:
    init = '"""Pkg."""\n__all__ = [\n    "Client",\n    "Room",\n]\n'
    reading = judge(
        edit("src/pkg/__init__.py", init, init.replace('    "Client",\n', ""))
    ).reading()
    assert reading.asks == [
        Asked(
            name="public-api",
            taken="held",
            line=3,
            side="before",
            api=ApiChanged(kind="export-removed", name="Client"),
        )
    ]


def test_a_file_that_asks_nothing_reads_as_its_role_alone(judge: Judging) -> None:
    reading = judge(edit("tests/test_a.py", None, "x = 1  # BAD regex\n")).reading()
    assert reading == Reading(role="test")


# Judged from the parse alone.


def test_from_the_parse_alone_a_change_asks_what_the_whole_judgement_asks_but_rules(
    kit: Kit, tmp_path: Path
) -> None:
    project = Project(
        held=["protected", "operator", "ignore", "regex"],
        flagged=["new-file", "whole-file", "public-api", "tuple-shape"],
    )
    judging = Judge(
        root=tmp_path,
        roles=Roles(root=tmp_path, declaration=Declaration.of(project)),
        checker=kit.engine,
        linter=kit.linter,
    )
    after = (
        CORE.replace("def ask(self, prompt: str)", "def ask(self, prompt: int)")
        + "y = 2  # BAD regex\n"
        + "z = 3  # RUFF E501\n"
        + "\n\nclass Room:\n"
        + '    # lup: ignore("string-split", why="a fixed format")\n'
        + "    pass\n"
    )
    changes = [
        edit("src/pkg/core.py", CORE, after),
        edit("src/pkg/fresh.py", None, CORE, baseline=None),
        edit(PROTECTED, CORE, CORE + "y = 2  # BAD regex\n"),
        edit("pyproject.toml", "a\n", "b\n"),
        edit("docs/a.md", None, "# A\n"),
    ]
    parsed = judging.parsed(changes, kit.parser)
    assert kit.engine.checked == []
    assert kit.linter.runners == []
    # One request, each version once: a file's start and the content before its
    # change are one here.
    assert [
        [(str(each.path), each.content == CORE) for each in asked]
        for asked in kit.parser.parsed_asked
    ] == [
        [
            ("src/pkg/core.py", False),
            ("src/pkg/core.py", True),
            ("src/pkg/fresh.py", True),
            (PROTECTED, False),
            (PROTECTED, True),
        ]
    ]
    typed = judging.judge(changes, inform=False)
    assert [each.reading().asks for each in parsed] == [
        each.reading().asks for each in typed
    ]
    assert [each.outcome for each in parsed] == [each.outcome for each in typed]
    assert [each.findings for each in parsed] == [[], [], [], [], []]
    assert [finding.rule for finding in typed[0].findings] == ["regex"]


def test_from_the_parse_alone_a_directives_own_problem_is_told(
    kit: Kit, tmp_path: Path
) -> None:
    judging = Judge(
        root=tmp_path,
        roles=Roles(root=tmp_path, declaration=Declaration.of(EVERY_HELD)),
        checker=kit.engine,
        linter=kit.linter,
        conditions=["other"],
    )
    after = CORE + 'x = 1  # lup: defer(when=ready, why="wait")\n'
    [judgement] = judging.parsed([edit("src/pkg/core.py", CORE, after)], kit.parser)
    assert [finding.rule for finding in judgement.findings] == ["defer-condition"]


def test_verdict_reasons() -> None:
    assert Judgement(path=Path("a"), role="docs", outcome="allow").reasons() == ["docs"]
    assert Judgement(path=Path("a"), role="production", outcome="allow").reasons() == [
        "rules-pass"
    ]


def test_touched_lines() -> None:
    assert touched_lines(None, "a\nb\n") == [1, 2]
    assert touched_lines("a\nb\nc\n", "a\nc\n") == [2]
    assert touched_lines("a\nb\n", "a\nb\nc\n") == [3]
    assert touched_lines("a\nb\n", "a\n") == [1]


# A value never published, on a line a write touches


WITHHELD = Withheld(
    held=[
        Held(kind="home", text="/home/op"),
        Held(kind="value", text="Kestrel Labs"),
    ]
)
"""Made-up values never published, as a launch would list them on the host."""


def test_a_value_on_a_touched_line_is_told_and_flagged_in_every_role(
    judge: Judging,
) -> None:
    for path in [
        "docs/notes.md",
        "tests/test_a.py",
        "data/a.json",
        "src/pkg/core.py",
        "pyproject.toml",
        "AGENTS.md",
    ]:
        change = edit(path, "a\nb\n", "a\nsee /home/op/x\n")
        judgement = judge(change, project=Project(), withheld=WITHHELD)
        [found] = judgement.findings
        assert (found.rule, found.span.start.line, found.span.start.column) == (
            "private",
            2,
            5,
        ), path
        assert found.message == "the operator's home path"
        assert "private" in [ask.name() for ask in judgement.flags], path
        assert "/home/op" not in found.message + found.steer


def test_a_value_nobody_wrote_now_is_told_apart_and_asks_nothing(
    judge: Judging,
) -> None:
    change = edit("docs/notes.md", "Kestrel Labs\nb\n", "Kestrel Labs\nc\n")
    judgement = judge(change, project=Project(), withheld=WITHHELD)
    assert judgement.findings == []
    assert [each.span.start.line for each in judgement.untouched] == [1]
    assert judgement.flags == []
    assert judgement.outcome == "allow"


def test_a_path_git_ignores_and_a_judge_with_no_list_find_nothing(
    judge: Judging,
) -> None:
    ignored = edit("notes.md", None, "/home/op\n").model_copy(
        update={"published": False}
    )
    assert judge(ignored, project=Project(), withheld=WITHHELD).findings == []
    plain = edit("notes.md", None, "/home/op\n")
    assert judge(plain, project=Project()).findings == []


def test_a_new_file_s_path_holding_a_value_is_told(judge: Judging) -> None:
    created = edit("docs/kestrel labs.md", None, "Plain.\n")
    [found] = judge(created, project=Project(), withheld=WITHHELD).findings
    assert found.message == "one of the operator's private values, in the file's path"


def test_a_project_holding_private_values_holds_the_write(judge: Judging) -> None:
    holding = Project(held=["protected", "operator", "ignore", "private"], flagged=[])
    change = edit("docs/notes.md", "a\n", "a\nKestrel Labs\n")
    judgement = judge(change, project=holding, withheld=WITHHELD)
    assert judgement.outcome == "ask"
    assert [(ask.kind, ask.line) for ask in judgement.asks] == [("private", 2)]
    assert judgement.reasons() == ["private"]


def test_the_review_reads_a_private_value_by_its_finding_flagged(
    judge: Judging,
) -> None:
    change = edit("docs/notes.md", "a\n", "a\nKestrel Labs\n")
    reading = judge(change, project=Project(), withheld=WITHHELD).reading()
    assert reading.asks == []
    assert reading.findings == [
        Found(
            rule="private",
            message="one of the operator's private values",
            steer=(
                "leave it out of what's published; the operator, who listed it, "
                "knows which it is"
            ),
            start=2,
            end=2,
            taken="flagged",
        )
    ]


def test_a_private_value_is_told_in_a_block_of_its_own(judge: Judging) -> None:
    change = edit("docs/notes.md", "Kestrel Labs\n", "Kestrel Labs\nsee /home/op\n")
    judgement = judge(change, project=Project(), withheld=WITHHELD)
    told = information(judgement.findings, [], judgement.untouched, [])
    assert told == (
        "Values never published, on the lines changed (rewrite each before it's "
        "committed: the operator sees this write with them, the gate's `private` "
        "step fails on them, and a push or a post carrying one is refused):\n"
        "  docs/notes.md:2:5 - private: the operator's home path\n"
        "      steer: write it as `~`, or a path in the repository from its root\n"
        "\n"
        "Values never published, on lines no change touched (the gate's `private` "
        "step fails on them too):\n"
        "  docs/notes.md:1:1 - private: one of the operator's private values\n"
        "      steer: leave it out of what's published; the operator, who listed "
        "it, knows which it is"
    )
