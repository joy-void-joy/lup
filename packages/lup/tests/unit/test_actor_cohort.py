"""A population of agents that stays reachable, from inside and from outside.

These are written against the failures that make a cohort useless without
being visibly broken: an agent that cannot be steered because whoever spawned
it is blocked waiting for it, an address that resolves only in the process
that minted it, a second round that turns one agent into two, and a message
meant for the spawner that its siblings eat.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from lup.actors.cohort import ActorCohort, ActorRecipe, CohortJournal
from lup.actors.mail import EVERYONE
from lup.actors.refs import ActorRef
from lup.hooks import LupHooksConfig
from lup.runtime.contracts import Session, Turn
from lup.client import Client
from lup.runtime.models import (
    TurnHandle,
    TurnInput,
    TurnRequest,
    TurnResult,
    turn_request,
)
from tests.unit.doubles import session_factory, turn_result


class Finding(BaseModel):
    """A submission carrying the field a finished spawn is summarized by."""

    summary: str = ""


class HeldTurn[T: BaseModel | None](Turn[T]):
    """A turn that finishes when the test says so, or fails as it was told."""

    def __init__(
        self,
        value: TurnResult[T],
        hold: asyncio.Event | None,
        fails: Exception | None,
    ) -> None:
        self.value = value
        self.hold = hold
        self.fails = fails

    async def result(self) -> TurnResult[T]:
        if self.hold is not None:
            await self.hold.wait()
        if self.fails is not None:
            raise self.fails
        return self.value


class HeldSession(Session):
    """A session whose turn the test controls, keeping the hooks it opened with.

    Holding the turn open is what lets a test steer a spawn that is still
    working, which is the whole property `start` exists for.
    """

    def __init__(
        self,
        summary: str = "",
        hold: asyncio.Event | None = None,
        fails: Exception | None = None,
    ) -> None:
        self.summary = summary
        self.hold = hold
        self.fails = fails
        self.hooks: LupHooksConfig | None = None

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        output_type = request.output_type
        if output_type is None or not issubclass(output_type, BaseModel):
            raise AssertionError("these turns request typed output")
        output = output_type.model_validate({"summary": self.summary})
        return TurnHandle[T](turn=HeldTurn(turn_result(output), self.hold, self.fails))


def recipe_for(session: HeldSession) -> ActorRecipe:
    """A recipe that opens one held session and keeps the hooks it is given.

    The hooks are threaded through rather than dropped, because a recipe that
    ignores them is exactly how an agent ends up looking spawned and reading
    nothing anyone sends it.
    """

    def recipe(_actor: ActorRef, hooks: LupHooksConfig) -> Client:
        session.hooks = hooks
        return session_factory(session)

    return recipe


def test_a_spawn_is_reached_by_every_spelling_of_the_label_it_printed(
    tmp_path: Path,
) -> None:
    """Whatever a reader saw is a handle they can use."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("verifier")
    cohort.spawn(actor, "check the drift bound")

    printed = cohort.live()[0].address
    assert cohort.reaching(printed) == actor
    assert cohort.reaching(actor.id) == actor
    assert cohort.reaching(f"verifier:{actor.id}") == actor


def test_an_address_nobody_spawned_reaches_nobody(tmp_path: Path) -> None:
    """A miss is a miss rather than the first actor in the store."""
    cohort = ActorCohort(tmp_path)
    cohort.spawn(cohort.actor("verifier"), "check something")

    assert cohort.reaching("verifier:beefbeef") is None
    assert cohort.reaching("") is None


def test_a_broadcast_token_names_no_single_agent(tmp_path: Path) -> None:
    """`*` is every agent, so resolving it to one would deliver to the wrong one."""
    cohort = ActorCohort(tmp_path)
    cohort.spawn(cohort.actor("analyst"), "position the claim")

    assert cohort.reaching(EVERYONE) is None


def test_two_spawns_of_one_kind_are_told_apart(tmp_path: Path) -> None:
    """The kind is a label, not an identity — a cohort holds many of one."""
    cohort = ActorCohort(tmp_path)
    first = cohort.actor("refuter")
    second = cohort.actor("refuter")
    cohort.spawn(first, "attack the lemma")
    cohort.spawn(second, "attack the corollary")

    assert first != second
    cohort.say(first, "only you")
    assert cohort.outstanding(first) == 1
    assert cohort.outstanding(second) == 0


def test_an_id_a_caller_supplies_is_the_address(tmp_path: Path) -> None:
    """A caller with durable state to name an agent by keeps naming it.

    Which is what lets a restarted run reattach: a minted id would be
    different on the next process and every persisted session orphaned.
    """
    cohort = ActorCohort(tmp_path)

    assert cohort.actor("worker", "some-concern").label() == "worker:some-concern#1"
    assert cohort.actor("worker", "some-concern") == cohort.actor(
        "worker", "some-concern"
    )


