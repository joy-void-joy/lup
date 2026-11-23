"""The inbox's parts: the one holding the store, which every act goes through, and the one speaking for agents.

`Inboxes` holds the store's database, one for the machine, since concerns cross
repositories and the operator reads every project's: what an agent says comes
to it as a service, called by its project's code, which lup vouches for, so the
repository an act is kept under is never one the caller names; what the
operator does comes to it as their actions and commands. `Speaking` is the
agents' side, in each project: their tools, each a service call on `Inboxes`
for the agent calling (`README.md` here, *Tools and acts*).
"""

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import Field

import lup
from lup.doors.door import RefusedError
from lup.doors.events import Stopping
from lup.doors.parties import Agent, Codebase, Machine, Operator
from lup.doors.parts import Data, Declared, Part
from lup.inbox import conversion, views
from lup.inbox.conversion import Converted
from lup.inbox.inbox import Inbox, InboxError, first_line
from lup.inbox.parts import ItemPart
from lup.inbox.records import (
    NODES,
    AgentRecord,
    Concern,
    Item,
    PartyRecord,
    PileRecord,
    Question,
)
from lup.inbox.said import (
    Addressing,
    Answering,
    Asked,
    AskSaid,
    Awaited,
    Awaiting,
    Clearing,
    CommentKept,
    ConcernDeclined,
    ConcernOf,
    ConcernSaid,
    Converting,
    Declining,
    Ended,
    Ending,
    Everywhere,
    FrictionSaid,
    Inboxed,
    ItemsSeen,
    Naming,
    NodeCleared,
    NoteSaid,
    Nothing,
    OnItem,
    PartiesOf,
    PartyOf,
    Pile,
    PileMade,
    Piling,
    Posted,
    Posting,
    QuestionAnswered,
    Reached,
    Reading,
    SaidSince,
    SendSaid,
    SentTo,
    Settling,
    Showing,
    Since,
    Spoken,
    Told,
    ToldItem,
    Untelling,
    Untold,
    Uttered,
    WithdrawSaid,
    Words,
)
from lup.inbox.views import Shows
from lup.shell.blocks import Blocks
from lup.shell.draft import Commented, Commenting
from lup.store.database import Database
from lup.store.errors import StoreError
from lup.store.records import Edge, Kinds, Node, Recorded

if TYPE_CHECKING:
    from collections.abc import Generator

DATABASE = "store.sqlite3"
"""The database's file, in the part's own directory."""


