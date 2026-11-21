"""The inbox's parts: the one holding the store, which every act goes through, and the one speaking for agents.

`Inboxes` holds the store's database, one for the machine, since concerns cross
repositories and the operator reads every project's: what an agent says comes
to it as a service, called by its project's code, which lup vouches for, so the
repository an act is kept under is never one the caller names; what the
operator does comes to it as their actions and commands. `Speaking` is the
agents' side, in each project: their tools, each a service call on `Inboxes`
for the agent calling (`README.md` here, *Tools and acts*).
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

import lup
from lup.doors.door import RefusedError
from lup.doors.events import Stopping
from lup.doors.parties import Agent, Codebase, Machine, Operator
from lup.doors.parts import Data, Part
from lup.inbox import views
from lup.inbox.inbox import Inbox, InboxError, first_line
from lup.inbox.records import (
    KINDS,
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
    AskSaid,
    Clearing,
    ConcernOf,
    ConcernSaid,
    Declining,
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
    Piling,
    Reached,
    Reading,
    SaidSince,
    SendSaid,
    Showing,
    Since,
    Spoken,
    Told,
    ToldItem,
    Uttered,
    WithdrawSaid,
    Words,
)
from lup.inbox.views import Shows
from lup.shell.blocks import Blocks
from lup.shell.draft import Commented, Commenting
from lup.store.database import Database
from lup.store.errors import StoreError

if TYPE_CHECKING:
    from collections.abc import Generator

DATABASE = "store.sqlite3"
"""The database's file, in the part's own directory."""


class Inboxes(Part, approved=True, shared=True):
    """The store's database and every repository's inbox kept in it, one for the machine: what's said and done goes through it."""

    data: Data
    """Where the database is kept, across restarts."""
    database: Database | None = None
    """The database, opened the first time it's needed."""
    state: Everywhere | None = None
    """Every repository's inbox as data, as last read: read again only once the database has taken a write since."""
    state_at: int = -1
    """How many writes the database had taken when `state` was read."""

    def opened(self) -> Database:
        """Return the database the inbox is kept in, opening it the first time: before anything else of the part runs, whatever order its start and its first call come in."""
        if self.database is None:
            self.database = Database.opened(self.data.path / DATABASE, KINDS)
        return self.database

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
    async def friction(self, given: Spoken[FrictionSaid], by: Codebase) -> str:
        """Keep what got in an agent's way as a friction, where they send it, and say where."""
        agent = self.inbox(by.repository).agent(given.agent)
        said = given.said
        with refusing():
            inbox = self.elsewhere(by.repository, said.repository)
            under = inbox.party_or_pile(said.under, agent)
            friction = inbox.opened(
                agent,
                said.title or first_line(said.text),
                said.text,
                under,
                friction=True,
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
    async def ask(self, given: Spoken[AskSaid], by: Codebase) -> str:
        """Ask the operator an agent's question, waiting on them until they answer it."""
        inbox = self.inbox(by.repository)
        agent = inbox.agent(given.agent)
        with refusing():
            concern = inbox.thread(agent, given.said.thread)
            question = inbox.asked(
                agent, given.said.question, given.said.decisions, concern
            )
        return f"Your question is @{question.number}, waiting on the operator."

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
            return inbox.read(agent, given.said.number)

    @lup.service
    async def standing(self, given: Nothing, by: Codebase) -> Inboxed:
        """Read the repository's inbox as data, changing nothing."""
        del given
        return self.inbox(by.repository).inboxed()

    @lup.tool(reads=True)
    async def everywhere(self, nothing: Nothing) -> Everywhere:
        """Read every repository's inbox as data.

        Where each concern stands, what waits on the operator, what's new to
        them, what's been told, and the operator's comments.
        """
        del nothing
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
    async def said(self, given: Since, by: Codebase | Machine) -> SaidSince:
        """Read every item kept since `given`'s key, every repository's, in the order kept: each with who said it, its words whole, and what it's on, as a search reads them."""
        del by
        database = self.opened()
        items = [each for each in database.every(Item) if each.key > given.after]
        return SaidSince(
            items=[self.inbox(each.repository).as_said(each) for each in items],
            last=max((each.key for each in items), default=given.after),
        )

    @lup.service
    async def told(self, given: Ending, by: Codebase) -> Told:
        """Tell an agent each item for them not told yet, once: what reaches them at their next call."""
        inbox = self.inbox(by.repository)
        items = inbox.taken(inbox.agent(given.agent))
        return Told(
            items=[
                ToldItem(
                    number=each.number or 0,
                    by=inbox.writer(each),
                    kind=each.kind,
                    text=each.text,
                )
                for each in items
            ]
        )

    @lup.service
    async def agent_named(self, given: Naming, by: Codebase) -> None:
        """Name an agent, as their session says its name, under the agent who spawned them where one did."""
        inbox = self.inbox(by.repository)
        spawner = None if given.spawner is None else inbox.agent(given.spawner)
        with refusing():
            inbox.agent(given.agent, given.name, spawner)

    @lup.service
    async def agent_ended(self, given: Ending, by: Codebase) -> None:
        """Say an agent's session ended: what they held reads as in `no-agent` until they start again."""
        inbox = self.inbox(by.repository)
        inbox.end(inbox.agent(given.agent))

    @lup.service
    async def agent_started(self, given: Ending, by: Codebase) -> None:
        """Say an agent started again: what they held is theirs again."""
        inbox = self.inbox(by.repository)
        inbox.start(inbox.agent(given.agent))

    # The operator's acts

    @lup.command
    async def answer(self, answering: Answering, by: Operator) -> str:
        """Answer a question: a ruling on each decision, and your words."""
        del by
        with refusing():
            question = self.numbered(answering.question, Question)
            inbox = self.inbox(question.repository)
            answer = inbox.answered(question, answering.rulings, answering.text)
        return f"Answered @{question.number}, @{answer.number}."

    @lup.command(verb="comment", says="comment on it")
    async def comment(self, commented: Commented[OnItem], by: Operator) -> str:
        """Keep your comment on an item, or a part of it: it reaches whoever wrote it, and each party it was for."""
        del by
        with refusing():
            item = self.numbered(commented.on.item, Item)
            inbox = self.inbox(item.repository)
            comment = inbox.commented(item, commented, commented.on.part)
        return f"Commented, @{comment.number}."

    @lup.command(verb="comment", says="comment to them")
    async def comment_to(self, commented: Commented[Reached], by: Operator) -> str:
        """Keep your comment on a block that offers none of its own, for the party it reaches: an agent, or a pile, where it opens a concern."""
        del by
        with refusing():
            found = self.reached(commented.on.party)
            inbox = self.inbox(found.repository)
            comment = inbox.told_party(found, commented)
        return f"Sent to {inbox.called(found)}, @{comment.number}."

    @lup.command
    async def tell(self, addressing: Addressing, by: Operator) -> str:
        """Send your words to a party: an agent, or a pile, where they open a concern."""
        del by
        inbox = self.inbox(addressing.repository)
        with refusing():
            party = inbox.party(addressing.to)
            comment = inbox.told_party(party, Commenting(words=addressing.text))
        return f"Sent to {inbox.called(party)}, @{comment.number}."

    @lup.command(verb="done", says="clear it")
    async def clear(self, clearing: Clearing, by: Operator) -> str:
        """Clear an item, a concern, or a party's buffer whole, until something new happens there."""
        del by
        inbox = self.inbox(clearing.repository)
        with refusing():
            node = inbox.cited(clearing.what)
            inbox.cleared(node)
        return f"Cleared {clearing.what}."

    @lup.command(verb="decline", says="decline it")
    async def decline(self, declining: Declining, by: Operator) -> str:
        """Decline a concern, saying why: nothing more will be done about it."""
        del by
        with refusing():
            concern = self.numbered(declining.concern, Concern)
            self.inbox(concern.repository).declined(concern, declining.why)
        return f"Declined @{concern.number}."

    @lup.command
    async def pile(self, piling: Piling, by: Operator) -> str:
        """Make a pile, by its path, and each pile above it not there yet."""
        del by
        inbox = self.inbox(piling.repository)
        with refusing():
            made = inbox.pile(piling.path, inbox.operator())
        return f"Made {inbox.called(made)}."

    @lup.command(verb="seen", says="seen")
    async def shown(self, showing: Showing, by: Operator) -> str:
        """Say what's been on your screen: each isn't new to you after, and stays where it is until you clear it."""
        del by
        with refusing():
            items = [self.numbered(each, Item) for each in showing.items]
        for repository in dict.fromkeys(each.repository for each in items):
            self.inbox(repository).shown(
                [each for each in items if each.repository == repository]
            )
        return f"{len(items)} shown."

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
        """Show a repository's parties: each agent no other spawned and each pile at the top, each opening on its buffer."""
        return views.parties(self.inbox(of.repository), self.shows())

    @lup.view
    async def party(self, of: PartyOf) -> Blocks:
        """Show a party's buffer: the concerns it holds, the parties under it, and what it said or was told outside any concern."""
        inbox = self.inbox(of.repository)
        with refusing():
            found = inbox.party(of.name)
        return views.buffer(inbox, found, self.shows())

    @lup.view
    async def concern_view(self, of: ConcernOf) -> Blocks:
        """Show a concern whole: its body, the concerns under it, and what's been said in it."""
        with refusing():
            found = self.numbered(of.number, Concern)
        return views.concern(self.inbox(found.repository), found, self.shows())

    @lup.view
    async def waiting(self, of: PartiesOf) -> Blocks:
        """Show what waits on you: each item you're to answer, then each concern its agent says is done."""
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

        Each decision with your lean; or a question answered in words. It waits
        on them until they answer it.
        """
        return await Inboxes.ask(Spoken(agent=by, said=said))

    @lup.tool
    async def how_it_felt(self, said: Words, by: Agent) -> str:
        """Tell the operator how it is for you.

        Whenever something's present for you, and once near the end of a piece
        of work, in your own words.
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


@contextmanager
def refusing() -> Generator[None]:
    """Turn what the inbox can't do into a refusal of the call, said to whoever called it, rather than an error of lup's."""
    try:
        yield
    except StoreError as refused:
        raise RefusedError(str(refused)) from refused