def test_a_second_round_advances_one_agent_rather_than_adding_another(
    tmp_path: Path,
) -> None:
    """A worker's round two is the agent that took round one, one attempt on."""
    cohort = ActorCohort(tmp_path)
    cohort.spawn(cohort.actor("worker", "a-concern"), "first attempt")
    cohort.spawn(cohort.actor("worker", "a-concern", round=2), "after review")

    assert [member.address for member in cohort.live()] == ["worker:a-concern#2"]
    assert cohort.reaching("worker:a-concern#1") == cohort.reaching(
        "worker:a-concern#2"
    )


def test_what_was_sent_is_outstanding_until_it_is_handed_over(
    tmp_path: Path,
) -> None:
    """Accepting a message is not the same as anyone having read it."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("analyst")
    cohort.spawn(actor, "position the claim")

    cohort.say(actor, "the base moved")
    cohort.say(actor, "stop that branch", redirect=True)
    assert cohort.outstanding(actor) == 2

    delivered = cohort.inbox(actor).take()
    assert [message.redirect for message in delivered] == [False, True]
    assert cohort.outstanding(actor) == 0


def test_delivery_is_recorded_against_the_actor_that_received_it(
    tmp_path: Path,
) -> None:
    """A message that reached someone leaves a record saying so."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("computator")
    cohort.spawn(actor, "measure the drift")
    cohort.say(actor, "use exact arithmetic")

    cohort.inbox(actor).take()

    posted = [entry.event for entry in CohortJournal(tmp_path).for_actor(actor)]
    assert [event.type for event in posted] == ["message_posted"]


def test_a_finished_spawn_sorts_behind_a_running_one(tmp_path: Path) -> None:
    """What is still working is what a reader is looking for."""
    cohort = ActorCohort(tmp_path)
    done = cohort.actor("certifier")
    working = cohort.actor("analyst")
    cohort.spawn(done, "search the matrix space")
    cohort.spawn(working, "position the result")
    cohort.roster.finished(done, summary="found a 3x3 witness")

    assert [spawn.running for spawn in cohort.live()] == [True, False]
    assert cohort.live()[1].summary == "found a 3x3 witness"


def test_finishing_an_address_nobody_recorded_is_ignored(tmp_path: Path) -> None:
    """A stray completion is not a reason to invent a spawn."""
    cohort = ActorCohort(tmp_path)
    cohort.roster.finished(cohort.actor("analyst"), summary="never started")

    assert cohort.live() == []


def test_a_process_that_spawned_nothing_reaches_what_another_one_did(
    tmp_path: Path,
) -> None:
    """The door steering a spawn is usually not the process that made it.

    An in-memory registry answered only for its own process, so a console in
    another terminal — and a run resumed after a park — saw an empty cohort
    and reported every address as unknown.
    """
    spawning = ActorCohort(tmp_path)
    actor = spawning.actor("refuter")
    spawning.spawn(actor, "attack the bound")

    outside = ActorCohort(tmp_path)

    assert outside.reaching(actor.label()) == actor
    assert [member.task for member in outside.live()] == ["attack the bound"]


def test_the_spawner_is_an_address_its_agents_can_reach(tmp_path: Path) -> None:
    """A member's report goes to whoever spawned it, and to no sibling.

    Addressed to the humans by leaving the target blank, it used to match
    every actor's own address list — so it was delivered into the siblings'
    context, consumed there, and never seen by a person at all.
    """
    cohort = ActorCohort(tmp_path)
    sibling = cohort.actor("worker", "other-concern")
    cohort.spawn(sibling, "do the other thing")

    cohort.tell_spawner("I could not remove my own scratch file")

    assert [message.text for message in cohort.heard().messages] == [
        "I could not remove my own scratch file"
    ]
    assert cohort.outstanding(sibling) == 0


def test_a_broadcast_reaches_every_member_including_a_later_one(
    tmp_path: Path,
) -> None:
    """One record rather than a fan-out, so a spawn made afterwards still reads it."""
    cohort = ActorCohort(tmp_path)
    early = cohort.actor("analyst")
    cohort.spawn(early, "position the claim")

    cohort.say_all("the base moved under all of you")

    late = cohort.actor("refuter")
    cohort.spawn(late, "attack it")

    assert cohort.outstanding(early) == 1
    assert cohort.outstanding(late) == 1


@pytest.mark.asyncio
async def test_a_started_agent_leaves_its_caller_free_to_steer_it(
    tmp_path: Path,
) -> None:
    """The whole point of starting rather than asking.

    A caller blocked inside an awaited call cannot make another, so a cohort
    of awaited spawns has steering tools that can never fire. Here the caller
    keeps its turn and redirects what it just started.
    """
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("refuter")
    working = asyncio.Event()
    session = HeldSession(summary="attacked", hold=working)

    cohort.start(
        actor, turn_request(TurnInput(text="attack it"), Finding), recipe_for(session)
    )

    assert [member.running for member in cohort.live()] == [True]
    cohort.say(actor, "that branch is closed", redirect=True)
    assert cohort.outstanding(actor) == 1

    working.set()
    await cohort.wait_all()

    assert [member.running for member in cohort.live()] == [False]
    assert cohort.live()[0].summary == "attacked"


