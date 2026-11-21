"""The inbox's promises: what agents and the operator can count on of what's said between them and where each concern stands.

Each is checked through the harness, lup started on its default modules: agents
call the inbox's tools, the operator its commands, and an agent's project's code
its services, as #5's sessions will (`README.md` here).
"""

import lup
from lup import (
    Agent,
    Blocks,
    Codebase,
    Commented,
    Fold,
    Machine,
    Model,
    Modules,
    Operator,
    Part,
    Project,
)
from lup.inbox.records import Decision, Ruling
from lup.inbox.said import (
    Answering,
    AskSaid,
    Clearing,
    ConcernOf,
    ConcernSaid,
    Ending,
    Everywhere,
    FrictionSaid,
    Inboxed,
    Naming,
    NoteSaid,
    Nothing,
    OnItem,
    PartiesOf,
    PartyOf,
    Pile,
    Placed,
    Reached,
    SaidSince,
    SendSaid,
    Since,
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
    answered = await started.serve("told", Ending(agent=agent), HERE)
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Told)
    return answered.output


async def viewed(started: Started, view: str, given: Model) -> Blocks:
    """Read one of the inbox's views as the operator does, which must answer its blocks."""
    answered = await started.view("core", view, given, Operator())
    assert isinstance(answered, Accepted), answered
    assert isinstance(answered.output, Blocks)
    return answered.output


