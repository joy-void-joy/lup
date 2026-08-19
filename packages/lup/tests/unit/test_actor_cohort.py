"""Reaching an agent whose address did not exist a moment ago.

A cohort's actors are minted as a session goes, so the thing an operator
types is the only handle anyone has on one. These are written against the
failure that makes: printing a label the send path then fails to recognize,
so a message is reported sent and reaches nobody.
"""

from pathlib import Path

from lup.actors.cohort import ActorCohort


def test_a_spawn_is_reached_by_every_spelling_of_the_label_it_printed(
    tmp_path: Path,
) -> None:
    """Whatever a reader saw is a handle they can use."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.address("verifier")
    cohort.record(actor, "check the drift bound")

    printed = cohort.live()[0].address
    assert cohort.reaching(printed) == actor
    assert cohort.reaching(actor.id) == actor
    assert cohort.reaching(f"verifier:{actor.id}") == actor


def test_an_address_nobody_spawned_reaches_nobody(tmp_path: Path) -> None:
    """A miss is a miss rather than the first actor in the store."""
    cohort = ActorCohort(tmp_path)
    cohort.record(cohort.address("verifier"), "check something")

    assert cohort.reaching("verifier:beefbeef") is None
    assert cohort.reaching("") is None


def test_two_spawns_of_one_kind_are_told_apart(tmp_path: Path) -> None:
    """The kind is a label, not an identity — a cohort holds many of one."""
    cohort = ActorCohort(tmp_path)
    first = cohort.address("refuter")
    second = cohort.address("refuter")
    cohort.record(first, "attack the lemma")
    cohort.record(second, "attack the corollary")

    assert first != second
    cohort.say(first, "only you", redirect=False)
    assert cohort.outstanding(first) == 1
    assert cohort.outstanding(second) == 0


def test_what_was_sent_is_outstanding_until_it_is_handed_over(
    tmp_path: Path,
) -> None:
    """Accepting a message is not the same as anyone having read it."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.address("analyst")
    cohort.record(actor, "position the claim")

    cohort.say(actor, "the base moved", redirect=False)
    cohort.say(actor, "stop that branch", redirect=True)
    assert cohort.outstanding(actor) == 2

    delivered = cohort.sessions.inbox(actor).take()
    assert [message.redirect for message in delivered] == [False, True]
    assert cohort.outstanding(actor) == 0


def test_delivery_is_recorded_against_the_actor_that_received_it(
    tmp_path: Path,
) -> None:
    """A message that reached someone leaves a record saying so."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.address("computator")
    cohort.record(actor, "measure the drift")
    cohort.say(actor, "use exact arithmetic", redirect=False)

    cohort.sessions.inbox(actor).take()

    posted = [entry.event for entry in cohort.journal.for_actor(actor)]
    assert [event.type for event in posted] == ["message_posted"]


def test_a_finished_spawn_sorts_behind_a_running_one(tmp_path: Path) -> None:
    """What is still working is what a reader is looking for."""
    cohort = ActorCohort(tmp_path)
    done = cohort.address("certifier")
    working = cohort.address("analyst")
    cohort.record(done, "search the matrix space")
    cohort.record(working, "position the result")
    cohort.finish(done, summary="found a 3x3 witness")

    assert [spawn.running for spawn in cohort.live()] == [True, False]
    assert cohort.live()[1].summary == "found a 3x3 witness"


def test_finishing_an_address_nobody_recorded_is_ignored(tmp_path: Path) -> None:
    """A stray completion is not a reason to invent a spawn."""
    cohort = ActorCohort(tmp_path)
    cohort.finish(cohort.address("analyst"), summary="never started")

    assert cohort.live() == []
