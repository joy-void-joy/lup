"""What the gate's pytest step does with the test roots a project declares.

The gate runs one pytest per declared root, and everything it decides before
that run is decided from a declaration rather than from this repository: which
flags the environment can answer for, and whether the directory a root names is
even there. Both were read from what the template happens to hold, so both were
green here and broken for every project that installed the library.
"""

from importlib.machinery import ModuleSpec

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