def folds(blocks: Blocks) -> list[Fold]:
    """Return the folds among `blocks`."""
    return [each for each in blocks.blocks if isinstance(each, Fold)]


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
        await started.serve("agent_ended", Ending(agent=agent), HERE)
        left = placed(await inboxed(started), "the gate")
        assert left.holder == "@no-agent"
        assert left.left_by is not None
        await started.serve("agent_started", Ending(agent=agent), HERE)
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
    async def what_was_said_reads_once_with_what_it_answered(self, by: Testing) -> None:
        """Every item said reads once from a read of what's been said since, each with its words whole and what it's on: a question with each decision and its lean, an answer with the question and the decisions it rules on, a comment with the item and the lines it quotes."""
        started = await by.started(project())
        agent = by.any(Agent)
        reader = by.any(Machine) if by.any(bool) else HERE
        await said(
            started,
            "ask",
            AskSaid(
                question="which way?",
                decisions=[Decision(decision="go left", lean="yes, it's shorter")],
            ),
            agent,
        )
        [question] = (await inboxed(started)).waiting
        await started.run(
            "core",
            "answer",
            Answering(question=question, rulings=[Ruling(number=1, verdict="leaning")]),
            Operator(),
        )
        await said(started, "note", NoteSaid(remark="a doubt\n\nand why"), agent)
        note = max((await inboxed(started)).new)
        await started.run(
            "core",
            "comment",
            Commented[OnItem](
                on=OnItem(item=note), words="answered", lines=["and why"]
            ),
            Operator(),
        )
        first = await started.serve("said", Since(), reader)
        assert isinstance(first, Accepted)
        assert isinstance(first.output, SaidSince)
        items = first.output.items
        asked = next(each for each in items if each.number == question)
        assert "go left" in asked.text
        assert "yes, it's shorter" in asked.text
        ruled = next(each for each in items if each.kind == "inbox:answer")
        assert ruled.on == question
        assert ruled.quoted is not None
        assert "go left" in ruled.quoted
        commented = next(each for each in items if each.text == "answered")
        assert commented.on == note
        assert commented.quoted == "and why"
        assert commented.agent is None
        assert len(dict.fromkeys(each.key for each in items)) == len(items)
        again = await started.serve("said", Since(after=first.output.last), reader)
        assert isinstance(again, Accepted)
        assert isinstance(again.output, SaidSince)
        assert again.output.items == []

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
        writer, reader = Agent.of("writer-id"), Agent.of("reader-id")
        await started.serve("agent_named", Naming(agent=writer, name="writer"), HERE)
        await started.serve("agent_named", Naming(agent=reader, name="reader"), HERE)
        await said(started, "send", SendSaid(to="reader", text="over to you"), writer)
        message = max((await inboxed(started)).new)
        commented = await started.run(
            "core",
            "comment",
            Commented[OnItem](on=OnItem(item=message), words="noted"),
            Operator(),
        )
        assert isinstance(commented, Accepted)
        for agent in [writer, reader]:
            assert any(
                each.text == "noted" for each in (await told(started, agent)).items
            )

    @lup.promise
    async def the_operator_finds_each_concern_from_the_list_of_parties(
        self, by: Testing
    ) -> None:
        """Every concern an agent opens is found from the list of parties, under the party holding it, and opens on what was said in it; a comment on it reaches its holder."""
        started = await by.started(project())
        agent = by.any(Agent)
        await started.serve("agent_named", Naming(agent=agent, name="builder"), HERE)
        await said(
            started,
            "concern",
            ConcernSaid(text="it hung twice", title="the gate hangs"),
            agent,
        )
        await said(
            started,
            "friction",
            FrictionSaid(text="slow keys", under="frictions/keys"),
            agent,
        )
        listed = folds(
            await viewed(started, "parties", PartiesOf(repository="harness"))
        )
        assert listed
        assert all(each.kind == "party" for each in listed)
        builder = folds(
            await viewed(
                started, "party", PartyOf(repository="harness", name="builder")
            )
        )
        [gate] = [each for each in builder if each.kind == "concern"]
        assert gate.reaches == agent
        keys = folds(
            await viewed(
                started, "party", PartyOf(repository="harness", name="frictions/keys")
            )
        )
        [slow] = [each for each in keys if each.kind == "concern"]
        assert slow.reaches == Pile(repository="harness", path="frictions/keys")
        number = int(gate.id.removeprefix("concern-"))
        words = await viewed(started, "concern_view", ConcernOf(number=number))
        assert any("it hung twice" in line for line in words.text().splitlines())

    @lup.promise
    async def what_waits_is_shown_as_waiting(self, by: Testing) -> None:
        """What waits on the operator is in their view of what waits, and leaves it once they answer it."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(started, "ask", AskSaid(question="which way?"), agent)
        assert (
            "which way?"
            in (
                await viewed(started, "waiting", PartiesOf(repository="harness"))
            ).text()
        )
        [question] = (await inboxed(started)).waiting
        await started.run(
            "core", "answer", Answering(question=question, text="this way"), Operator()
        )
        assert (
            "which way?"
            not in (
                await viewed(started, "waiting", PartiesOf(repository="harness"))
            ).text()
        )

    @lup.promise
    async def a_friction_about_another_repository_lands_in_its_pile(
        self, by: Testing
    ) -> None:
        """A friction an agent of one project sends to another repository's pile lands there, made if it isn't, and not in their own."""
        started = await by.started(project())
        lup_agent, project_agent = by.any(Agent), Agent.of("downstream")
        await said(started, "note", NoteSaid(remark="here first"), lup_agent)
        elsewhere = Codebase(repository="downstream")
        sent = await started.serve(
            "friction",
            {
                "agent": project_agent.model_dump(),
                "said": FrictionSaid(
                    text="lup's keys lag", under="frictions/keys", repository="harness"
                ).model_dump(),
            },
            elsewhere,
        )
        assert isinstance(sent, Accepted), sent
        found = placed(await inboxed(started), "lup's keys lag")
        assert found.holder == "@frictions/keys"
        assert found.kind == "inbox:friction"

    @lup.promise
    async def a_comment_on_a_pile_opens_a_concern_there(self, by: Testing) -> None:
        """A comment the operator writes on a block whose party is a pile opens a concern in that pile, holding their words."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started,
            "friction",
            FrictionSaid(text="first sighting", under="frictions/keys"),
            agent,
        )
        pile = Pile(repository="harness", path="frictions/keys")
        commented = await started.run(
            "core",
            "comment_to",
            Commented[Reached](on=Reached(party=pile), words="group these"),
            Operator(),
        )
        assert isinstance(commented, Accepted), commented
        found = placed(await inboxed(started), "group these")
        assert found.holder == "@frictions/keys"
