"""What a bracketed deferral's condition is resolved to, and when it wakes."""

import pytest

from lup.codescan.markers import MarkerComment, NoteKind
from lup.devtools.dev.branches import get_integration_branch
from lup.devtools.dev.comments import FoundComment
from lup.devtools.dev.gates import (
    BranchLanded,
    Gate,
    GateVerdict,
    PathGone,
    parse_gate,
    sweep_gates,
)


class AlwaysFires(Gate, frozen=True):
    """A gate with a fixed answer, so a sweep can be tested without a checkout."""

    keyword = "always"

    def asked(self) -> GateVerdict:
        return GateVerdict(fired=True, evidence=f"always, for {self.argument}")


class NeverFires(Gate, frozen=True):
    """The other fixed answer."""

    keyword = "never"

    def asked(self) -> GateVerdict:
        return GateVerdict(fired=False, evidence="never")


FIXED: list[type[Gate]] = [AlwaysFires, NeverFires]


def parked(
    condition: str | None, text: str = "park it", where: str = "a.py"
) -> FoundComment:
    """One deferred note carrying *condition*, as a scan would have found it."""
    return FoundComment(
        start_line=1,
        end_line=1,
        read_start=1,
        read_end=1,
        text=text,
        kind=NoteKind.defer,
        condition=condition,
        file=where,
        context="",
    )


def test_a_condition_naming_a_declared_keyword_resolves_to_that_gate() -> None:
    gate = parse_gate("branch:content-overhaul")
    assert isinstance(gate, BranchLanded)
    assert gate.argument == "content-overhaul"
    assert gate.spelling() == "branch:content-overhaul"


def test_a_condition_stating_prose_stays_prose() -> None:
    # The spelling every deferral used before any of them could be resolved,
    # and the one a gate this checkout cannot see still has to be written in.
    assert parse_gate("content-overhaul lands") is None
    assert parse_gate("until the v2 API ships") is None


def test_prose_that_happens_to_contain_a_colon_is_still_prose() -> None:
    # A keyword is one word, which is the whole of what separates the two.
    assert parse_gate("when the v2 API ships: probably next quarter") is None


def test_a_colon_after_an_undeclared_keyword_is_prose_rather_than_an_error() -> None:
    # A gate this union does not declare is a real condition somebody stated,
    # not a typo — so it degrades to the listing rather than to a failure.
    assert parse_gate("milestone:4") is None


def test_a_deferral_stating_no_condition_resolves_to_nothing() -> None:
    assert parse_gate(None) is None


def test_whitespace_around_the_argument_is_not_part_of_it() -> None:
    gate = parse_gate("branch:  content-overhaul  ")
    assert gate is not None
    assert gate.argument == "content-overhaul"


def test_a_gate_naming_nothing_fires_rather_than_passing_quietly() -> None:
    # `branch:` with no branch is a typo, and the loud reading is the safe one:
    # a gate that silently never fires is indistinguishable from one that has
    # not come true yet, which is the failure this whole module exists to end.
    assert BranchLanded(argument="").asked().fired
    assert PathGone(argument="").asked().fired


def test_a_path_gate_reads_the_tree_it_is_checked_against() -> None:
    present = PathGone(argument="pyproject.toml").asked()
    assert not present.fired
    assert "still exists" in present.evidence
    absent = PathGone(argument="no/such/file/anywhere.txt").asked()
    assert absent.fired


def test_a_branch_gate_fires_once_its_branch_is_in_the_integration_branch() -> None:
    # The integration branch is trivially its own ancestor, which is the one
    # landed branch whose name is stable enough to pin: any feature branch
    # named here would land eventually and turn this into a test about how old
    # the checkout is.
    landed = BranchLanded(argument=get_integration_branch()).asked()
    assert landed.fired
    assert "has reached" in landed.evidence


def test_a_branch_gate_fires_when_its_branch_is_no_longer_there() -> None:
    # Pruned after landing is the likely reading and abandoned is the other,
    # and both are moments the note wanted somebody at. The evidence says which
    # question to settle rather than deciding it here.
    vanished = BranchLanded(argument="no-such-branch-was-ever-pushed").asked()
    assert vanished.fired
    assert "no longer exists" in vanished.evidence


def test_a_sweep_counts_only_the_gates_it_could_put() -> None:
    # Prose was never a question this checkout could ask, so folding it into
    # the total would report coverage the sweep does not have.
    sweep = sweep_gates(
        [parked("never:x"), parked("some prose"), parked(None)], declared=FIXED
    )
    assert sweep.asked == 1
    assert sweep.woken == []


def test_a_fired_gate_carries_the_note_and_the_evidence_whole() -> None:
    sweep = sweep_gates(
        [parked("always:reason", text="the whole instruction", where="b.py")],
        declared=FIXED,
    )
    assert sweep.asked == 1
    assert len(sweep.woken) == 1
    woken = sweep.woken[0]
    assert woken.file == "b.py"
    assert woken.gate == "always:reason"
    assert woken.evidence == "always, for reason"
    assert woken.text == "the whole instruction"
    assert "the whole instruction" in woken.reported()


def test_a_sweep_with_nothing_fired_says_how_many_it_asked() -> None:
    sweep = sweep_gates([parked("never:x"), parked("never:y")], declared=FIXED)
    assert sweep.lines() == ["woken deferrals: ok, 2 gate(s) asked"]


def test_a_sweep_that_fired_leads_with_the_failure() -> None:
    sweep = sweep_gates([parked("always:x"), parked("never:y")], declared=FIXED)
    assert sweep.lines()[0] == "woken deferrals: FAIL (1 of 2 gate(s) fired)"


def test_only_a_defer_note_can_carry_a_condition_at_all() -> None:
    # The coherence the marker model already enforces, pinned here because the
    # sweep reads `condition` off every note it is handed and would otherwise
    # be trusting an invariant nothing in this module states.
    with pytest.raises(ValueError):
        MarkerComment(
            start_line=1,
            end_line=1,
            read_start=1,
            read_end=1,
            text="x",
            kind=NoteKind.note,
            condition="branch:whatever",
        )
