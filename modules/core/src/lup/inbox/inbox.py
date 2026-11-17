"""The inbox of one repository: its parties, the concerns they hold, what's said between them, and where each stands.

Every act is kept in the store as nodes and edges (`lup.inbox.records`), and
every reading is made from them when it's asked, so nothing says where a thing
stands but the edges drawn to it (`README.md` here). What came after what is the
store's order, an item's key and an edge's place, never a time: a clearing
stays until an item newer than the newest it cleared, and an agent's "done"
until an item newer than the newest they said it after.
"""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from lup.inbox.records import (
    AgentParty,
    Answer,
    Answers,
    Blocked,
    Cleared,
    Comment,
    Concern,
    Decision,
    Declined,
    Done,
    Ended,
    Felt,
    Friction,
    In,
    Item,
    Message,
    OperatorParty,
    Party,
    Pile,
    Question,
    Ruling,
    Shown,
    Started,
    Stopped,
    Told,
    Tone,
    TurnEnd,
    Under,
    Withdrawn,
    WorksIn,
)
from lup.store.database import Database
from lup.store.errors import StoreError
from lup.store.records import Edge, Node
from lup.types import Model

if TYPE_CHECKING:
    from pydantic import JsonValue

NO_AGENT = "no-agent"
"""The pile where what an ended agent held reads as being, each concern saying who left it."""

FRICTIONS = "frictions"
"""The pile a friction lands in where its agent names no other."""


class InboxError(StoreError):
    """The inbox can't do what it was asked: a party, a concern or an item it doesn't hold, or an act its kind refuses."""


class Standing(Model):
    """Where a concern stands, read from the edges drawn to it and the items said in it."""

    holder: Party
    """Who holds it: the party it's under, or that its nearest parent concern is under."""
    left_by: AgentParty | None = None
    """The agent who held it and has ended, where it reads as in `No agent`."""
    done: str | None = None
    """What its agent said of it being done, where they did and nothing's been said in it since."""
    cleared: bool = False
    """Whether the operator cleared it, and nothing's been said in it since."""
    declined: str | None = None
    """Why the operator declined it, where they did: nothing more will be done about it."""

    def waits(self) -> bool:
        """Say whether it waits on the operator: its agent says it's done, and the operator hasn't cleared or declined it since."""
        return self.done is not None and not self.cleared and self.declined is None


