"""What the gate's pytest step does with the test roots a project declares.

The gate runs one pytest per declared root, and everything it decides before
that run is decided from a declaration rather than from this repository: which
flags the environment can answer for, whether the directory a root names is
even there, and which suite installs a path somebody named. The first two were
read from what the template happens to hold, so both were green here and broken
for every project that installed the library.
"""

from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest
import typer

import lup.devtools.dev.check as check


def test_the_worker_flag_is_offered_where_the_plugin_answers_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check, "find_spec", lambda name: ModuleSpec(name, None))

    assert check.parallel_arguments(4) == ["-n", "4"]


def test_no_worker_flag_where_the_plugin_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An adopter installs the library's dependencies, which carry no
    # pytest-xdist, and pytest rejects `-n` before collecting anything. The
    # pytest row then read FAIL on every branch whatever the suite did, which
    # is indistinguishable from a real regression.
    monkeypatch.setattr(check, "find_spec", lambda name: None)

    assert check.parallel_arguments(4) == []


def test_one_worker_spells_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    # The count is the off switch: a worker count no higher than one is the
    # same run without the interpreter boot, so nothing else has to say it.
    monkeypatch.setattr(check, "find_spec", lambda name: ModuleSpec(name, None))

    assert check.parallel_arguments(1) == []
    assert check.parallel_arguments(0) == []


def test_a_root_whose_directory_is_missing_reports_instead_of_raising(
    tmp_path: Path,
) -> None:
    # The template declares a root at `packages/lup`, which an adopter
    # inherits and does not hold. `sh` changes directory in the forked child,
    # so the failure arrived as a fork exception rather than an exit status:
    # it escaped the gate, and the operator got a traceback where a verdict
    # belonged, with the checks that had already passed never reported.
    root = check.TestRoot(name="pytest (lup)", directory=tmp_path / "packages/lup")

    report = root.checked(4, [])

    assert not report.passed
    assert report.name == "pytest (lup)"
    assert str(root.directory) in report.lines[0]


def test_a_missing_root_names_the_declaration_rather_than_the_checker(
    tmp_path: Path,
) -> None:
    # "A declared root does not exist" and "its suite failed" send the reader
    # to different places, so the row says which of the two it is.
    report = check.TestRoot(name="pytest (lup)", directory=tmp_path / "gone").absent()

    assert "test_roots" in " ".join(report.lines)


def test_a_root_that_names_a_file_is_no_root(tmp_path: Path) -> None:
    # Not a directory is not a directory: the fork would fail the same way.
    named = tmp_path / "tests"
    named.write_text("", encoding="utf-8")

    assert not check.TestRoot(name="pytest", directory=named).checked(4, []).passed


def declared_roots(workspace: Path) -> list[check.TestRoot]:
    """The two-suite shape the template declares, rooted in a temporary tree."""
    return [
        check.TestRoot(name="pytest", directory=workspace),
        check.TestRoot(name="pytest (lup)", directory=workspace / "packages/lup"),
    ]


def test_paths_from_two_suites_become_two_invocations(tmp_path: Path) -> None:
    # Named in one pytest run, the two suites both claim `tests.conftest` and
    # collection dies before a test runs — so the narrowing move a caller
    # reaches for, run the suites I touched, is served one suite at a time.
    grouped = check.group_by_root(
        declared_roots(tmp_path),
        [
            str(tmp_path / "packages/lup/tests/unit/test_profiles.py"),
            str(tmp_path / "tests/unit/test_harness_compilation.py"),
        ],
    )

    assert [group.root.name for group in grouped] == ["pytest", "pytest (lup)"]
    assert [group.paths for group in grouped] == [
        ["tests/unit/test_harness_compilation.py"],
        ["tests/unit/test_profiles.py"],
    ]


def test_a_nested_suite_claims_what_sits_under_it(tmp_path: Path) -> None:
    # The workspace root contains the package root, so read in declaration
    # order it would claim every path and run the library's tests from a
    # directory where `src` is the application's.
    grouped = check.group_by_root(
        declared_roots(tmp_path), [str(tmp_path / "packages/lup/tests/unit")]
    )

    assert [group.root.name for group in grouped] == ["pytest (lup)"]
    assert grouped[0].paths == ["tests/unit"]


def test_naming_nothing_asks_every_suite_for_all_of_itself(tmp_path: Path) -> None:
    grouped = check.group_by_root(declared_roots(tmp_path), [])

    assert [group.paths for group in grouped] == [[], []]


def test_a_path_under_no_declared_suite_is_refused(tmp_path: Path) -> None:
    # Silently dropping it would report a green run over tests nobody ran.
    with pytest.raises(typer.BadParameter):
        check.group_by_root(declared_roots(tmp_path / "workspace"), [str(tmp_path)])
