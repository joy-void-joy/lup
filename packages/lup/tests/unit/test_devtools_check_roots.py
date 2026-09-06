"""What the gate's pytest step does with the test roots a project declares.

The gate runs one pytest per declared root, and everything it decides before
that run is decided from a declaration rather than from this repository: which
flags the environment can answer for, and whether the directory a root names is
even there. Both were read from what the template happens to hold, so both were
green here and broken for every project that installed the library.
"""

from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

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
