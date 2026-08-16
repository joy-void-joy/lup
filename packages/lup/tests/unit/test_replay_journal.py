"""Replay journals: identity, divergence, and what a divergence means."""

from lup.replay.journal import JournalCell, ReplayJournal


def journal(*outcomes: bool, claims_determinism: bool = False) -> ReplayJournal:
    return ReplayJournal(
        id="j1",
        cells=[
            JournalCell(source=f"cell {index}", ok=ok)
            for index, ok in enumerate(outcomes)
        ],
        determinism_claimed=claims_determinism,
    )


def test_a_faithful_replay_reports_no_divergence() -> None:
    report = journal(True, True).compare([True, True])

    assert report.reproduced
    assert report.cells_replayed == 2
    assert "no divergence" in report.finding()


def test_a_cell_that_replayed_differently_is_named() -> None:
    report = journal(True, True, True).compare([True, False, True])

    assert not report.reproduced
    assert [item.index for item in report.divergences] == [1]
    assert report.divergences[0].recorded_ok
    assert not report.divergences[0].replayed_ok


def test_divergence_without_a_determinism_claim_is_the_finding() -> None:
    # The environment promised nothing, so a divergence is information about
    # what the result depended on — not a broken promise.
    report = journal(True).compare([False])

    assert "which is the finding" in report.finding()
    assert "not reproducible" not in report.finding()


def test_divergence_against_a_determinism_claim_is_a_defect() -> None:
    report = journal(True, claims_determinism=True).compare([False])

    finding = report.finding()
    assert "determinism was claimed" in finding
    assert "nothing built on it should be treated as established" in finding


def test_a_replay_that_stopped_early_is_compared_as_far_as_it_went() -> None:
    report = journal(True, True, True).compare([True])

    assert report.cells_replayed == 1
    assert report.reproduced


def test_identity_covers_the_cells_and_not_the_envelope() -> None:
    # A journal forked from another records the same execution, so it has to
    # digest the same however its id and lineage differ.
    original = journal(True, False)
    forked = original.model_copy(update={"id": "j2", "parent": "j1"})

    assert forked.digest() == original.digest()


def test_a_different_execution_digests_differently() -> None:
    assert journal(True, True).digest() != journal(True, False).digest()
