"""What a bracketed deferral's condition is resolved to, and when it wakes."""

import pytest

from lup.codescan.markers import MarkerComment, NoteKind
from lup.devtools.dev.branches import get_integration_branch
from lup.devtools.dev.comments import FoundComment
from lup.devtools.dev.gates import (
    BranchInPlay,
    Gate,
    GateVerdict,
    PathGone,
    current_branch,
    inbound_notes,
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
    assert isinstance(gate, BranchInPlay)
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
    assert BranchInPlay(argument="").asked().fired
    assert PathGone(argument="").asked().fired


def test_a_path_gate_reads_the_tree_it_is_checked_against() -> None:
    present = PathGone(argument="pyproject.toml").asked()
    assert not present.fired
    assert "still exists" in present.evidence
    absent = PathGone(argument="no/such/file/anywhere.txt").asked()
    assert absent.fired


def test_a_branch_gate_fires_on_the_branch_it_names() -> None:
    # The moment the whole gate exists for. A note about a branch is written
    # for whoever works on that branch, and they are the last to see it: it
    # lives where its author stood, and their checkout carries no copy until
    # they merge. Waking on arrival only would reach them one step after the
    # step it was written to change.
    standing = BranchInPlay(argument=current_branch()).asked()
    assert standing.fired
    assert "you are on" in standing.evidence


def test_a_branch_gate_fires_once_its_branch_is_in_the_integration_branch() -> None:
    # The integration branch is trivially its own ancestor, which is the one
    # landed branch whose name is stable enough to pin: any feature branch
    # named here would land eventually and turn this into a test about how old
    # the checkout is. Either reason is a pass — running this from the
    # integration branch itself reaches the same verdict by the other route.
    landed = BranchInPlay(argument=get_integration_branch()).asked()
    assert landed.fired
    assert get_integration_branch() in landed.evidence


def test_a_branch_gate_fires_when_its_branch_is_no_longer_there() -> None:
    # Pruned after landing is the likely reading and abandoned is the other,
    # and both are moments the note wanted somebody at. The evidence says which
    # question to settle rather than deciding it here.
    vanished = BranchInPlay(argument="no-such-branch-was-ever-pushed").asked()
    assert vanished.fired
    assert "no longer exists" in vanished.evidence


def test_a_note_on_another_ref_reaches_the_branch_it_names() -> None:
    # The half that makes any of this arrive in time, read against a ref this
    # commit controls rather than against whatever the integration branch
    # happens to hold today. The real case is the same shape one step out:
    # content-overhaul has not merged dev, so a deferral naming it is found
    # only by reading the ref it was left on.
    inbound = inbound_notes("content-overhaul", "HEAD")
    assert inbound, "the deferral naming content-overhaul was not found on HEAD"
    assert all(note.condition == "branch:content-overhaul" for note in inbound)
    assert all(note.kind == NoteKind.defer for note in inbound)


def test_a_branch_nobody_left_a_note_about_gets_nothing() -> None:
    # Naming is what keeps this quiet. A check that surfaced every deferral on
    # the integration branch would put the same wall of text in front of every
    # branch in the repository.
    assert inbound_notes("some-branch-no-note-mentions", "HEAD") == []


def test_a_detached_head_asks_no_branch_question_rather_than_erroring() -> None:
    assert inbound_notes("", "HEAD") == []


def test_a_ref_that_does_not_resolve_is_quiet_rather_than_fatal() -> None:
    # `dev check` runs in checkouts that may not carry the integration branch
    # at all — a fresh clone of one branch, a CI job fetched shallow. Failing
    # there would refuse the whole check over a question it merely could not
    # put.
    assert inbound_notes("content-overhaul", "no-such-ref-anywhere") == []


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