@pytest.mark.asyncio
async def test_an_asked_agent_records_what_it_found(tmp_path: Path) -> None:
    """The awaited path leaves the same record the started one does."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("analyst")
    session = HeldSession(summary="the bound holds")

    result = await cohort.ask(
        actor, turn_request(TurnInput(text="check it"), Finding), recipe_for(session)
    )

    assert result.output is not None and result.output.summary == "the bound holds"
    assert [member.summary for member in cohort.live()] == ["the bound holds"]
    assert [member.running for member in cohort.live()] == [False]


@pytest.mark.asyncio
async def test_a_failed_agent_records_why_rather_than_vanishing(
    tmp_path: Path,
) -> None:
    """A spawn that died is a spawn whose reader can find out that it died."""
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("formalizer")
    session = HeldSession(fails=RuntimeError("the toolchain is degraded"))

    with pytest.raises(RuntimeError):
        await cohort.ask(
            actor,
            turn_request(TurnInput(text="formalize it"), Finding),
            recipe_for(session),
        )

    assert cohort.live()[0].error == "the toolchain is degraded"
    assert cohort.live()[0].running is False


@pytest.mark.asyncio
async def test_a_spawn_is_handed_the_hooks_that_reach_it(tmp_path: Path) -> None:
    """The wiring the cohort owns, so a recipe cannot forget it.

    Delivery works only if the hook is in the options the session opened
    with. A caller that had to fetch it could write a recipe once without
    it, producing an agent that looks addressed and reads nothing.
    """
    cohort = ActorCohort(tmp_path)
    session = HeldSession()

    cohort.session(cohort.actor("analyst"), recipe_for(session))

    assert session.hooks is not None
    assert [matcher.tag for matcher in session.hooks.pre_tool_use] == ["inbox"]


@pytest.mark.asyncio
async def test_a_round_advances_an_agent_instead_of_finishing_it(
    tmp_path: Path,
) -> None:
    """A turn and a lifetime coincide only for an agent asked once.

    An agent that revises over several rounds is the same agent between
    them. Recorded finished after each round, it reads as stopped to every
    door while it is still working — and a caller that wanted the one-shot
    behaviour has `ask`, which is this plus the finish.
    """
    cohort = ActorCohort(tmp_path)
    session = HeldSession(summary="first pass")

    await cohort.round(
        cohort.actor("worker", "a-concern"),
        turn_request(TurnInput(text="resolve it"), Finding),
        recipe_for(session),
    )

    assert [member.running for member in cohort.live()] == [True]

    await cohort.round(
        cohort.actor("worker", "a-concern", round=2),
        turn_request(TurnInput(text="revise it"), Finding),
        recipe_for(session),
    )

    # One member advanced, not two: the second round is the same agent.
    assert [member.actor.round for member in cohort.live()] == [2]
    assert cohort.live()[0].running is True

    await cohort.finish(cohort.actor("worker", "a-concern", round=2), summary="settled")

    assert cohort.live()[0].running is False
    assert cohort.live()[0].summary == "settled"


@pytest.mark.asyncio
async def test_a_round_records_one_start_however_often_it_is_announced(
    tmp_path: Path,
) -> None:
    """Detaching work and opening its first round announce the same start.

    Two records for one round leave a reader measuring how long that round
    took with no way to say which start it ran from, so the roster keeps the
    one and the fold stays a fold.
    """
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("worker", "a-concern")
    session = HeldSession(summary="done")

    cohort.spawn(actor, "resolve it")
    await cohort.round(
        actor, turn_request(TurnInput(text="resolve it"), Finding), recipe_for(session)
    )

    starts = [
        record for record in cohort.roster.stream.read_all() if record.type == "spawned"
    ]
    assert len(starts) == 1


@pytest.mark.asyncio
async def test_started_work_is_a_pipeline_rather_than_a_single_turn(
    tmp_path: Path,
) -> None:
    """The unit a caller runs concurrently is rarely one turn.

    A concern carried through a worker turn and a review is one agent's work
    from the roster's side. A cohort that could only detach single turns
    left every such caller to fan out for itself, with its own cap and its
    own answer to who is running.
    """
    cohort = ActorCohort(tmp_path)
    actor = cohort.actor("worker", "a-concern")
    working = asyncio.Event()
    session = HeldSession(summary="first pass", hold=working)
    rounds: list[int] = []

    async def pipeline(opened: ActorRef) -> str:
        for number in (1, 2):
            await cohort.round(
                opened.model_copy(update={"round": number}),
                turn_request(TurnInput(text="work"), Finding),
                recipe_for(session),
            )
            rounds.append(number)
        await cohort.finish(opened, summary="accepted")
        return "accepted"

    cohort.start_work(actor, pipeline, task="resolve the concern")

    assert [member.running for member in cohort.live()] == [True]
    cohort.say(actor, "the base moved under you")

    working.set()
    await cohort.wait_all()

    assert rounds == [1, 2]
    assert cohort.live()[0].running is False
    assert cohort.live()[0].summary == "accepted"


@pytest.mark.asyncio
async def test_the_cohort_caps_how_many_of_its_agents_work_at_once(
    tmp_path: Path,
) -> None:
    """The cap belongs to the population, not to each caller fanning out.

    Three callers each holding their own semaphore around `start` is three
    answers to how many agents this population runs, and the roster agrees
    with none of them.
    """
    cohort = ActorCohort(tmp_path, parallel=2)
    working = asyncio.Event()
    peak = 0
    inside = 0

    async def work(_opened: ActorRef) -> None:
        nonlocal peak, inside
        inside += 1
        peak = max(peak, inside)
        await working.wait()
        inside -= 1

    for index in range(5):
        cohort.start_work(cohort.actor("worker", f"concern-{index}"), work, task="work")

    await asyncio.sleep(0)
    # Every one of them is listed and addressable, and only two are running:
    # mail is held by address, so steering never waits on a slot.
    assert len(cohort.live()) == 5
    assert peak == 2

    working.set()
    await cohort.wait_all()

    assert peak == 2


@pytest.mark.asyncio
async def test_a_wave_hands_back_every_answer_against_its_own_address(
    tmp_path: Path,
) -> None:
    """A caller that classifies failures needs each one, not a flattened list.

    The resolver's wave decides what a batch meant from the exceptions it
    got — this one parked, this one was the host, this one really failed —
    so a fan-out that returned only the successes, or only the count, would
    leave it unable to tell a suspended batch from a failed one.
    """
    cohort = ActorCohort(tmp_path)
    trouble = RuntimeError("the lease would not open")

    async def work(opened: ActorRef) -> str:
        if opened.id == "second":
            raise trouble
        return f"{opened.id} finished"

    results = await cohort.work_all(
        work,
        [cohort.actor("worker", name) for name in ("first", "second", "third")],
    )

    assert results == ["first finished", trouble, "third finished"]


@pytest.mark.asyncio
async def test_a_wave_leaves_a_suspended_agent_standing(tmp_path: Path) -> None:
    """Work that stopped because it was suspended has not finished its agent.

    A park, a drain and a host fault all raise, and all three expect the same
    agent to carry on once the reason is gone. Recorded finished, the resume
    opens a fresh conversation instead of reattaching to the one already
    holding the context, and every door reads a waiting agent as a stopped
    one.
    """

    class Parked(Exception):
        """The consumer's own way of saying "waiting on a human"."""

    cohort = ActorCohort(tmp_path, settles=lambda error: not isinstance(error, Parked))

    async def work(opened: ActorRef) -> None:
        raise Parked("waiting") if opened.id == "parked" else RuntimeError("died")

    results = await cohort.work_all(
        work,
        [cohort.actor("worker", name) for name in ("parked", "failed")],
    )

    assert [type(result) for result in results] == [Parked, RuntimeError]
    standing = {member.actor.id: member for member in cohort.live()}
    assert standing["parked"].running is True
    assert standing["failed"].running is False
    assert standing["failed"].error == "died"


@pytest.mark.asyncio
async def test_a_suspension_out_of_a_turn_leaves_its_agent_standing(
    tmp_path: Path,
) -> None:
    """The judgement has to reach the turn, not only the work around it.

    A suspension is raised in both places a raise can happen. A drain checked
    between rounds comes out of the work, and a host fault comes out of the
    turn itself — and the turn's own failure path ran first, finishing the
    agent before anything else was consulted. So of the three suspensions a
    consumer names, the one that arrives through a turn was the one that did
    not stand, and the retry it exists for opened a fresh conversation.
    """

    class Faulted(Exception):
        """The consumer's own way of saying "the host failed, not the work"."""

    cohort = ActorCohort(tmp_path, settles=lambda error: not isinstance(error, Faulted))
    session = HeldSession(fails=Faulted("credential revoked"))
    actor = cohort.actor("worker", "faulted")

    with pytest.raises(Faulted):
        await cohort.round(
            actor, turn_request(TurnInput(text="go"), Finding), recipe_for(session)
        )

    standing = {member.actor.id: member for member in cohort.live()}
    assert standing["faulted"].running is True, "the host said nothing about it"
    assert standing["faulted"].error == ""
