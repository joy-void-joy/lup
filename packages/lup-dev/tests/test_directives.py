"""Checking `# lup:` directives: ignore, defer, notes, malformed calls."""

from typing import TYPE_CHECKING, Literal

import httpx
import pytest

from lup_dev.codescan.conditions import (
    Condition,
    ConditionError,
    PackageIndex,
    PackageReleased,
    PyPI,
    PythonAvailable,
    Pythons,
    declared,
    loaded,
)
from lup_dev.codescan.directives import (
    Checking,
    Defer,
    Directive,
    Fired,
    Ignore,
    IssueRef,
    Issues,
    Malformed,
    Note,
    Trackers,
    added_suppressions,
    holding,
    missing,
)

if TYPE_CHECKING:
    from pathlib import Path


class FakeIssues(Issues):
    closed: list[int] = []

    def state(self, issue: IssueRef) -> Literal["open", "closed"]:
        return "closed" if issue.number in self.closed else "open"

    def unreachable(self) -> str | None:
        return None


class Always(Condition):
    answer: bool

    def holds(self) -> bool:
        return self.answer


def ignore(rule: str = "tuple-shape", covers: int = 3) -> Ignore:
    return Ignore(line=covers - 1, covers=covers, rule=rule, why="sh takes tuples")


def test_an_ignore_keeps_its_rule_on_the_line_it_covers() -> None:
    assert ignore().keeps("tuple-shape", 3)
    assert not ignore().keeps("tuple-shape", 4)
    assert not ignore().keeps("regex", 3)


def test_an_ignore_whose_rule_doesnt_fire_there_is_a_finding() -> None:
    checking = Checking(fired=[Fired(rule="regex", line=3)])
    [problem] = ignore().problems(checking)
    assert problem.rule == "unused-ignore"
    assert problem.fixable
    assert ignore().problems(Checking(fired=[Fired(rule="tuple-shape", line=3)])) == []


def test_an_ignore_keeps_any_owners_finding() -> None:
    assert ignore("E501").problems(Checking(fired=[Fired(rule="E501", line=3)])) == []


def test_an_ignore_waiting_on_a_closed_issue_is_due_and_keeps_its_finding() -> None:
    waiting = ignore().model_copy(update={"issue": 12})
    fired = [Fired(rule="tuple-shape", line=3)]
    closed = Checking(fired=fired, gate=Trackers(issues=FakeIssues(closed=[12])))
    [problem] = waiting.problems(closed)
    assert (problem.rule, problem.line) == ("ignore-closed", 2)
    assert problem.reminder
    assert "issue #12 is closed" in problem.message
    assert waiting.keeps("tuple-shape", 3)
    still_open = Checking(fired=fired, gate=Trackers(issues=FakeIssues()))
    assert waiting.problems(still_open) == []
    assert waiting.problems(Checking(fired=fired)) == []
    unchecked = Checking(fired=fired, gate=Trackers(issues=None))
    assert waiting.problems(unchecked) == []


def test_an_ignore_needs_a_readable_issue() -> None:
    waiting = ignore().model_copy(update={"issue": "lup seven"})
    [problem] = waiting.problems(Checking(fired=[Fired(rule="tuple-shape", line=3)]))
    assert problem.rule == "ignore-issue"
    assert not problem.reminder


def test_an_ignores_issue_is_no_part_of_what_the_operator_is_asked() -> None:
    waiting = ignore().model_copy(update={"issue": 12})
    assert waiting.identity() == ignore().identity()
    assert added_suppressions([ignore()], [waiting]) == []
    assert missing([waiting], [ignore()]) == []


def test_a_malformed_directive_is_a_finding() -> None:
    malformed = Malformed(line=4, text="todo()", problem="`todo` is no directive")
    [problem] = malformed.problems(Checking())
    assert problem.rule == "malformed-directive"
    assert problem.message == "`todo` is no directive"


def test_a_note_is_never_a_finding() -> None:
    assert (
        Note(line=1, text="the retry count is the provider's").problems(Checking())
        == []
    )


def test_a_defer_needs_a_readable_issue() -> None:
    [problem] = Defer(line=1, issue="lup seven", why="x").problems(Checking())
    assert problem.rule == "defer-issue"
    assert Defer(line=1, issue="joy-void-joy/lup#7", why="x").problems(Checking()) == []
    assert Defer(line=1, issue=7, why="x").problems(Checking()) == []


def test_a_defer_names_a_declared_condition() -> None:
    defer = Defer(line=1, when="sdk_reports_ttl", why="read the TTL")
    [problem] = defer.problems(Checking(conditions=["other"]))
    assert problem.rule == "defer-condition"
    [problem] = defer.problems(Checking(conditions=None))
    assert problem.rule == "defer-condition"
    assert defer.problems(Checking(conditions=["sdk_reports_ttl"])) == []


def test_at_the_gate_a_closed_issue_is_reported() -> None:
    gate = Trackers(issues=FakeIssues(closed=[12]))
    [problem] = Defer(line=1, issue=12, why="x").problems(Checking(gate=gate))
    assert problem.rule == "defer-closed"
    assert problem.reminder
    assert Defer(line=1, issue=13, why="x").problems(Checking(gate=gate)) == []


def test_at_the_gate_an_issue_out_of_reach_goes_unchecked_and_a_due_condition_still_reports() -> (
    None
):
    gate = Trackers(issues=None, held=holding({"ready": Always(answer=True)}))
    checking = Checking(conditions=["ready"], gate=gate)
    assert Defer(line=1, issue=12, why="x").problems(checking) == []
    [problem] = Defer(line=1, issue=12, when="ready", why="x").problems(checking)
    assert problem.rule == "defer-due"