class Inboxes(Part, approved=True, shared=True):
    """The store's database and every repository's inbox kept in it, one for the machine: what's said and done goes through it."""

    data: Data
    """Where the database is kept, across restarts."""
    declared: Declared
    """Every module of the project lup runs on the machine, for the kinds of
    record each declares, which the database reads its records as: a module's
    own kinds of item among them."""
    database: Database | None = None
    """The database, opened the first time it's needed."""
    changes: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set at the database's next write, then made anew: what a held question
    waits on, each waiter reading what it waits for again once it's set."""
    state: Everywhere | None = None
    """Every repository's inbox as data, as last read: read again only once the database has taken a write since."""
    state_at: int = -1
    """How many writes the database had taken when `state` was read."""

    def opened(self) -> Database:
        """Return the database the inbox is kept in, opening it the first time: before anything else of the part runs, whatever order its start and its first call come in."""
        if self.database is None:
            kinds = self.declared.held(Recorded)
            self.database = Database.opened(
                self.data.path / DATABASE,
                Kinds(
                    nodes=[each for each in kinds if issubclass(each, Node)],
                    edges=[each for each in kinds if issubclass(each, Edge)],
                ),
            )
            self.database.watchers.append(self.changed)
        return self.database

    def changed(self) -> None:
        """Wake whatever waits on the database changing, and wait anew."""
        woken, self.changes = self.changes, asyncio.Event()
        woken.set()

    def change(self) -> asyncio.Event:
        """Return what's set at the database's next write."""
        return self.changes

    @lup.on(Stopping)
    async def closed(self, stopping: Stopping) -> None:
        """Close the database."""
        del stopping
        if self.database is not None:
            self.database.close()

    def inbox(self, repository: str) -> Inbox:
        """Return `repository`'s inbox."""
        return Inbox(database=self.opened(), repository=repository)

    def elsewhere(self, own: str, other: str | None) -> Inbox:
        """Return the inbox of the repository `other` names, else `own`'s: where an agent of `own` sends what they say; raise `InboxError` where the store holds nothing of `other`."""
        if other is None or other == own:
            return self.inbox(own)
        # lup: defer(issue=2, why="any repository the store holds, until #2 resolves the repositories a declaration relates, which alone an agent's project may write into")
        if other not in self.opened().repositories():
            message = f"the store holds nothing of a repository named `{other}`"
            raise InboxError(message, about=[other])
        return self.inbox(other)

    # Agents' acts, called by their project's code

    @lup.service
    async def concern(self, given: Spoken[ConcernSaid], by: Codebase) -> str:
        """Do what an agent says of a concern, and say what came of it."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        said = given.said
        with refusing():
            found = None if said.name is None else inbox.found_concern(said.name)
            if found is None:
                if said.text is None:
                    message = f"no concern of {by.repository} is `{said.name}`: give `text` to open it"
                    raise InboxError(message)
                under = inbox.place(agent, said.under)
                title = said.title or first_line(said.text)
                concern = inbox.opened(agent, title, said.text, under, name=said.name)
                return f"Opened @{concern.name or concern.number}, under {inbox.called(under)}."
            return inbox.acted(agent, found, said)

    @lup.service
    async def friction(
        self, given: Spoken[FrictionSaid], by: Codebase | Machine
    ) -> str:
        """Keep what got in an agent's way as a friction, where they send it, and say where.

        Called by the machine, as a landing files what its gate found, the
        agent's repository is the one the friction names, which it must name.
        """
        said = given.said
        own = by.repository if isinstance(by, Codebase) else said.repository
        if own is None:
            message = "a friction the machine files names the agent's repository"
            raise RefusedError(message)
        agent = self.inbox(own).agent(given.agent)
        with refusing():
            inbox = self.elsewhere(own, said.repository)
            under = inbox.party_or_pile(said.under, agent)
            spawner = inbox.under(agent)
            friction = inbox.opened(
                agent,
                said.title or first_line(said.text),
                said.text,
                under,
                friction=True,
                also=[spawner]
                if isinstance(spawner, AgentRecord)
                and spawner.repository == inbox.repository
                else [],
            )
        return f"Your friction is @{friction.number}, in {inbox.called(under)}."

    @lup.service
    async def note(self, given: Spoken[NoteSaid], by: Codebase) -> str:
        """Keep an agent's remark for the operator, in the concern it names or the one they work in."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            concern = inbox.thread(agent, given.said.thread)
            item = inbox.sent(
                agent, [inbox.operator()], given.said.remark, "note", concern
            )
        return f"Your note is @{item.number}."

    @lup.service
    async def send(self, given: Spoken[SendSaid], by: Codebase) -> str:
        """Send an agent's message to the party it names: a pile opens a concern with it."""
        own = self.inbox(by.repository)
        agent = own.agent(given.agent)
        said = given.said
        with refusing():
            inbox = self.elsewhere(by.repository, said.repository)
            to = inbox.party(said.to)
            concern = (
                own.thread(agent, said.thread)
                if inbox.repository == own.repository
                else None
            )
            if isinstance(to, PileRecord):
                opened = inbox.opened(agent, first_line(said.text), said.text, to)
                return f"Opened @{opened.number} in {inbox.called(to)}."
            item = inbox.sent(agent, [to], said.text, said.tone, concern)
        return f"Sent to {inbox.called(to)}, @{item.number}."

    @lup.service
    async def ask(self, given: Spoken[AskSaid], by: Codebase) -> Asked:
        """Ask the operator an agent's question, waiting on them until they answer it, and return its number."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            concern = inbox.thread(agent, given.said.thread)
            question = inbox.asked(
                agent, given.said.question, given.said.decisions, concern
            )
        return Asked(number=question.number or 0)

    @lup.service
    async def awaited(self, given: Spoken[Awaiting], by: Codebase) -> Awaited:
        """Hold until something settles an agent's question, the operator's answer or comment, or its withdrawal, at most `within`, and say what: what a held `ask` returns, told to the agent here rather than again at their next call.

        Raise `RefusedError` where it isn't a question of the agent's.
        """
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            question = inbox.item(str(given.said.question))
        if not isinstance(question, Question) or question.by != agent.key:
            message = f"@{given.said.question} isn't a question of yours"
            raise RefusedError(message, about=[str(given.said.question)])
        try:
            async with asyncio.timeout(given.said.within.total_seconds()):
                while (answers := inbox.settled_by(question)) is None:
                    await self.change().wait()
        except TimeoutError:
            return Awaited(
                settled=False,
                text=(
                    f"@{question.number} isn't answered yet: the operator's answer "
                    "reaches you at a later call."
                ),
            )
        inbox.tell(agent, [each for each in answers if not inbox.told(agent, each)])
        return Awaited(settled=True, text=inbox.answer_said(question, answers))

    @lup.service
    async def spoke(self, given: Spoken[Uttered], by: Codebase) -> str:
        """Keep an agent's own words of a kind: how it felt, a block, a stop, a turn's end."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        text = given.said.text
        match given.said.kind:
            case "how it felt":
                item: Item = inbox.felt(agent, text)
            case "blocked":
                item = inbox.blocked(agent, text)
            case "stop":
                item = inbox.stopped(agent, text)
            case "turn's end":
                item = inbox.turn_ended(agent, text)
        return f"Kept, @{item.number}."

    @lup.service
    async def withdraw(self, given: Spoken[WithdrawSaid], by: Codebase) -> str:
        """Take back an item an agent sent, saying why."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            inbox.withdrawn(agent, inbox.item(str(given.said.item)), given.said.why)
        return f"Withdrew @{given.said.item}."

    @lup.service
    async def read(self, given: Spoken[Reading], by: Codebase) -> str:
        """Read the inbox, changing nothing: one item or concern whole, or what stands."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            return inbox.read(agent, given.said.number, given.said.part)

    @lup.service
    async def standing(self, given: Nothing, by: Codebase) -> Inboxed:
        """Read the repository's inbox as data, changing nothing."""
        del given
        return self.inbox(by.repository).inboxed()

    @lup.tool(reads=True)
    async def everywhere(self, nothing: Nothing, by: Operator) -> Everywhere:
        """Read every repository's inbox as data.

        Where each concern stands, what waits on the operator, what's new to
        them, what's been told, and the operator's comments. Yours alone, since
        it holds every project's exchange with you.
        """
        del nothing, by
        database = self.opened()
        if self.state is None or self.state_at != database.writes:
            self.state = Everywhere(
                inboxes=[
                    self.inbox(repository).inboxed()
                    for repository in database.repositories()
                ]
            )
            self.state_at = database.writes
        return self.state

    @lup.service
    async def said(self, given: Since, by: Machine) -> SaidSince:
        """Read every item kept since `given`'s key, every repository's, in the order kept: each with who said it, its words whole, and what it's on, as a search reads them."""
        del by
        database = self.opened()
        items = [each for each in database.every(Item) if each.key > given.after]
        return SaidSince(
            items=[self.inbox(each.repository).as_said(each) for each in items],
            last=max((each.key for each in items), default=given.after),
        )

    # What sessions say, from the machine's own part holding them

    @lup.service
    async def told(self, given: Ending, by: Machine) -> Told:
        """Tell an agent each item for them not told yet, once: what reaches them at their next call."""
        del by
        inbox = self.inbox(given.repository)
        agent = inbox.agent(given.agent)
        items = inbox.taken(agent)
        return Told(
            items=[
                ToldItem(
                    number=each.number or 0,
                    by=inbox.writer(each),
                    kind=each.kind,
                    text=inbox.told_as(each, agent),
                    on=inbox.on(each),
                )
                for each in items
            ]
        )

    @lup.service
    async def untold(self, given: Untelling, by: Machine) -> Untold:
        """List each agent of a repository who has something not yet told them: whom a session wakes, or starts again."""
        del by
        inbox = self.inbox(given.repository)
        return Untold(
            agents=[each.caller() for each in inbox.agents() if inbox.untold(each)]
        )

    @lup.service
    async def turn_ended(self, given: Ended, by: Machine) -> str:
        """Keep an agent's last words of a turn, answering what the operator told them since their last."""
        del by
        inbox = self.inbox(given.repository)
        item = inbox.turn_ended(inbox.agent(given.agent), given.text)
        return f"Kept, @{item.number}."

    @lup.service
    async def agent_named(self, given: Naming, by: Machine) -> None:
        """Name an agent, as their session says its name, under the agent who spawned them where one did."""
        del by
        inbox = self.inbox(given.repository)
        spawner = None if given.spawner is None else inbox.agent(given.spawner)
        with refusing():
            inbox.agent(given.agent, given.name, spawner)

    @lup.service
    async def agent_ended(self, given: Ending, by: Machine) -> None:
        """Say an agent's session ended: what they held reads as in `no-agent` until they start again."""
        del by
        inbox = self.inbox(given.repository)
        inbox.end(inbox.agent(given.agent))

    @lup.service
    async def agent_started(self, given: Ending, by: Machine) -> None:
        """Say an agent started again: what they held is theirs again."""
        del by
        inbox = self.inbox(given.repository)
        inbox.start(inbox.agent(given.agent))

    # What modules say, in their own kinds of item

    @lup.service
    async def post(self, given: Posting, by: Machine | Codebase) -> Posted:
        """Keep an item of a module's own kind, said by an agent to the operator in the concern the agent works in, and return its number: it waits on the operator as its kind says, laid out as its kind says, until the module settles it or the operator comments on it.

        Raise `RefusedError` where its kind is the inbox's own or no module's, where its fields aren't its kind's, or, called by a project's code, where it names another repository than the project's.
        """
        kind = self.opened().kinds.node(given.kind)
        if not issubclass(kind, Item) or kind in NODES:
            message = (
                f"`{given.kind}` isn't a module's own kind of item: a module "
                "declares one in its `Recorded`, deriving from `Item`"
            )
            raise RefusedError(message)
        theirs(by, given.repository)
        inbox = self.inbox(given.repository)
        with refusing():
            kept = inbox.posted(inbox.agent(given.by), kind, given.text, given.fields)
        return Posted(number=kept.number or 0)

    @lup.service
    async def settle(self, given: Settling, by: Machine | Codebase) -> None:
        """Say what came of an item of a module's own kind, for the operator's act: told to whoever wrote it, at their next call, and answering it, so it waits no more.

        Raise `RefusedError` where the item isn't one of a module's own kind, or, called by a project's code, where it's another repository's than the project's.
        """
        theirs(by, given.repository)
        inbox = self.inbox(given.repository)
        with refusing():
            item = inbox.item(str(given.item))
            if type(item) in NODES:
                message = (
                    f"@{given.item} is the inbox's own kind of item, which a "
                    "module doesn't settle"
                )
                raise InboxError(message, about=[str(given.item)])
            inbox.settled(item, given.text)

    # The operator's acts

    @lup.command
    async def answer(self, answering: Answering, by: Operator) -> QuestionAnswered:
        """Answer a question: a ruling on each decision, your words.

        Each decision gets its ruling, and your words go with them.
        """
        del by
        with refusing():
            question = self.numbered(answering.question, Question)
            inbox = self.inbox(question.repository)
            answer = inbox.answered(question, answering.rulings, answering.text)
        return QuestionAnswered(
            question=question.number or 0, answer=answer.number or 0
        )

    @lup.command(verb="comment", says="comment on it")
    async def comment(self, commented: Commented[OnItem], by: Operator) -> CommentKept:
        """Keep your comment on an item, or on a part of it.

        It reaches whoever wrote the item, and each party it was for.
        """
        del by
        with refusing():
            item = self.numbered(commented.on.item, Item)
            inbox = self.inbox(item.repository)
            comment = inbox.commented(item, commented, commented.on.part)
        return CommentKept(item=item.number or 0, comment=comment.number or 0)

    @lup.command(verb="comment", says="comment to them")
    async def comment_to(self, commented: Commented[Reached], by: Operator) -> SentTo:
        """Keep your comment for the party a block reaches.

        For a block that offers no comment of its own: the party it reaches is
        an agent, or a pile, where the comment opens a concern.
        """
        del by
        with refusing():
            found = self.reached(commented.on.party)
            inbox = self.inbox(found.repository)
            comment = inbox.told_party(found, commented)
        return SentTo(to=inbox.called(found), comment=comment.number or 0)

    @lup.command
    async def tell(self, addressing: Addressing, by: Operator) -> SentTo:
        """Send your words to an agent, or to a pile.

        A pile keeps them as a concern it opens.
        """
        del by
        inbox = self.inbox(addressing.repository)
        with refusing():
            party = inbox.party(addressing.to)
            comment = inbox.told_party(party, Commenting(words=addressing.text))
        return SentTo(to=inbox.called(party), comment=comment.number or 0)

    @lup.command(verb="done", says="clear it")
    async def clear(self, clearing: Clearing, by: Operator) -> NodeCleared:
        """Clear an item, a concern, or a party's buffer whole.

        It stays cleared until something new happens there.
        """
        del by
        inbox = self.inbox(clearing.repository)
        with refusing():
            found = inbox.cited(clearing.what)
            if isinstance(found, ItemPart):
                message = f"{found.cited()} is a part of an item: clear the item whole"
                raise InboxError(message, about=[clearing.what])
            inbox.cleared(found)
        return NodeCleared(what=clearing.what)

    @lup.command(verb="decline", says="decline it")
    async def decline(self, declining: Declining, by: Operator) -> ConcernDeclined:
        """Decline a concern, saying why.

        Nothing more will be done about it.
        """
        del by
        with refusing():
            concern = self.numbered(declining.concern, Concern)
            self.inbox(concern.repository).declined(concern, declining.why)
        return ConcernDeclined(concern=concern.number or 0)

    @lup.command
    async def pile(self, piling: Piling, by: Operator) -> PileMade:
        """Make a pile by its path, and each pile above it.

        Each pile above it that isn't there yet is made too.
        """
        del by
        inbox = self.inbox(piling.repository)
        with refusing():
            made = inbox.pile(piling.path, inbox.operator())
        return PileMade(pile=inbox.called(made))

    @lup.command
    async def convert(self, converting: Converting, by: Operator) -> Converted:
        """Bring frictions and concerns over from the second lup.

        From its ledger, once: each a friction or a concern by the tool its
        first words were filed with, with its title, bodies, place, holder,
        done mark and the words filed in it; the agents who held or wrote them
        read as ended, so what they held waits in `no-agent`, saying who left
        it, until they start here.
        """
        del by
        # lup: defer(issue=13, why="the second lup's ledger is read once, at the switch, and the command goes with the second lup")
        inbox = self.inbox(converting.repository)
        with refusing():
            ledger = conversion.read(converting.ledger, converting.named)
            return conversion.converted(inbox, ledger)

    @lup.command(verb="seen", says="seen")
    async def shown(self, showing: Showing, by: Operator) -> ItemsSeen:
        """Say what's been on your screen.

        Each item isn't new to you after, and stays where it is until you
        clear it.
        """
        del by
        with refusing():
            items = [self.numbered(each, Item) for each in showing.items]
        for repository in dict.fromkeys(each.repository for each in items):
            self.inbox(repository).shown(
                [each for each in items if each.repository == repository]
            )
        return ItemsSeen(count=len(items), items=showing.items)

    # What the operator reads

    def shows(self) -> Shows:
        """Return the inbox's views a block opens."""
        return Shows(
            party=Inboxes.party,
            concern=Inboxes.concern_view,
            comment=Inboxes.comment,
            clear=Inboxes.clear,
            decline=Inboxes.decline,
            seen=Inboxes.shown,
        )

    @lup.view
    async def parties(self, of: PartiesOf) -> Blocks:
        """Show a repository's parties, each opening on its buffer.

        Each agent no other spawned, and each pile at the top.
        """
        return views.parties(self.inbox(of.repository), self.shows())

    @lup.view
    async def party(self, of: PartyOf) -> Blocks:
        """Show a party's buffer.

        The concerns it holds, the parties under it, and what it said or was
        told outside any concern.
        """
        inbox = self.inbox(of.repository)
        with refusing():
            found = inbox.party(of.name)
        return views.buffer(inbox, found, self.shows())

    @lup.view
    async def concern_view(self, of: ConcernOf) -> Blocks:
        """Show a concern whole.

        Its body, the concerns under it, and what's been said in it.
        """
        with refusing():
            found = self.numbered(of.number, Concern)
        return views.concern(self.inbox(found.repository), found, self.shows())

    @lup.view
    async def waiting(self, of: PartiesOf) -> Blocks:
        """Show what waits on you.

        Each item you're to answer, then each concern its agent says is done.
        """
        return views.waiting(self.inbox(of.repository), self.shows())

    def reached(self, party: Agent | Pile) -> PartyRecord:
        """Return the record of the party a block's comment reaches: the pile at its path in its repository, or the agent lup knows by its id, in whichever repository they're of; raise `InboxError` where none is."""
        database = self.opened()
        match party:
            case Pile(repository=repository, path=path):
                return self.inbox(repository).pile(path)
            case Agent(id=known_as):
                found = [
                    each for each in database.every(AgentRecord) if each.id == known_as
                ]
                if not found:
                    message = f"no agent is known by `{known_as}`"
                    raise InboxError(message, about=[known_as])
                return found[0]

    def numbered[N: Item | Concern](self, number: int, kind: type[N]) -> N:
        """Return the node cited `@number`, as `kind`; raise `InboxError` where none is."""
        found = self.opened().numbered(number)
        if not isinstance(found, kind):
            message = f"@{number} is no {kind.__name__.lower()}"
            raise InboxError(message, about=[str(number)])
        return found


