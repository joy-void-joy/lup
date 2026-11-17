"""The inbox of one repository: its parties, the concerns they hold, what's said between them, and where each stands.

Every act is kept in the store as nodes and edges (`lup.inbox.records`), and
every reading is made from them when it's asked, so nothing says where a thing
stands but the edges drawn to it (`README.md` here). What came after what is the
store's order, an item's key and an edge's place, never a time: a clearing
stays until an item newer than the newest it cleared, and an agent's "done"
until an item newer than the newest they said it after.
"""

from datetime import UTC, datetime
from itertools import accumulate, groupby
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from lup.inbox.records import (
    NO_AGENT,
    AgentRecord,
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
    OperatorRecord,
    PartyRecord,
    PileRecord,
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
from lup.inbox.said import Comments, ConcernSaid, Inboxed, Placed, Telling
from lup.store.database import Database
from lup.store.errors import StoreError
from lup.store.records import Edge, Node, named
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import JsonValue


class InboxError(StoreError):
    """The inbox can't do what it was asked: a party, a concern or an item it doesn't hold, or an act its kind refuses."""


class Standing(Model):
    """Where a concern stands, read from the edges drawn to it and the items said in it."""

    holder: PartyRecord
    """Who holds it: the party it's under, or that its nearest parent concern is under."""
    left_by: AgentRecord | None = None
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
        by: PartyRecord | None,
        **fields: JsonValue,
    ) -> E:
        """Draw an edge of `kind` to `target`, from `source` where it has one, written by `by` (lup where none), and return it."""
        return self.database.drawn(
            kind.model_validate(
                {
                    "repository": self.repository,
                    "by": None if by is None else by.key,
                    "at": self.now(),
                    "target": target.key,
                    "source": None if source is None else source.key,
                    **fields,
                }
            )
        )

    # Parties

    def operator(self) -> OperatorRecord:
        """Return the operator, as a party of the repository, made the first time it's needed."""
        found = self.database.named(self.repository, "operator")
        if isinstance(found, OperatorRecord):
            return found
        return self.database.kept(
            OperatorRecord(repository=self.repository, by=None, at=self.now())
        )

    def agent(
        self,
        known_as: str,
        name: str | None = None,
        spawner: AgentRecord | None = None,
    ) -> AgentRecord:
        """Return the agent lup knows by the id `known_as`, under `spawner` where they have one: made the first time, and named `name` where a name is given, renamed where it changed.

        An agent lup hasn't named yet, as one whose session hasn't said its
        name, has none, and is found by their id. Raise `InboxError` where
        `name` isn't one a node can take, or another node holds it.
        """
        if name is not None:
            try:
                named(name)
            except ValueError as wrong:
                raise InboxError(str(wrong), about=[name]) from wrong
        known = next(
            (
                each
                for each in self.database.nodes(self.repository, AgentRecord)
                if each.id == known_as
            ),
            None,
        )
        if known is not None:
            if name is None or known.name == name:
                return known
            return self.database.kept(
                known.model_copy(update={"name": name, "at": self.now()})
            )
        made = self.database.kept(
            AgentRecord(
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

    def party(self, name: str) -> PartyRecord:
        """Return the party named `name`, `@` before it or not; raise `InboxError` where none is."""
        found = self.database.named(self.repository, name.removeprefix("@"))
        if not isinstance(found, PartyRecord):
            message = f"no party of {self.repository} is named `{name}`"
            raise InboxError(message, about=[name])
        return found

    def pile(self, path: str, by: PartyRecord | None = None) -> PileRecord:
        """Return the pile at `path` (`frictions/dashboard/keys`), making it, and each pile above it that isn't there yet, under its parent.

        A path's first segments may name a party there already, an agent among
        them, which the piles below go under.
        """
        try:
            named(path)
        except ValueError as wrong:
            raise InboxError(str(wrong), about=[path]) from wrong
        found = self.database.named(self.repository, path)
        if isinstance(found, PileRecord):
            return found
        if found is not None:
            message = (
                f"`{path}` names a `{found.kind}` in {self.repository}, not a pile"
            )
            raise InboxError(message, about=[path])
        above = str(PurePosixPath(path).parent)
        parent = None if above == "." else self.party_or_pile(above, by)
        made = self.database.kept(
            PileRecord(
                repository=self.repository,
                by=None if by is None else by.key,
                at=self.now(),
                name=path,
            )
        )
        if parent is not None:
            self.edge(Under, parent, made, by)
        return made

    def party_or_pile(self, path: str, by: PartyRecord | None) -> PartyRecord:
        """Return the party at `path`, or a pile made there where nothing is."""
        found = self.database.named(self.repository, path)
        if isinstance(found, PartyRecord):
            return found
        return self.pile(path, by)

    def ended(self, agent: AgentRecord) -> bool:
        """Say whether `agent` has ended: their latest `Ended` or `Started` is an `Ended`."""
        marks = [
            each
            for each in self.database.drawn_to(agent.key, Edge)
            if isinstance(each, Ended | Started)
        ]
        return bool(marks) and isinstance(marks[-1], Ended)

    def end(self, agent: AgentRecord) -> None:
        """Say `agent` ended: what they held reads as in `No agent` until they start again."""
        self.edge(Ended, agent, None, None)

    def start(self, agent: AgentRecord) -> None:
        """Say `agent` started again: what they held is theirs again."""
        self.edge(Started, agent, None, None)

    def under(self, node: Node) -> Node | None:
        """Return what `node` is under, its latest `Under`; none where it's at the top."""
        places = self.database.drawn_from(node.key, Under, current=True)
        return None if not places else self.database.found(places[-1].target)

    def parties(self) -> list[PartyRecord]:
        """Return every party of the repository, in the order made."""
        return self.database.nodes(self.repository, PartyRecord)

    # Concerns

    def opened(
        self,
        by: PartyRecord,
        title: str,
        words: str,
        under: PartyRecord | Concern,
        *,
        friction: bool = False,
        name: str | None = None,
    ) -> Concern:
        """Open a concern titled `title`, under `under`, with `by`'s `words` its first item, told to the operator: a `Friction` where `friction` says so.

        It's named `name`, or after its title where none is given (`slug`),
        with a number after where another node holds that name.
        """
        kind = Friction if friction else Concern
        concern = self.database.kept(
            kind(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                title=title,
                name=name or self.free(slug(title)),
            )
        )
        self.edge(Under, under, concern, by)
        self.said(by, concern, words)
        return concern

    def said(
        self, by: PartyRecord, concern: Concern, words: str, tone: Tone = "note"
    ) -> Message:
        """Keep `by`'s `words` in `concern`, told to the operator, and return them."""
        message = self.database.kept(
            Message(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                to=[self.operator().key],
                text=words,
                tone=tone,
            )
        )
        self.edge(In, concern, message, by)
        return message

    def free(self, name: str | None) -> str | None:
        """Return `name`, or `name` with the first number after it that no node of the repository holds; none for none."""
        if name is None:
            return None
        taken = self.database.named(self.repository, name)
        if taken is None:
            return name
        return next(
            candidate
            for count in range(2, 10_000)
            if self.database.named(self.repository, candidate := f"{name}-{count}")
            is None
        )

    def found_concern(self, cited: str) -> Concern | None:
        """Return the concern `cited` names, by its number or its name; none where none is."""
        bare = cited.removeprefix("@")
        found = (
            self.database.numbered(int(bare))
            if bare.isdigit()
            else self.database.named(self.repository, bare)
        )
        return found if isinstance(found, Concern) else None

    def cited(self, what: str) -> Node:
        """Return what `what` names: an item or a concern by its number, or a party or a concern by its name; raise `InboxError` where nothing is."""
        bare = what.removeprefix("@")
        found = (
            self.database.numbered(int(bare))
            if bare.isdigit()
            else self.database.named(self.repository, bare)
        )
        if found is None:
            message = f"nothing of {self.repository} is `{what}`"
            raise InboxError(message, about=[what])
        return found

    def place(self, agent: AgentRecord, under: str | None) -> PartyRecord | Concern:
        """Return where `agent` puts what they open: the party or concern `under` names, else the concern they work in, else themselves."""
        if under is None:
            return self.working_in(agent) or agent
        found = self.cited(under)
        if not isinstance(found, PartyRecord | Concern):
            message = f"`{under}` is no party nor concern: nothing goes under it"
            raise InboxError(message, about=[under])
        return found

    def thread(self, agent: AgentRecord, cited: str | None) -> Concern | None:
        """Return the concern `cited` names, else the one `agent` works in, else none."""
        if cited is None:
            return self.working_in(agent)
        return self.concern(cited)

    def by(self, node: Node) -> PartyRecord:
        """Return the party who wrote `node`: the operator where lup did, of its own accord, since lup acts for them."""
        found = None if node.by is None else self.database.found(node.by)
        return found if isinstance(found, PartyRecord) else self.operator()

    def writer(self, node: Node) -> str:
        """Name who wrote `node`, as `@` cites them, or `lup`."""
        return "lup" if node.by is None else self.called(self.by(node))

    def called(self, node: Node) -> str:
        """Name `node` as `@` cites it: by its name where it has one, else by its number, else by its key."""
        if node.name is not None:
            return f"@{node.name}"
        if node.number is not None:
            return f"@{node.number}"
        return f"node {node.key}"

    def acted(self, agent: AgentRecord, concern: Concern, said: ConcernSaid) -> str:
        """Do to `concern` what `agent` says of it, each field given one act, and say what came of it; with nothing given, say where it stands."""

        def acts() -> Iterator[str]:
            if said.text is not None:
                self.said(agent, concern, said.text)
                yield "your words are in it"
            if said.body is not None:
                self.rewritten(agent, concern, said.body)
                yield "its body is rewritten"
            for number in said.move:
                self.edge(In, concern, self.item(str(number)), agent)
                yield f"@{number} is in it"
            if said.hold:
                self.moved(agent, concern, agent)
                self.works_in(agent, concern)
                yield "you hold it, and work in it"
            if said.join and not said.hold:
                self.works_in(agent, concern)
                yield "you work in it"
            if said.hand is not None:
                to = self.party(said.hand)
                self.moved(agent, concern, to)
                yield f"it's {self.called(to)}'s"
            if said.done is not None:
                self.done(agent, concern, said.done)
                yield "it's done, for the operator to clear"

        done = list(acts())
        if not done:
            return self.described(concern)
        return f"{self.called(concern)}: {'; '.join(done)}."

    def described(self, concern: Concern) -> str:
        """Say where `concern` stands, in a line: its title, who holds it, and its marks."""
        standing = self.standing(concern)
        marks = [
            f"left by {self.called(standing.left_by)}" if standing.left_by else "",
            "done, to clear" if standing.done is not None else "",
            "cleared" if standing.cleared else "",
            "declined" if standing.declined is not None else "",
        ]
        said = ", ".join(each for each in marks if each)
        return (
            f"{self.called(concern)}, {concern.title}: held by "
            f"{self.called(standing.holder)}{f', {said}' if said else ''}."
        )

    def read(self, agent: AgentRecord, number: int | None) -> str:
        """Read the inbox for `agent`, changing nothing: one item or concern whole, by its number, or what waits on the operator and the concerns they hold."""
        if number is not None:
            found = self.cited(str(number))
            match found:
                case Concern():
                    words = [
                        f"{self.called(each)}: {each.text}"
                        for each in self.said_in(found)
                    ]
                    return "\n".join(
                        [self.described(found), found.body, *words]
                    ).strip()
                case Item():
                    return (
                        f"{self.called(found)} from {self.writer(found)}: {found.text}"
                    )
                case _:
                    return self.called(found)
        waiting = [
            f"{self.called(each)} waits on the operator"
            for each in self.waits_on_operator()
        ]
        held = [self.described(each) for each in self.held(agent)]
        return "\n".join([*waiting, *held]) or "Nothing waits, and you hold nothing."

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

    def rewritten(self, by: PartyRecord, concern: Concern, body: str) -> Concern:
        """Rewrite `concern`'s body whole, as `by` understands it, its body before kept as an earlier version."""
        return self.database.kept(
            concern.model_copy(update={"body": body, "by": by.key, "at": self.now()})
        )

    def moved(
        self, by: PartyRecord, concern: Concern, to: PartyRecord | Concern
    ) -> None:
        """Move `concern` under `to`: it's in one place, where it's moved."""
        self.edge(Under, to, concern, by)

    def done(self, by: AgentRecord, concern: Concern, said: str) -> None:
        """Say, for `by`, that `concern` is done: what's done, what isn't, and what to try, for the operator to clear."""
        self.edge(Done, concern, by, by, said=said, newest=self.newest(concern))

    def cleared(self, node: Node) -> None:
        """Clear `node`, for the operator: an item, a concern, or a party's buffer whole, until something new happens in it."""
        match node:
            case Concern():
                newest = self.newest(node)
            case PartyRecord():
                newest = max((each.key for each in self.involving(node)), default=0)
            case _:
                newest = node.key
        self.edge(Cleared, node, self.operator(), self.operator(), newest=newest)

    def involving(self, party: PartyRecord) -> list[Item]:
        """Return each item `party` wrote or was for, oldest first: what their buffer shows."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if each.by == party.key or party.key in each.to
        ]

    def is_cleared(self, item: Item) -> bool:
        """Say whether the operator cleared `item`: itself, the concern it's in, or the buffer of a party who wrote it or was for it, with nothing newer there since."""
        places = [item.key, *item.to]
        if item.by is not None:
            places.append(item.by)
        within = self.database.drawn_from(item.key, In, current=True)
        places.extend(each.target for each in within)
        return any(
            edge.newest >= item.key
            for place in places
            for edge in self.database.drawn_to(place, Cleared)
        )

    def declined(self, concern: Concern, why: str) -> None:
        """Decline `concern`, for the operator, saying why: nothing more will be done about it."""
        self.edge(Declined, concern, self.operator(), self.operator(), why=why)

    def works_in(self, agent: AgentRecord, concern: Concern) -> None:
        """Have `agent` work in `concern`: what they say without naming another lands there."""
        self.edge(WorksIn, concern, agent, agent)

    def working_in(self, agent: AgentRecord) -> Concern | None:
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

    def held(self, party: PartyRecord) -> list[Concern]:
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

    def holder(self, concern: Concern) -> PartyRecord:
        """Return the party `concern` is under, or its nearest parent concern is under."""
        place = self.under(concern)
        match place:
            case PartyRecord():
                return place
            case Concern():
                return self.holder(place)
            case _:
                return self.pile(NO_AGENT)

    def standing(self, concern: Concern) -> Standing:
        """Read where `concern` stands, from the edges drawn to it and what's been said in it."""
        holder = self.holder(concern)
        left_by = (
            holder if isinstance(holder, AgentRecord) and self.ended(holder) else None
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
        by: PartyRecord,
        to: list[PartyRecord],
        text: str,
        tone: Tone = "note",
        concern: Concern | None = None,
    ) -> Message:
        """Send `by`'s `text` to `to`, of `tone`, in `concern` where it's said in one, and return it."""
        message = self.database.kept(
            Message(
                repository=self.repository,
                by=by.key,
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
        by: AgentRecord,
        text: str,
        decisions: list[Decision],
        concern: Concern | None = None,
    ) -> Question:
        """Ask the operator `text`, with `decisions`, each with `by`'s lean, and return the question."""
        question = self.database.kept(
            Question(
                repository=self.repository,
                by=by.key,
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
        asker = self.by(question)
        answer = self.database.kept(
            Answer(
                repository=self.repository,
                by=self.operator().key,
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
        writer = [] if on.by is None or on.by == operator.key else [on.by]
        readers = [each for each in on.to if each != operator.key]
        comment = self.database.kept(
            Comment(
                repository=self.repository,
                by=self.operator().key,
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

    def told_party(self, party: PartyRecord, text: str) -> Comment:
        """Send the operator's `text` to `party` alone: to an agent, or to a pile, where it opens a concern."""
        if isinstance(party, PileRecord):
            self.opened(self.operator(), first_line(text), text, party)
        return self.database.kept(
            Comment(
                repository=self.repository,
                by=self.operator().key,
                at=self.now(),
                to=[party.key],
                text=text,
            )
        )

    def felt(self, by: AgentRecord, text: str) -> Felt:
        """Keep how it is for `by`, in their words, told to the operator."""
        return self.database.kept(
            Felt(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def blocked(self, by: AgentRecord, text: str) -> Blocked:
        """Keep `by`'s word that their work can't go on, waiting on the operator."""
        return self.database.kept(
            Blocked(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def stopped(self, by: AgentRecord, text: str) -> Stopped:
        """Keep `by`'s word that they ended their work by their own choice."""
        return self.database.kept(
            Stopped(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )

    def turn_ended(self, by: AgentRecord, text: str) -> TurnEnd:
        """Keep `by`'s last words of a turn, answering each of the operator's items told to them since their last turn's end."""
        end = self.database.kept(
            TurnEnd(
                repository=self.repository,
                by=by.key,
                at=self.now(),
                to=[self.operator().key],
                text=text,
            )
        )
        operator = self.operator()
        ends = [
            each
            for each in self.database.nodes(self.repository, TurnEnd)
            if each.by == by.key and each.key != end.key
        ]
        since = ends[-1].key if ends else 0
        for told in self.told_to(by):
            if told.key > since and told.by == operator.key:
                self.edge(Answers, told, end, by)
        return end

    def withdrawn(self, by: AgentRecord, item: Item, why: str) -> None:
        """Take back `by`'s `item`, saying why: it waits on nobody after."""
        if item.by != by.key:
            message = f"@{item.number} isn't {self.called(by)}'s to withdraw"
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
            if each.by != self.operator().key
            and not self.database.drawn_to(each.key, Shown)
            and not self.is_cleared(each)
        ]

    def shown(self, items: list[Item]) -> None:
        """Say `items` have been on the operator's screen: none of them is new to them after."""
        operator = self.operator()
        for each in items:
            self.edge(Shown, each, operator, operator)

    def told_to(self, party: PartyRecord) -> list[Item]:
        """Return each item for `party` already told to them, oldest first."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if party.key in each.to and self.told(party, each)
        ]

    def told(self, party: PartyRecord, item: Item) -> bool:
        """Say whether `item` has been told to `party`."""
        return any(
            each.source == party.key for each in self.database.drawn_to(item.key, Told)
        )

    def untold(self, party: PartyRecord) -> list[Item]:
        """Return each item for `party` not yet told to them, oldest first: what reaches them at their next call."""
        return [
            each
            for each in self.database.nodes(self.repository, Item)
            if party.key in each.to and not self.told(party, each)
        ]

    def taken(self, party: PartyRecord) -> list[Item]:
        """Return each item for `party` not yet told them, and say it's told, in one transaction: what reaches them at their next call, told once."""
        with self.database.writing():
            untold = self.untold(party)
            self.tell(party, untold)
        return untold

    def inboxed(self) -> Inboxed:
        """Read the repository's inbox as data: where each concern stands, what waits on the operator, what's new to them, what's been told, and the operator's comments."""
        with self.database.together():
            concerns = [
                Placed(
                    number=each.number or 0,
                    name=each.name,
                    title=each.title,
                    kind=each.kind,
                    holder=self.called((standing := self.standing(each)).holder),
                    left_by=None
                    if standing.left_by is None
                    else self.called(standing.left_by),
                    said=len(self.said_in(each)),
                    done=standing.done is not None,
                    cleared=standing.cleared,
                    declined=standing.declined is not None,
                )
                for each in self.database.nodes(self.repository, Concern)
            ]
            items = self.database.nodes(self.repository, Item)
            told = [
                Telling(
                    item=item.number or 0,
                    party=self.called(party),
                    times=sum(
                        1
                        for edge in self.database.drawn_to(item.key, Told)
                        if edge.source == party.key
                    ),
                )
                for item in items
                for key in item.to
                if isinstance(party := self.database.found(key), PartyRecord)
            ]
            return Inboxed(
                repository=self.repository,
                concerns=concerns,
                waiting=[each.number or 0 for each in self.waits_on_operator()],
                new=[each.number or 0 for each in self.new_to_operator()],
                told=told,
                comments=[
                    Comments(item=each.number or 0, reaches=len(each.to))
                    for each in items
                    if isinstance(each, Comment)
                ],
            )

    def tell(self, party: PartyRecord, items: list[Item]) -> None:
        """Say `items` were told to `party`: each is told once, never again."""
        for each in items:
            if not self.told(party, each):
                self.edge(Told, each, party, None)


def slug(title: str, longest: int = 40) -> str | None:
    """Return a name made of `title`: its letters and digits, lower case, words joined by `-`, cut at a word's end to `longest`; none where it holds no letter.

    >>> slug("The gate hangs on a fresh worktree!"), slug("42")
    ('the-gate-hangs-on-a-fresh-worktree', None)
    """
    words = [
        "".join(letters)
        for kept, letters in groupby(
            title.lower(), key=lambda each: each.isalnum() and each.isascii()
        )
        if kept
    ]
    ends = accumulate(len(each) + 1 for each in words)
    kept = [each for each, end in zip(words, ends, strict=True) if end - 1 <= longest]
    name = "-".join(kept)
    return name if any(each.isalpha() for each in name) else None


def first_line(text: str) -> str:
    r"""Return `text`'s first line, as a title where none was given.

    >>> first_line("The gate hangs\nIt hung twice.")
    'The gate hangs'
    """
    return next(iter(text.splitlines()), "")