def test_at_the_gate_a_condition_that_holds_makes_the_defer_due() -> None:
    gate = Trackers(
        issues=FakeIssues(),
        held=holding({"ready": Always(answer=True), "later": Always(answer=False)}),
    )
    checking = Checking(conditions=["ready", "later"], gate=gate)
    [problem] = Defer(line=1, when="ready", why="x").problems(checking)
    assert problem.rule == "defer-due"
    assert problem.reminder
    assert Defer(line=1, when="later", why="x").problems(checking) == []


def test_a_comment_moved_to_another_line_is_the_same_comment() -> None:
    before: list[Directive] = [Note(line=1, text="keep"), ignore(covers=3)]
    after: list[Directive] = [Note(line=9, text="keep"), ignore(covers=11)]
    assert missing(after, before) == []


def test_removed_comments_are_counted_each_time() -> None:
    before: list[Directive] = [Note(line=1, text="same"), Note(line=2, text="same")]
    after: list[Directive] = [Note(line=1, text="same")]
    assert missing(after, before) == [Note(line=2, text="same")]


def test_only_added_ignores_ask() -> None:
    before: list[Directive] = [ignore("a")]
    after: list[Directive] = [ignore("a"), ignore("b"), Note(line=1, text="new note")]
    assert added_suppressions(before, after) == [ignore("b")]


def test_issue_references() -> None:
    assert IssueRef.read(7) == IssueRef(number=7)
    assert IssueRef.read("owner/repo#7") == IssueRef(repository="owner/repo", number=7)
    assert IssueRef.read("https://github.com/owner/repo#7") is None
    assert IssueRef.read("owner#7") is None
    assert str(IssueRef(repository="owner/repo", number=7)) == "owner/repo#7"


class Listed(Pythons):
    listed: list[str]

    def versions(self) -> list[str]:
        return self.listed


class Index(PackageIndex):
    released: list[str]

    def releases(self, name: str) -> list[str]:
        return self.released


def test_python_available_wants_a_final_release() -> None:
    assert not PythonAvailable(
        version="3.15", pythons=Listed(listed=["3.14.2", "3.15.0rc3"])
    ).holds()
    assert PythonAvailable(version="3.15", pythons=Listed(listed=["3.15.0"])).holds()
    assert PythonAvailable(version="3.15", pythons=Listed(listed=["3.15.2"])).holds()


def test_package_released_wants_that_version_or_later() -> None:
    assert not PackageReleased(
        name="sdk", version="1.0", index=Index(released=["0.9", "1.0rc1"])
    ).holds()
    assert PackageReleased(
        name="sdk", version="1.0", index=Index(released=["1.0.1"])
    ).holds()


def test_pypi_reads_releases_skipping_yanked_ones() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://pypi.org/pypi/sdk/json"
        return httpx.Response(
            200,
            json={
                "releases": {
                    "1.0": [{"yanked": True}],
                    "0.9": [{"yanked": False}],
                    "0.8": [],
                }
            },
        )

    index = PyPI(transport=httpx.MockTransport(answer))
    assert index.releases("sdk") == ["0.9"]


def test_pypi_raises_on_an_error_answer() -> None:
    index = PyPI(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(httpx.HTTPStatusError):
        index.releases("missing")


def test_conditions_are_read_without_running_and_loaded_at_the_gate(repo: Path) -> None:
    (repo / "src" / "cond_one").mkdir()
    (repo / "src" / "cond_one" / "__init__.py").write_text("")
    (repo / "src" / "cond_one" / "conditions.py").write_text(
        "from lup_dev.codescan.conditions import PythonAvailable\n"
        'python_315 = PythonAvailable(version="3.15")\n'
        "limit: int = 3\n"
    )
    modules = ["cond_one.conditions"]
    assert declared(repo, modules) == ["python_315", "limit"]
    assert list(loaded(repo, modules)) == ["python_315"]
    assert declared(repo, []) is None
    assert loaded(repo, []) == {}


def conditions_module(repo: Path, package: str, text: str) -> str:
    (repo / "src" / package).mkdir()
    (repo / "src" / package / "__init__.py").write_text("")
    (repo / "src" / package / "conditions.py").write_text(
        f"from lup_dev.codescan.conditions import PythonAvailable\n{text}"
    )
    return f"{package}.conditions"


def test_each_modules_conditions_are_read_together(repo: Path) -> None:
    modules = [
        conditions_module(
            repo, "cond_two", 'python_315 = PythonAvailable(version="3.15")\n'
        ),
        conditions_module(
            repo, "cond_three", 'python_316 = PythonAvailable(version="3.16")\n'
        ),
    ]
    assert declared(repo, modules) == ["python_315", "python_316"]
    assert list(loaded(repo, modules)) == ["python_315", "python_316"]
    assert list(loaded(repo, [*modules, modules[0]])) == ["python_315", "python_316"]


def test_two_modules_binding_one_condition_fail_at_the_gate(repo: Path) -> None:
    text = 'python_315 = PythonAvailable(version="3.15")\n'
    modules = [
        conditions_module(repo, "cond_four", text),
        conditions_module(repo, "cond_five", text),
    ]
    assert declared(repo, modules) == ["python_315"]
    with pytest.raises(
        ConditionError,
        match=r"`python_315` from `cond_four.conditions` and `cond_five.conditions`",
    ):
        loaded(repo, modules)