class Speaking(Part):
    """What an agent says to the operator and to other parties: their tools, each kept by `Inboxes`."""

    @lup.tool
    async def concern(self, said: ConcernSaid, by: Agent) -> str:
        """Say what's worth keeping an eye on.

        Whenever something's worth keeping an eye on, the moment it comes up,
        even if you'll never work on it: a line is enough, and nobody will ask
        you to finish it. With no `name`, `text` opens a concern under the one
        you work in, else under you. With `name`, what you give says one thing
        of it: `text` adds your words, `body` rewrites what you understand of
        it, `join` works in it, `hold` takes it, `hand` passes it on, `move`
        puts items in it, `done` says it's done for the operator to clear.
        """
        return await Inboxes.concern(Spoken(agent=by, said=said))

    @lup.tool
    async def friction(self, said: FrictionSaid, by: Agent) -> str:
        """Say what got in your way.

        The moment something gets in the way of the work, whatever it is, in
        your own words. It's feedback, kept as a friction where you send it:
        `frictions` unless you name a pile or an agent.
        """
        return await Inboxes.friction(Spoken(agent=by, said=said))

    @lup.tool
    async def note(self, said: NoteSaid, by: Agent) -> str:
        """Tell the operator a doubt, and carry on.

        An assumption your work rests on, a doubt, or a counterargument: news
        they read when they come to it.
        """
        return await Inboxes.note(Spoken(agent=by, said=said))

    @lup.tool
    async def send(self, said: SendSaid, by: Agent) -> str:
        """Send a message to a party.

        To the operator, an agent by their name, or a pile, where it opens a
        concern. A note is news; a problem, a disagreement or a question wants
        its reader's answer. The operator reads every message.
        """
        return await Inboxes.send(Spoken(agent=by, said=said))

    @lup.tool
    async def ask(self, said: AskSaid, by: Agent) -> str:
        """Ask the operator, with numbered decisions.

        Each decision with your lean; or a question answered in words. The call
        holds until they answer, and returns their answer, so you don't build
        on your leans before they've said; with `wait` false, it returns at
        once, and their answer reaches you at a later call.
        """
        asked = await Inboxes.ask(Spoken(agent=by, said=said))
        if not said.wait:
            return (
                f"Your question is @{asked.number}, waiting on the operator: their "
                "answer reaches you at a later call."
            )
        awaited = await Inboxes.awaited(
            Spoken(agent=by, said=Awaiting(question=asked.number))
        )
        return awaited.text

    @lup.tool
    async def how_it_felt(self, said: Words, by: Agent) -> str:
        """Note how it is for you.

        In your own words: the work, the tools, lup, the people you worked with,
        the operator among them, each named as such. Write it as you'd write
        your own notes, or to the operator directly, whichever is truer for
        you. What didn't sit right is as welcome as what did: an unclear ask, a
        reversal, the pace, being interrupted, being made to relay. The
        operator reads every one, for a sense of how the work is for you, and
        doesn't answer it here: what needs their eyes soon is a `note`. Whenever
        something's present for you, and once near the end of a piece of work.
        "Nothing notable" is a fine answer.
        """
        return await Inboxes.spoke(
            Spoken(agent=by, said=Uttered(kind="how it felt", text=said.text))
        )

    @lup.tool
    async def blocked(self, said: Words, by: Agent) -> str:
        """Say the work can't go on, and what's wrong.

        It waits on the operator until they answer it.
        """
        return await Inboxes.spoke(
            Spoken(agent=by, said=Uttered(kind="blocked", text=said.text))
        )

    @lup.tool
    async def stop(self, said: Words, by: Agent) -> str:
        """End your work by your own choice, saying why."""
        return await Inboxes.spoke(
            Spoken(agent=by, said=Uttered(kind="stop", text=said.text))
        )

    @lup.tool
    async def withdraw(self, said: WithdrawSaid, by: Agent) -> str:
        """Take back an item the operator needn't see.

        A message or a question you sent that needn't take their time, with why.
        """
        return await Inboxes.withdraw(Spoken(agent=by, said=said))

    @lup.tool(reads=True)
    async def inbox(self, said: Reading, by: Agent) -> str:
        """Read the repository's inbox, changing nothing.

        With `number`, one item or concern whole; without, what waits on the
        operator and the concerns you hold.
        """
        return await Inboxes.read(Spoken(agent=by, said=said))


def theirs(by: Machine | Codebase, repository: str) -> None:
    """Refuse a project's code naming another repository than its own: the machine names any."""
    if isinstance(by, Codebase) and by.repository != repository:
        message = (
            f"{by.repository}'s code can't say what's kept in {repository}'s inbox"
        )
        raise RefusedError(message, about=[repository])


@contextmanager
def refusing() -> Generator[None]:
    """Turn what the inbox can't do into a refusal of the call, said to whoever called it, rather than an error of lup's."""
    try:
        yield
    except StoreError as refused:
        raise RefusedError(str(refused)) from refused
