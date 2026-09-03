"""What a session may believe about its own boundary, read inside the dispatcher.

The half that closes the gap the whole layer is named for. `contained` used to
read `LUP_CONTAINED`, a constant an image bakes — and a constant answers yes for
any container built from that image, for a bare `run` holding none of the lease,
and for an uncontained session whose launcher forwarded a variable the operator
happened to export. Each of those is a session reporting a boundary nothing put
under it.

So the answer comes from a ledger a launch wrote, and only from the one that
launch named. Everything here is a case where the honest answer is "no boundary
was measured", which every caller reads as the fail-closed one.
"""

import json
from pathlib import Path

import pytest

from lup.policy.assets.host import (
    contained,
    defers_unjudged,
    delivers,
    measured_boundary,
)

MEASURED = {
    "profile": ["contained"],
    "contained": ["yes"],
    "unjudged_ambient": ["ask"],
    "delivered": ["inside_placement", "question_relay"],
    "blocked": ["host_executor"],
}


def written(root: Path, nonce: str, ledger: dict[str, list[str]]) -> None:
    """One launch's measurement, where that launch would have put it."""
    path = root / ".lup" / "preflight" / f"{nonce}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger), encoding="utf-8")


def test_an_inherited_variable_no_longer_grants_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this replaced, stated as the case that must now fail.

    A launcher forwards its own environment, so an uncontained session started
    from a shell exporting `LUP_CONTAINED=1` used to report a boundary with no
    container under it — and place every operation by a wall that was not
    there. Nothing consults that variable now, so the claim costs nothing.
    """
    monkeypatch.setenv("LUP_CONTAINED", "1")
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)

    assert not contained(measured_boundary(tmp_path))


def test_a_session_believes_only_the_ledger_its_own_launch_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ledger left by another launch is a measurement of another session.

    Which is the same class of wrong answer as the constant, reached from the
    other direction — so the nonce decides, and a session holding none reads
    nothing at all.
    """
    written(tmp_path, "the-launch-that-measured", MEASURED)

    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "some-other-launch")
    assert not contained(measured_boundary(tmp_path))

    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "the-launch-that-measured")
    assert contained(measured_boundary(tmp_path))


def test_each_capability_is_answered_from_what_was_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delivered and blocked are different facts and both are recorded."""
    written(tmp_path, "launch", MEASURED)
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "launch")

    measured = measured_boundary(tmp_path)

    assert delivers(measured, "inside_placement")
    assert delivers(measured, "question_relay")
    assert not delivers(measured, "host_executor")
    assert not delivers(measured, "checkpoint_store")


def test_the_ambient_policy_is_the_profiles_and_asks_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session that could not read its profile does not infer a seamless one."""
    written(tmp_path, "asking", MEASURED)
    written(tmp_path, "deferring", {**MEASURED, "unjudged_ambient": ["defer"]})

    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "asking")
    assert not defers_unjudged(measured_boundary(tmp_path))

    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "deferring")
    assert defers_unjudged(measured_boundary(tmp_path))

    monkeypatch.delenv("LUP_BOUNDARY_NONCE")
    assert not defers_unjudged(measured_boundary(tmp_path))


def test_every_way_of_having_no_measurement_reads_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent, unnamed, wrecked, and the wrong shape are one answer.

    A session whose launcher predates this has no ledger and gets exactly what
    a session whose boundary failed to stand gets — which is the fail-closed
    answer, and the only one that cannot be wrong in the dangerous direction.
    """
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "launch")
    assert measured_boundary(tmp_path) == {}
    assert measured_boundary(None) == {}

    path = tmp_path / ".lup" / "preflight" / "launch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert measured_boundary(tmp_path) == {}

    path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
    assert measured_boundary(tmp_path) == {}


def test_a_ledger_carrying_something_other_than_strings_drops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This half validates by hand, because it may reach no parser but json.

    A capability name that is not a string cannot be compared to one, and
    keeping it would put a value of unknown shape in front of every later
    read. Dropped rather than refused: the rest of the measurement is still
    a measurement.
    """
    written(tmp_path, "launch", MEASURED)
    path = tmp_path / ".lup" / "preflight" / "launch.json"
    path.write_text(
        json.dumps({**MEASURED, "delivered": ["question_relay", 7, None]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", "launch")

    measured = measured_boundary(tmp_path)

    assert measured["delivered"] == ["question_relay"]
    assert contained(measured)
