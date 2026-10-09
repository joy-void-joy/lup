"""One judgement: each row of the allow table, and what decides it."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.judge import Change, Judge, Judgement, touched_lines
from lup_dev.policy.roles import Roles
from lup_dev.project import Exemption, Project

if TYPE_CHECKING:
    from conftest import Kit

CORE = (
    '"""Core."""\n\n\n'
    "class Client:\n"
    "    def ask(self, prompt: str) -> str:\n"
    "        return prompt\n\n\n"
    "def helper(x: int) -> int:\n"
    "    return x\n"
)


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
    ) -> Judgement:
        judging = Judge(
            root=self.root,
            roles=Roles(root=self.root, project=project or Project()),
            checker=self.kit.engine,
            linter=self.kit.linter,
            conditions=conditions,
            approved=approved or [],
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
        assert judgement.refusing == []


def test_the_operators_documents_ask(judge: Judging) -> None:
    judgement = judge(edit("DESIGN.md", "a\n", "b\n"))
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["operator-document"]


def test_a_protected_path_asks(judge: Judging) -> None:
    judgement = judge(edit("pyproject.toml", "a\n", "b\n"))
    assert judgement.outcome == "ask"
    assert (
        judgement.asks[0].reason
        == f"{judge.root}/pyproject.toml is a protected path (**/pyproject.toml)"
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


def test_a_finding_in_a_protected_module_refuses_before_it_asks(
    judge: Judging,
) -> None:
    after = CORE + "y = 2  # BAD regex\n"
    judgement = judge(edit(PROTECTED, CORE, after))
    assert judgement.outcome == "refuse"
    assert [finding.rule for finding in judgement.refusing] == ["regex"]
    assert [ask.kind for ask in judgement.asks] == ["protected"]
    assert judgement.reasons() == ["regex"]


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
    project = Project(excluded=["vendor/**"])
    after = "x = 1  # BAD regex\ny: int = 'a'  # TYPE\nimport os  # RUFF F401\n"
    judgement = judge(
        edit("vendor/lib.py", None, after, baseline=None), project=project
    )
    assert judgement.outcome == "allow"
    assert judgement.reasons() == ["excluded"]
    assert judgement.refusing == judgement.information == judgement.untouched == []


def test_an_excluded_protected_module_asks_without_its_findings(
    judge: Judging,
) -> None:
    project = Project(excluded=[".claude/hooks/**"])
    judgement = judge(
        edit(PROTECTED, CORE, CORE + "y = 2  # BAD regex\n"), project=project
    )
    assert judgement.outcome == "ask"
    assert [ask.kind for ask in judgement.asks] == ["protected"]
    assert judgement.refusing == []


def test_an_exempt_rule_is_lifted_from_its_paths_alone(judge: Judging) -> None:
    lifted = Exemption(rule="regex", paths=["src/pkg/**"], why="a grammar")
    project = Project(exempt=[lifted])
    after = CORE + "y = 2  # BAD regex\nz = 3  # BAD tuple-shape\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after), project=project)
    assert [found.rule for found in judgement.refusing] == ["tuple-shape"]
    elsewhere = judge(edit("src/other.py", None, after, baseline=None), project=project)
    assert sorted(found.rule for found in elsewhere.refusing) == [
        "regex",
        "tuple-shape",
    ]


def test_protected_files_that_arent_python_only_ask(judge: Judging) -> None:
    judgement = judge(edit(".claude/settings.json", "{}\n", "{} # BAD regex\n"))
    assert judgement.outcome == "ask"
    assert judgement.refusing == []


def test_deleting_a_protected_path_asks_and_deleting_code_is_allowed(
    judge: Judging,
) -> None:
    assert judge(edit(".github/ci.yml", "a\n", None)).outcome == "ask"
    assert judge(edit("src/pkg/core.py", CORE, None)).outcome == "allow"


def test_a_finding_on_a_touched_line_refuses_and_every_finding_is_listed(
    judge: Judging,
) -> None:
    before = CORE + "y = 2  # BAD regex\n"
    after = before + "z = 3  # BAD tuple-shape\n"
    judgement = judge(edit("src/pkg/core.py", before, after))
    assert judgement.outcome == "refuse"
    assert [finding.rule for finding in judgement.refusing] == ["tuple-shape"]
    assert [finding.rule for finding in judgement.untouched] == ["regex"]


def test_findings_on_untouched_lines_dont_refuse(judge: Judging) -> None:
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
    assert judgement.outcome == "refuse"


def test_writing_a_whole_existing_file_asks(judge: Judging) -> None:
    judgement = judge(edit("src/pkg/core.py", CORE, CORE + "\n", whole=True))
    assert [ask.kind for ask in judgement.asks] == ["whole-file"]


def test_a_new_class_asks(judge: Judging) -> None:
    after = CORE + "\n\nclass Room:\n    pass\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "ask"
    assert (
        judgement.asks[0].reason
        == f"{judge.root}/src/pkg/core.py adds the class `Room`"
    )


def test_a_changed_signature_of_a_definition_from_the_sessions_start_asks(
    judge: Judging,
) -> None:
    after = CORE.replace(
        "def helper(x: int) -> int", "def helper(x: int, y: int = 0) -> int"
    )
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert [ask.reason for ask in judgement.asks] == [
        f"{judge.root}/src/pkg/core.py changes the signature of `helper`"
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
        f"{judge.root}/src/pkg/__init__.py adds `Room` to the package's root"
    ]
    removed = judge(edit("src/pkg/__init__.py", init, init.replace('["Client"]', "[]")))
    assert [ask.reason for ask in removed.asks] == [
        f"{judge.root}/src/pkg/__init__.py removes `Client` from the package's root"
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
        'adds `# lup: ignore("tuple-shape", why="sh takes tuples")` to '
        f"{judge.root}/src/pkg/core.py"
    )
    assert judgement.refusing == []


def test_an_ignore_whose_rule_doesnt_fire_is_a_finding(judge: Judging) -> None:
    after = CORE + 'y = 1  # lup: ignore("tuple-shape", why="nothing here")\n'
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "refuse"
    assert [finding.rule for finding in judgement.refusing] == ["unused-ignore"]


def test_refuse_wins_over_ask(judge: Judging) -> None:
    judgement = judge(
        edit("src/pkg/new.py", None, "x = 1  # BAD regex\n", baseline=None)
    )
    assert judgement.outcome == "refuse"
    assert [ask.kind for ask in judgement.asks] == ["new-file"]


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


def test_type_errors_and_ruffs_findings_are_information(judge: Judging) -> None:
    after = CORE + "y: int = 'a'  # TYPE\nimport os  # RUFF F401\n"
    judgement = judge(edit("src/pkg/core.py", CORE, after))
    assert judgement.outcome == "allow"
    assert sorted(finding.owner for finding in judgement.information) == [
        "pyright",
        "ruff",
    ]


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


def test_a_defer_naming_an_undeclared_condition_refuses(judge: Judging) -> None:
    after = CORE + 'x = 1  # lup: defer(when=ready, why="wait")\n'
    assert (
        judge(edit("src/pkg/core.py", CORE, after), conditions=["ready"]).outcome
        == "allow"
    )
    judgement = judge(edit("src/pkg/core.py", CORE, after), conditions=["other"])
    assert [finding.rule for finding in judgement.refusing] == ["defer-condition"]


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
