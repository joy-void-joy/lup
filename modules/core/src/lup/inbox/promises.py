"""The inbox's promises: what agents and the operator can count on of what's said between them and where each concern stands.

Each is checked through the harness, lup started on its default modules: agents
call the inbox's tools, the operator its commands, and an agent's project's code
its services, as #5's sessions will (`README.md` here).
"""

import lup
from lup import Agent, Codebase, Model, Modules, Operator, Part, Project
from lup.inbox.said import (
    Answering,
    AskSaid,
    Clearing,
    Commenting,
    ConcernSaid,
    Ending,
    Everywhere,
    FrictionSaid,
    Inboxed,
    Naming,
    NoteSaid,
    Nothing,
    Placed,
    SendSaid,
    Told,
    WithdrawSaid,
)
from lup.testing import Accepted, Started, Step, Testing

HERE = Codebase(repository="harness")
"""The harness's project's own code, which calls the inbox's services for its agents."""


def project() -> Project:
    """Return a project of lup's default modules, the inbox among them."""
    return Project(modules=Modules.default())


async def inboxed(started: Started) -> Inboxed:
    """Read the inbox as data, as its project's code does."""
    read = await started.serve("standing", Nothing(), HERE)
    assert isinstance(read, Accepted)
    assert isinstance(read.output, Inboxed)
    return read.output


async def said(started: Started, tool: str, given: lup.Model, agent: Agent) -> str:
    """Call one of the inbox's tools as `agent`, and return what it answered, which it must."""
    answered = await started.call(tool, given, agent)
    assert isinstance(answered, Accepted), answered
    assert isinstance(answered.output, str)
    return answered.output


async def told(started: Started, agent: Agent) -> Told:
    """Tell `agent` what's for them, as their session's next call does."""
    answered = await started.serve("told", Ending(agent=agent.id), HERE)
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Told)
    return answered.output


def placed(state: Inboxed, title: str) -> Placed:
    """Return the concern titled `title`, which must be there."""
    [found] = [each for each in state.concerns if each.title == title]
    return found


class Changed(Model):
    """One concern as it stood before a step and after it."""

    before: Placed
    after: Placed


def changed(step: Step[Everywhere]) -> list[Changed]:
    """Return each concern there both before and after `step`, of every repository, as it stood before and after."""
    before = {
        each.number: each for inbox in step.before.inboxes for each in inbox.concerns
    }
    return [
        Changed(before=before[each.number], after=each)
        for inbox in step.after.inboxes
        for each in inbox.concerns
        if each.number in before
    ]


class InboxPromises(Part):
    """What agents and the operator can count on of the inbox."""

    @lup.promise
    def nothing_is_told_twice(self, step: Step[Everywhere]) -> bool:
        """Nothing is told to a party twice."""
        return all(
            each.times <= 1 for inbox in step.after.inboxes for each in inbox.told
        )

    @lup.promise
    def every_comment_reaches_a_party(self, step: Step[Everywhere]) -> bool:
        """Every comment of the operator's reaches at least one party."""
        return all(
            each.reaches >= 1 for inbox in step.after.inboxes for each in inbox.comments
        )

    @lup.promise
    def clearing_is_the_operators(self, step: Step[Everywhere]) -> bool:
        """A concern is cleared by the operator's act alone, never by anything an agent says or does."""
        return isinstance(step.by(), Operator) or all(
            each.after.cleared <= each.before.cleared for each in changed(step)
        )

    @lup.promise
    def what_is_cleared_comes_back_only_with_something_new(
        self, step: Step[Everywhere]
    ) -> bool:
        """A cleared concern comes back only when something new is said in it."""
        return all(
            each.after.cleared
            or not each.before.cleared
            or each.after.said > each.before.said
            for each in changed(step)
        )

    @lup.promise
    async def a_friction_lands_where_its_agent_sends_it(self, by: Testing) -> None:
        """A friction sent to a pile's path not there yet makes the pile, each pile above it too, and reads there as a friction, not a concern."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started,
            "friction",
            FrictionSaid(text="the keys lag", under="frictions/dashboard/keys"),
            agent,
        )
        found = placed(await inboxed(started), "the keys lag")
        assert found.kind == "inbox:friction"
        assert found.holder == "@frictions/dashboard/keys"

    @lup.promise
    async def an_ended_agents_concerns_wait_in_no_agent(self, by: Testing) -> None:
        """What an ended agent held reads as in `no-agent`, saying who left it, and is theirs again when they start again."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started,
            "concern",
            ConcernSaid(text="watch the gate", title="the gate"),
            agent,
        )
        await started.serve("agent_ended", Ending(agent=agent.id), HERE)
        left = placed(await inboxed(started), "the gate")
        assert left.holder == "@no-agent"
        assert left.left_by is not None
        await started.serve("agent_started", Ending(agent=agent.id), HERE)
        back = placed(await inboxed(started), "the gate")
        assert back.holder == left.left_by
        assert back.left_by is None

    @lup.promise
    async def a_question_waits_until_answered(self, by: Testing) -> None:
        """A question waits on the operator until they answer it, and a note never does."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(started, "ask", AskSaid(question="which way?"), agent)
        await said(started, "note", NoteSaid(remark="a doubt"), agent)
        [question] = (await inboxed(started)).waiting
        answered = await started.run(
            "core", "answer", Answering(question=question, text="this way"), Operator()
        )
        assert isinstance(answered, Accepted)
        assert not (await inboxed(started)).waiting
        assert any(
            each.kind == "inbox:answer" for each in (await told(started, agent)).items
        )

    @lup.promise
    async def a_withdrawn_question_waits_on_nobody(self, by: Testing) -> None:
        """A question its agent withdraws waits on nobody after."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(started, "ask", AskSaid(question="still needed?"), agent)
        [question] = (await inboxed(started)).waiting
        await said(
            started, "withdraw", WithdrawSaid(item=question, why="settled"), agent
        )
        assert not (await inboxed(started)).waiting

    @lup.promise
    async def news_stays_until_cleared(self, by: Testing) -> None:
        """News stays new until the operator clears it; clearing a concern clears what's in it, until something newer is said there."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started, "concern", ConcernSaid(text="first", title="a direction"), agent
        )
        state = await inboxed(started)
        assert state.new
        concern = placed(state, "a direction")
        cleared = await started.run(
            "core",
            "clear",
            Clearing(repository="harness", what=str(concern.number)),
            Operator(),
        )
        assert isinstance(cleared, Accepted)
        after = await inboxed(started)
        assert not after.new
        assert placed(after, "a direction").cleared
        await said(
            started,
            "concern",
            ConcernSaid(name=str(concern.number), text="second"),
            agent,
        )
        again = await inboxed(started)
        assert again.new
        assert not placed(again, "a direction").cleared

    @lup.promise
    async def a_comment_on_agents_exchange_reaches_both(self, by: Testing) -> None:
        """The operator's comment on a message one agent sent another reaches both: whoever wrote it, and whoever it was for."""
        started = await by.started(project())
        writer, reader = Agent(id="writer-id"), Agent(id="reader-id")
        await started.serve("agent_named", Naming(agent=writer.id, name="writer"), HERE)
        await started.serve("agent_named", Naming(agent=reader.id, name="reader"), HERE)
        await said(started, "send", SendSaid(to="reader", text="over to you"), writer)
        message = max((await inboxed(started)).new)
        commented = await started.run(
            "core", "comment", Commenting(item=message, text="noted"), Operator()
        )
        assert isinstance(commented, Accepted)
        for agent in [writer, reader]:
            assert any(
                each.text == "noted" for each in (await told(started, agent)).items
            )