class Inbox(Model, arbitrary_types_allowed=True):
    """The inbox of `repository`, kept in `database`.

    >>> from lup.inbox.records import KINDS
    >>> inbox = Inbox(database=Database.opened(":memory:", KINDS), repository="lup")
    >>> agent = inbox.agent("a1", "builder")
    >>> concern = inbox.opened(agent, "the gate hangs", "It hung twice today.", agent)
    >>> inbox.standing(concern).holder == agent, [each.text for each in inbox.said_in(concern)]
    (True, ['It hung twice today.'])
    """

    database: Database
    repository: str

    def now(self) -> datetime:
        """Say when an act happens: the time a record of it carries, which says when and never decides an order."""
        return datetime.now(UTC)

    def edge[E: Edge](
        self,
        kind: type[E],
        target: Node,
        source: Node | None,
        by: Party | None,
        **fields: JsonValue,
    ) -> E:
        """Draw an edge of `kind` to `target`, from `source` where it has one, written by `by` (lup where none), and return it."""
        return self.database.drawn(
            kind.model_validate(
                {
                    "repository": self.repository,
                    "by": None if by is None else by.name,
                    "at": self.now(),
                    "target": target.key,
                    "source": None if source is None else source.key,
                    **fields,
                }
            )
        )

    # Parties

    def operator(self) -> OperatorParty:
        """Return the operator, as a party of the repository, made the first time it's needed."""
        found = self.database.named(self.repository, "operator")
        if isinstance(found, OperatorParty):
            return found
        return self.database.kept(
            OperatorParty(repository=self.repository, by=None, at=self.now())
        )

    def agent(
        self, known_as: str, name: str, spawner: AgentParty | None = None
    ) -> AgentParty:
        """Return the agent lup knows by the id `known_as`, named `name`, under `spawner` where they have one: made the first time, renamed where their name changed."""
        known = next(
            (
                each
                for each in self.database.nodes(self.repository, AgentParty)
                if each.id == known_as
            ),
            None,
        )
        if known is not None:
            if known.name == name:
                return known
            return self.database.kept(
                known.model_copy(update={"name": name, "at": self.now()})
            )
        made = self.database.kept(
            AgentParty(
                repository=self.repository,
                by=None,
                at=self.now(),
                name=name,
                id=known_as,
            )
        )
        if spawner is not None:
            self.edge(Under, spawner, made, None)
        return made

    def party(self, name: str) -> Party:
        """Return the party named `name`, `@` before it or not; raise `InboxError` where none is."""
        found = self.database.named(self.repository, name.removeprefix("@"))
        if not isinstance(found, Party):
            message = f"no party of {self.repository} is named `{name}`"
            raise InboxError(message, about=[name])
        return found

    def pile(self, path: str, by: Party | None = None) -> Pile:
        """Return the pile at `path` (`frictions/dashboard/keys`), making it, and each pile above it that isn't there yet, under its parent.

        A path's first segments may name a party there already, an agent among
        them, which the piles below go under.
        """
        found = self.database.named(self.repository, path)
        if isinstance(found, Pile):
            return found
        if found is not None:
            message = (
                f"`{path}` names a `{found.kind}` in {self.repository}, not a pile"
            )
            raise InboxError(message, about=[path])
        above = str(PurePosixPath(path).parent)
        parent = None if above == "." else self.party_or_pile(above, by)
        made = self.database.kept(
            Pile(
                repository=self.repository,
                by=None if by is None else by.name,
                at=self.now(),
                name=path,
            )
        )
        if parent is not None:
            self.edge(Under, parent, made, by)
        return made

    def party_or_pile(self, path: str, by: Party | None) -> Party:
        """Return the party at `path`, or a pile made there where nothing is."""
        found = self.database.named(self.repository, path)
        if isinstance(found, Party):
            return found
        return self.pile(path, by)

    def ended(self, agent: AgentParty) -> bool:
        """Say whether `agent` has ended: their latest `Ended` or `Started` is an `Ended`."""
        marks = [
            each
            for each in self.database.drawn_to(agent.key, Edge)
            if isinstance(each, Ended | Started)
        ]
        return bool(marks) and isinstance(marks[-1], Ended)

    def end(self, agent: AgentParty) -> None:
        """Say `agent` ended: what they held reads as in `No agent` until they start again."""
        self.edge(Ended, agent, None, None)

    def start(self, agent: AgentParty) -> None:
        """Say `agent` started again: what they held is theirs again."""
        self.edge(Started, agent, None, None)

    def under(self, node: Node) -> Node | None:
        """Return what `node` is under, its latest `Under`; none where it's at the top."""
        places = self.database.drawn_from(node.key, Under, current=True)
        return None if not places else self.database.found(places[-1].target)

    def parties(self) -> list[Party]:
        """Return every party of the repository, in the order made."""
        return self.database.nodes(self.repository, Party)

    # Concerns

    def opened(
        self,
        by: Party,
        title: str,
        words: str,
        under: Party | Concern,
        *,
        friction: bool = False,
    ) -> Concern:
        """Open a concern titled `title`, under `under`, with `by`'s `words` its first item, told to the operator: a `Friction` where `friction` says so."""
        kind = Friction if friction else Concern
        concern = self.database.kept(
            kind(repository=self.repository, by=by.name, at=self.now(), title=title)
        )
        self.edge(Under, under, concern, by)
        self.said(by, concern, words)
        return concern

    def said(
        self, by: Party, concern: Concern, words: str, tone: Tone = "note"
    ) -> Message:
        """Keep `by`'s `words` in `concern`, told to the operator, and return them."""
        message = self.database.kept(
            Message(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=words,
                tone=tone,
            )
        )
        self.edge(In, concern, message, by)
        return message

    def concern(self, cited: str) -> Concern:
        """Return the concern `cited` names, by its number or its name, `@` before it or not; raise `InboxError` where none is."""
        bare = cited.removeprefix("@")
        found = (
            self.database.numbered(int(bare))
            if bare.isdigit()
            else self.database.named(self.repository, bare)
        )
        if not isinstance(found, Concern):
            message = f"no concern of {self.repository} is `{cited}`"
            raise InboxError(message, about=[cited])
        return found

    def rewritten(self, by: Party, concern: Concern, body: str) -> Concern:
        """Rewrite `concern`'s body whole, as `by` understands it, its body before kept as an earlier version."""
        return self.database.kept(
            concern.model_copy(update={"body": body, "by": by.name, "at": self.now()})
        )

    def moved(self, by: Party, concern: Concern, to: Party | Concern) -> None:
        """Move `concern` under `to`: it's in one place, where it's moved."""
        self.edge(Under, to, concern, by)

    def done(self, by: AgentParty, concern: Concern, said: str) -> None:
        """Say, for `by`, that `concern` is done: what's done, what isn't, and what to try, for the operator to clear."""
        self.edge(Done, concern, by, by, said=said, newest=self.newest(concern))

    def cleared(self, node: Node) -> None:
        """Clear `node`, for the operator: an item, a concern, or a party's buffer whole, until something new happens in it."""
        newest = self.newest(node) if isinstance(node, Concern) else node.key
        self.edge(Cleared, node, self.operator(), self.operator(), newest=newest)

    def declined(self, concern: Concern, why: str) -> None:
        """Decline `concern`, for the operator, saying why: nothing more will be done about it."""
        self.edge(Declined, concern, self.operator(), self.operator(), why=why)

    def works_in(self, agent: AgentParty, concern: Concern) -> None:
        """Have `agent` work in `concern`: what they say without naming another lands there."""
        self.edge(WorksIn, concern, agent, agent)

    def working_in(self, agent: AgentParty) -> Concern | None:
        """Return the concern `agent` works in; none where they work in none."""
        places = self.database.drawn_from(agent.key, WorksIn, current=True)
        found = None if not places else self.database.found(places[-1].target)
        return found if isinstance(found, Concern) else None

    def said_in(self, concern: Concern) -> list[Item]:
        """Return each item in `concern`, oldest first."""
        keys = [
            each.source
            for each in self.database.drawn_to(concern.key, In, current=True)
            if each.source is not None
        ]
        return [
            found for key in keys if isinstance(found := self.database.found(key), Item)
        ]

    def newest(self, concern: Concern) -> int:
        """Return the key of the newest item in `concern`, 0 where none is."""
        return max((each.key for each in self.said_in(concern)), default=0)

    def held(self, party: Party) -> list[Concern]:
        """Return each concern right under `party`, as the store holds them, oldest first."""
        keys = [
            each.source
            for each in self.database.drawn_to(party.key, Under, current=True)
            if each.source is not None
        ]
        return [
            found
            for key in keys
            if isinstance(found := self.database.found(key), Concern)
        ]

    def holder(self, concern: Concern) -> Party:
        """Return the party `concern` is under, or its nearest parent concern is under."""
        place = self.under(concern)
        match place:
            case Party():
                return place
            case Concern():
                return self.holder(place)
            case _:
                return self.pile(NO_AGENT)

    def standing(self, concern: Concern) -> Standing:
        """Read where `concern` stands, from the edges drawn to it and what's been said in it."""
        holder = self.holder(concern)
        left_by = (
            holder if isinstance(holder, AgentParty) and self.ended(holder) else None
        )
        newest = self.newest(concern)
        edges = self.database.drawn_to(concern.key, Edge)
        done = [each for each in edges if isinstance(each, Done)]
        cleared = [each for each in edges if isinstance(each, Cleared)]
        declined = [each for each in edges if isinstance(each, Declined)]
        return Standing(
            holder=self.pile(NO_AGENT) if left_by is not None else holder,
            left_by=left_by,
            done=done[-1].said if done and done[-1].newest >= newest else None,
            cleared=bool(cleared) and cleared[-1].newest >= newest,
            declined=declined[-1].why if declined else None,
        )

    # Items

    def sent(
        self,
        by: Party,
        to: list[Party],
        text: str,
        tone: Tone = "note",
        concern: Concern | None = None,
    ) -> Message:
        """Send `by`'s `text` to `to`, of `tone`, in `concern` where it's said in one, and return it."""
        message = self.database.kept(
            Message(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[each.key for each in to],
                text=text,
                tone=tone,
            )
        )
        if concern is not None:
            self.edge(In, concern, message, by)
        return message

    def asked(
        self,
        by: AgentParty,
        text: str,
        decisions: list[Decision],
        concern: Concern | None = None,
    ) -> Question:
        """Ask the operator `text`, with `decisions`, each with `by`'s lean, and return the question."""
        question = self.database.kept(
            Question(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=text,
                decisions=decisions,
            )
        )
        if concern is not None:
            self.edge(In, concern, question, by)
        return question

    def answered(self, question: Question, rulings: list[Ruling], text: str) -> Answer:
        """Answer `question`, for the operator: a ruling on each decision and their words, told to whoever asked."""
        asker = self.party(question.by or "operator")
        answer = self.database.kept(
            Answer(
                repository=self.repository,
                by="operator",
                at=self.now(),
                to=[asker.key],
                text=text,
                rulings=rulings,
            )
        )
        self.edge(Answers, question, answer, self.operator())
        return answer

    def commented(
        self, on: Item, text: str, part: int | None = None, quote: str = ""
    ) -> Comment:
        """Comment on `on`, or a part of it, for the operator: told to whoever wrote it, and to each it was for where an agent wrote it to another."""
        operator = self.operator()
        writer = [] if on.by is None or on.by == "operator" else [self.party(on.by).key]
        readers = [each for each in on.to if each != operator.key]
        comment = self.database.kept(
            Comment(
                repository=self.repository,
                by="operator",
                at=self.now(),
                to=list(dict.fromkeys([*writer, *readers])),
                text=text,
                on=on.key,
                part=part,
                quote=quote,
            )
        )
        self.edge(Answers, on, comment, operator, part=part)
        return comment

    def told_party(self, party: Party, text: str) -> Comment:
        """Send the operator's `text` to `party` alone: to an agent, or to a pile, where it opens a concern."""
        if isinstance(party, Pile):
            self.opened(self.operator(), first_line(text), text, party)
        return self.database.kept(
            Comment(
                repository=self.repository,
                by="operator",
                at=self.now(),
                to=[party.key],
                text=text,
            )
        )

    def felt(self, by: AgentParty, text: str) -> Felt:
        """Keep how it is for `by`, in their words, told to the operator."""
        return self.database.kept(
            Felt(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def blocked(self, by: AgentParty, text: str) -> Blocked:
        """Keep `by`'s word that their work can't go on, waiting on the operator."""
        return self.database.kept(
            Blocked(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def stopped(self, by: AgentParty, text: str) -> Stopped:
        """Keep `by`'s word that they ended their work by their own choice."""
        return self.database.kept(
            Stopped(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def turn_ended(self, by: AgentParty, text: str) -> TurnEnd:
        """Keep `by`'s last words of a turn, answering each of the operator's items told to them since their last turn's end."""
        end = self.database.kept(
            TurnEnd(
                repository=self.repository,
                by=by.name,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )
        operator = self.operator()
        ends = [
            each
            for each in self.database.nodes(self.repository, TurnEnd)
            if each.by == by.name and each.key != end.key
        ]
        since = ends[-1].key if ends else 0
        for told in self.told_to(by):
            if told.key > since and told.by == operator.name:
                self.edge(Answers, told, end, by)
        return end

    def withdrawn(self, by: AgentParty, item: Item, why: str) -> None:
        """Take back `by`'s `item`, saying why: it waits on nobody after."""
        if item.by != by.name:
            message = f"@{item.number} is {item.by}'s, not {by.name}'s, to withdraw"
            raise InboxError(message, about=[str(item.number)])
        self.edge(Withdrawn, item, by, by, why=why)

    def item(self, cited: str) -> Item:
        """Return the item `cited` names by its number, `@` before it or not; raise `InboxError` where none is."""
        bare = cited.removeprefix("@")
        found = self.database.numbered(int(bare)) if bare.isdigit() else None
        if not isinstance(found, Item) or found.repository != self.repository:
            message = f"no item of {self.repository} is `{cited}`"
            raise InboxError(message, about=[cited])
        return found

    # What stands

    def answered_by(self, item: Item) -> list[Item]:
        """Return each item answering `item`, oldest first."""
        keys = [
            each.source
            for each in self.database.drawn_to(item.key, Answers)
            if each.source is not None
        ]
        return [
            found for key in keys if isinstance(found := self.database.found(key), Item)
        ]

    def waits_on_operator(self) -> list[Item | Concern]:
        """Return what waits on the operator, oldest first: each item for them whose kind waits, answered by nobody it was for and not withdrawn; then each concern an agent says is done, not cleared or declined since."""
        operator = self.operator()
        items: list[Item | Concern] = [
            each
            for each in self.database.nodes(self.repository, Item)
            if operator.key in each.to
            and each.waits()
            and not self.answered_by(each)
            and not any(
                isinstance(edge, Withdrawn)
                for edge in self.database.drawn_to(each.key, Edge)
            )
        ]
        concerns = [
            each
            for each in self.database.nodes(self.repository, Concern)
            if self.standing(each).waits()
        ]
        return [*items, *concerns]

    def new_to_operator(self) -> list[Item]:
        """Return each item the operator hasn't had on their screen, nor cleared, oldest first: whoever it was for, since they read every exchange."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if each.by != "operator"
            and not any(
                isinstance(edge, Shown | Cleared)
                for edge in self.database.drawn_to(each.key, Edge)
            )
        ]

    def shown(self, items: list[Item]) -> None:
        """Say `items` have been on the operator's screen: none of them is new to them after."""
        operator = self.operator()
        for each in items:
            self.edge(Shown, each, operator, operator)

    def told_to(self, party: Party) -> list[Item]:
        """Return each item for `party` already told to them, oldest first."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if party.key in each.to and self.told(party, each)
        ]

    def told(self, party: Party, item: Item) -> bool:
        """Say whether `item` has been told to `party`."""
        return any(
            each.source == party.key for each in self.database.drawn_to(item.key, Told)
        )

    def untold(self, party: Party) -> list[Item]:
        """Return each item for `party` not yet told to them, oldest first: what reaches them at their next call."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if party.key in each.to and not self.told(party, each)
        ]

    def tell(self, party: Party, items: list[Item]) -> None:
        """Say `items` were told to `party`: each is told once, never again."""
        for each in items:
            if not self.told(party, each):
                self.edge(Told, each, party, None)


def first_line(text: str) -> str:
    r"""Return `text`'s first line, as a title where none was given.

    >>> first_line("The gate hangs\nIt hung twice.")
    'The gate hangs'
    """
    return next(iter(text.splitlines()), "")
