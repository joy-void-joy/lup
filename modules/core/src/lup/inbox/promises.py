"""The inbox's promises: what agents and the operator can count on of what's said between them and where each concern stands.

Each is checked through the harness, lup started on its default modules: agents
call the inbox's tools, the operator its commands, and an agent's project's code
its services, as #5's sessions will (`README.md` here).
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, Literal

from pydantic import Field
from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, insert
from sqlalchemy.engine import URL

import lup
from lup import (
    Agent,
    Blocks,
    Codebase,
    Commented,
    Fold,
    JsonObject,
    Line,
    Machine,
    Markdown,
    Model,
    Module,
    Modules,
    Offer,
    Operator,
    Part,
    Parts,
    Project,
    Recorded,
    Viewing,
)
from lup.inbox import (
    Answering,
    AskSaid,
    Awaited,
    Awaiting,
    Clearing,
    ConcernOf,
    ConcernSaid,
    Converting,
    Decision,
    Ending,
    Everywhere,
    FrictionSaid,
    Inboxed,
    Item,
    Laid,
    Naming,
    NoteSaid,
    Nothing,
    On,
    OnItem,
    PartiesOf,
    PartyOf,
    Pile,
    Placed,
    Posted,
    Posting,
    Question,
    Reached,
    Reading,
    Ruling,
    SaidSince,
    SendSaid,
    Settling,
    Showing,
    Since,
    Spoken,
    Told,
    Untelling,
    Untold,
    WithdrawSaid,
)
from lup.testing import (
    Accepted,
    Comment,
    Delivered,
    Hello,
    Quote,
    Refused,
    Send,
    Started,
    Step,
    Testing,
    Write,
)

HERE = Codebase(repository="harness")
"""The harness's project's own code, which calls the inbox's services for its agents."""


def project() -> Project:
    """Return a project of lup's default modules, the inbox among them."""
    return Project(modules=Modules.default())


class Change(Model):
    """A change to review, by its name."""

    change: str


class ChangeAccepted(lup.Done):
    """A change accepted."""

    line: ClassVar[str] = "accepted {change}"
    change: str


class ChangeWaits(Item):
    """A change waiting on the operator's review: the reviewing module's own kind of item, laid out as a fold opening on its view, offering its command."""

    kind: str = "reviewing:waits"
    change: str

    def waits(self) -> bool:
        """Say that a change waits until the module settles it."""
        return True

    def laid(self) -> Laid:
        """Lay it out as a fold opening on the change's review, offering to accept it."""
        given = Change(change=self.change)
        return Laid(
            fold="body",
            summary=f"the change {self.change}",
            opens=Viewing.of(Reviews.review, given, module=Reviewing.name),
            offers=[Offer.of(Reviews.accept, given, module=Reviewing.name)],
        )


class Reviews(Part):
    """The reviewing module's part: a change's review, and accepting it."""

    @lup.view
    async def review(self, change: Change) -> Blocks:
        """Show a change's review."""
        return Blocks.of(Line.of("change", change.change))

    @lup.command(verb="done", says="accept it")
    async def accept(self, change: Change, by: Operator) -> ChangeAccepted:
        """Accept a change."""
        del by
        return ChangeAccepted(change=change.change)


class Reviewing(Module):
    """Reviewing changes, an item kind of a module's own.

    Reviewing: an example module the inbox's promises check a module's own kind of item
    with.
    """

    name = "reviewing"
    parts: Parts = Parts.of(Reviews)
    kinds: Recorded = Recorded.of(ChangeWaits)


def reviewing() -> Project:
    """Return a project of lup's default modules and the reviewing module."""
    return Project(modules=Modules.default().add(Reviewing()))


SECOND = MetaData()
"""The second lup's ledger, as far as a conversion reads it: its tables as the second lup wrote them, stated apart from the conversion's own, so the scenario checks that reading against them."""

SECOND_NODES = Table(
    "nodes",
    SECOND,
    Column("number", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("repository", Text, nullable=False),
    Column("name", Text),
)
SECOND_VERSIONS = Table(
    "versions",
    SECOND,
    Column("version", Integer, primary_key=True),
    Column("number", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("record", Text, nullable=False),
)
SECOND_EDGES = Table(
    "edges",
    SECOND,
    Column("drawn", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("source", Integer),
    Column("target", Integer, nullable=False),
    Column("record", Text, nullable=False),
)
SECOND_RECORDS = Table(
    "records",
    SECOND,
    Column("name", Text, primary_key=True),
    Column("record", Text, nullable=False),
)

SECOND_REPOSITORY = "/repositories/lup.git"
"""The repository, as the second lup's ledger names it: by its git directory."""


class SecondNode(Model):
    """One version of a node of the second lup's ledger, as a row of its tables reads, its record as the second lup wrote it."""

    number: int
    kind: str
    repository: str = SECOND_REPOSITORY
    name: str | None = None
    record: JsonObject


class SecondEdge(Model):
    """An edge of the second lup's ledger, as a row of its table reads, its record as the second lup wrote it."""

    kind: str
    source: int | None = None
    target: int
    record: JsonObject = {}


def second_ledger(path: Path) -> None:
    """Write a ledger of the second lup's at `path`: a planning session and the session it spawned, with a subagent of its own, writing three threads of the repository, a note among their words, and a thread of another repository.

    - `the-port`, held by the planner, its body rewritten once, a note filed in it;
    - `the-gate`, under `the-port`, then held by the builder, with their words,
      a copy of them told to the planner, their subagent's words, and a done mark;
    - `keys-lag`, under `the-gate`, its words filed with `friction`;
    - `elsewhere`, of another repository.
    """

    def party(session: str, agent: str | None = None) -> JsonObject:
        return {
            "party": "conversation",
            "repository": SECOND_REPOSITORY,
            "runtime": "claude",
            "session": session,
            "agent": agent,
        }

    plan, build, probe = party("s-plan"), party("s-build"), party("s-build", "a1")
    operator: JsonObject = {"party": "operator"}

    def at(hour: int) -> str:
        return f"2026-11-16T{hour:02}:00:00Z"

    def thread(
        number: int,
        name: str,
        title: str,
        hour: int,
        *,
        repository: str = SECOND_REPOSITORY,
        parent: int | None = None,
        holder: JsonObject | None = None,
    ) -> SecondNode:
        return SecondNode(
            number=number,
            kind="ledger:thread",
            repository=repository,
            name=name,
            record={
                "kind": "ledger:thread",
                "repository": repository,
                "by": plan,
                "at": at(hour),
                "number": number,
                "name": name,
                "title": title,
                "parent": parent,
                "holder": holder,
            },
        )

    def item(
        number: int,
        by: JsonObject,
        tool: str,
        text: str,
        hour: int,
        to: JsonObject = operator,
    ) -> SecondNode:
        return SecondNode(
            number=number,
            kind="inbox:item",
            record={
                "kind": "inbox:item",
                "repository": SECOND_REPOSITORY,
                "by": by,
                "at": at(hour),
                "number": number,
                "reason": {"tool": tool, "text": text, "title": text, "reason": tool},
                "recipient": to,
            },
        )

    versions = [
        thread(1, "the-port", "How the port goes", 1, holder=plan),
        item(2, plan, "concern", "Porting it", 1),
        thread(3, "the-gate", "#10: the gate", 2, parent=1),
        item(4, build, "concern", "The gate first", 3),
        item(5, probe, "concern", "Probed it", 4),
        item(6, build, "concern", "The gate first", 3, to=plan),
        thread(7, "keys-lag", "the keys lag", 5, parent=3),
        item(8, build, "friction", "the keys lag", 5),
        item(9, plan, "note", "A note on the port", 6),
        thread(10, "elsewhere", "Another's", 6, repository="/repositories/other.git"),
        thread(3, "the-gate", "#10: the gate", 7, parent=1, holder=build),
    ]
    edges = [
        *(
            SecondEdge(kind="ledger:in", source=source, target=target)
            for source, target in [(2, 1), (4, 3), (5, 3), (6, 3), (8, 7), (9, 1)]
        ),
        SecondEdge(
            kind="ledger:body",
            target=1,
            record={"by": plan, "at": at(8), "text": "The port's body"},
        ),
        SecondEdge(
            kind="ledger:done",
            target=3,
            record={"by": build, "at": at(9), "to_try": "Try the gate"},
        ),
    ]
    conversations: list[JsonObject] = [
        {"conversation": plan, "since": at(0), "parent": None, "name": None},
        {"conversation": build, "since": at(1), "parent": plan, "name": None},
        {"conversation": probe, "since": at(2), "parent": None, "name": "probe"},
    ]
    latest = {each.number: version for version, each in enumerate(versions, 1)}
    engine = create_engine(URL.create("sqlite", database=str(path)))
    with engine.begin() as connection:
        SECOND.create_all(connection)
        connection.execute(
            insert(SECOND_VERSIONS),
            [
                {
                    "version": version,
                    "number": each.number,
                    "kind": each.kind,
                    "record": json.dumps(each.record),
                }
                for version, each in enumerate(versions, 1)
            ],
        )
        connection.execute(
            insert(SECOND_NODES),
            [
                {
                    "number": each.number,
                    "version": version,
                    "kind": each.kind,
                    "repository": each.repository,
                    "name": each.name,
                }
                for version, each in enumerate(versions, 1)
                if latest[each.number] == version
            ],
        )
        connection.execute(
            insert(SECOND_EDGES),
            [
                {
                    "kind": each.kind,
                    "source": each.source,
                    "target": each.target,
                    "record": json.dumps(
                        {
                            "kind": each.kind,
                            "source": each.source,
                            "target": each.target,
                            **each.record,
                        }
                    ),
                }
                for each in edges
            ],
        )
        connection.execute(
            insert(SECOND_RECORDS),
            [
                {"name": f"inbox:conversation:{number}", "record": json.dumps(each)}
                for number, each in enumerate(conversations)
            ],
        )
    engine.dispose()


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
    answered = await started.serve(
        "told", Ending(repository="harness", agent=agent), Machine()
    )
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Told)
    return answered.output


async def untold(started: Started) -> list[Agent]:
    """Return each agent of the harness's repository who has something not yet told them, as a session reads whom to wake."""
    answered = await started.serve("untold", Untelling(repository="harness"), Machine())
    assert isinstance(answered, Accepted)
    assert isinstance(answered.output, Untold)
    return answered.output.agents


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


class Written(Model):
    """Markdown an agent writes, a line at a time: the beginnings of its blocks, and what goes on with them."""

    lines: list[
        Literal[
            "a paragraph",
            "- an item",
            "  - nested in it",
            "1. a first",
            "# a heading",
            "> a quote",
            "```",
            "    set in",
            "| a | b |",
            "|---|---|",
            "---",
            "<div>",
            "[a]: https://x.y",
            "",
        ]
    ] = Field(min_length=1, max_length=8)

    def text(self) -> str:
        """Return what's written."""
        return "\n".join(self.lines)


class Pointing(Model):
    """Which line the operator points at, the last where there are fewer."""

    line: int = Field(ge=0, le=8)


class Highlight(Model):
    """A phrase the operator picks out of a line, and what the line says around it."""

    before: Literal["", "so, "]
    phrase: Literal["safer", "shorter by far"]
    after: Literal[", since nothing is deleted", " than that"]

    def line(self) -> str:
        """Return the line whole, an item of a list."""
        return f"- {self.before}{self.phrase}{self.after}"

    def starts(self) -> int:
        """Return where the phrase starts in its line."""
        return len(f"- {self.before}")

    def ends(self) -> int:
        """Return where the phrase ends in its line."""
        return self.starts() + len(self.phrase)


class Deciding(Model):
    """How many decisions a question asks."""

    count: int = Field(ge=1, le=3)


async def asked(started: Started, text: str, agent: Agent, decisions: int = 0) -> int:
    """Ask the operator `text` as `agent`, with as many decisions, without waiting, and return the question's number."""
    asking = AskSaid(
        question=text,
        decisions=[
            Decision(decision=f"decide {number}", lean=f"lean {number}")
            for number in range(1, decisions + 1)
        ],
        wait=False,
    )
    await said(started, "ask", asking, agent)
    return max((await inboxed(started)).waiting)


async def texts(started: Started, number: int) -> list[Markdown]:
    """Return the blocks saying item `number`'s words, as the operator's view of what waits lays them out."""
    shown = await viewed(started, "waiting", PartiesOf(repository="harness"))
    return [
        each
        for each in shown.blocks
        if isinstance(each, Markdown) and each.id.startswith(f"item-{number}-")
    ]


async def commented(started: Started, comment: Commented[OnItem]) -> None:
    """Comment on an item as the operator does, which must be kept."""
    kept = await started.run("core", "comment", comment, Operator())
    assert isinstance(kept, Accepted), kept


async def told_on(started: Started, agent: Agent, words: str) -> On:
    """Tell `agent` what's for them, and return what the item saying `words` is said to be on, which it must be."""
    [on] = [
        each.on
        for each in (await told(started, agent)).items
        if each.text == words and each.on is not None
    ]
    return on


class InboxPromises(Part):
    """What agents and the operator can count on of the inbox."""

    @lup.promise
    def a_parts_id_names_the_same_words(self, step: Step[Everywhere]) -> bool:
        """A part's id names the same words for as long as its item is kept."""
        before = {
            each.item: each.parts
            for inbox in step.before.inboxes
            for each in inbox.parts
        }
        return all(
            before.get(each.item, each.parts) == each.parts
            for inbox in step.after.inboxes
            for each in inbox.parts
        )

    @lup.promise
    def a_comment_on_a_part_names_one_its_item_has(
        self, step: Step[Everywhere]
    ) -> bool:
        """A comment on a part of an item names a part that item has."""
        counted = {
            each.item: len(each.parts)
            for inbox in step.after.inboxes
            for each in inbox.parts
        }
        return all(
            each.on is not None and 1 <= place <= counted.get(each.on, 0)
            for inbox in step.after.inboxes
            for each in inbox.comments
            for place in each.places
        )

    @lup.promise
    async def every_line_said_is_in_one_part(self, by: Testing) -> None:
        """Each line an agent says that says something is in one part, and the parts in order are what they said."""
        started = await by.started(project())
        agent = by.any(Agent)
        written = by.any(Written)
        await said(started, "note", NoteSaid(remark=written.text()), agent)
        [found] = (await inboxed(started)).parts
        assert [line for part in found.parts for line in part.splitlines() if line] == [
            line for line in written.lines if line
        ]

    @lup.promise
    async def a_comment_on_a_line_is_told_with_what_cites_it(self, by: Testing) -> None:
        """A comment the operator writes on a line of an item, in the dashboard, is told to its writer as on the part the view says cites that line, or on the item where it's one part alone."""
        started = await by.started(project())
        agent = by.any(Agent)
        lines = [*by.any(Written).lines, "the end"]
        number = await asked(started, "\n".join(lines), agent)
        [text] = await texts(started, number)
        at = min(by.any(Pointing).line, len(lines) - 1)
        page = await started.dashboard()
        await page.say(Hello(token=page.token))
        quote = Quote(
            viewing=Viewing(
                module="core", view="waiting", given={"repository": "harness"}
            ),
            block=text.id,
            lines=[lines[at]],
            line=at,
        )
        await page.say(Write(comment=Comment(id="c", on=quote, words="why?")))
        await page.say(Send())
        while not isinstance(sent := await page.told(), Delivered):
            assert sent is not None, "the page was told nothing more before the send"
        assert sent.went == ["c"]
        above = [each for each in reversed(text.anchors) if each.line <= at]
        cited = next((each.cited for each in [*above, *text.anchors]), f"@{number}")
        on = await told_on(started, agent, "why?")
        assert f"@{on.named()}" == cited

    @lup.promise
    async def what_the_operator_picks_out_is_told_whole(self, by: Testing) -> None:
        """A phrase the operator picks out of an item is told whole, with the part it's in; a comment on whole parts is told by their ids and how they begin, over several with the first and the last; one on the item's heading is on the item whole."""
        started = await by.started(project())
        agent = by.any(Agent)
        picked = by.any(Highlight)
        number = await asked(started, f"Which way?\n\n{picked.line()}\n- or not", agent)
        shown = await viewed(started, "waiting", PartiesOf(repository="harness"))
        heading = "".join(
            span.text
            for each in shown.blocks
            if isinstance(each, Line) and each.id == f"item-{number}"
            for span in each.spans
        )
        on = OnItem(item=number)
        await commented(
            started,
            Commented[OnItem](
                on=on,
                words="a phrase",
                lines=[picked.line()],
                line=2,
                start=picked.starts(),
                end=picked.ends(),
            ),
        )
        phrase = await told_on(started, agent, "a phrase")
        assert (phrase.part, phrase.quote) == (2, picked.phrase)
        await commented(
            started,
            Commented[OnItem](on=on, words="a part", lines=[picked.line()], line=2),
        )
        part = await told_on(started, agent, "a part")
        assert (part.part, part.last, part.quote) == (2, None, None)
        assert part.opening is not None
        await commented(
            started,
            Commented[OnItem](
                on=on, words="both", lines=[picked.line(), "- or not"], line=2
            ),
        )
        both = await told_on(started, agent, "both")
        assert (both.part, both.last, both.quote) == (2, 3, None)
        await commented(
            started, Commented[OnItem](on=on, words="it all", lines=[heading])
        )
        whole = await told_on(started, agent, "it all")
        assert (whole.item, whole.part, whole.quote) == (number, None, None)

    @lup.promise
    async def each_decision_is_shown_and_answered_by_its_part(
        self, by: Testing
    ) -> None:
        """A question's decisions each show as a part of their own after its text's, and a comment on one is told to the asker as on that part; a comment on a part it hasn't is refused."""
        started = await by.started(project())
        agent = by.any(Agent)
        count = by.any(Deciding).count
        number = await asked(started, "Which way?", agent, decisions=count)
        shown = await texts(started, number)
        assert len(shown) == 1 + count
        for place, block in enumerate(shown, start=1):
            assert [each.cited for each in block.anchors] == [f"@{number}.{place}"]
        for place, block in enumerate(shown[1:], start=2):
            assert f"decide {place - 1}" in block.text
            assert f"lean {place - 1}" in block.text
            [offer] = [each for each in block.offers if each.command == "comment"]
            words = f"on {place}"
            await commented(
                started,
                Commented[OnItem](on=OnItem.model_validate(offer.given), words=words),
            )
            on = await told_on(started, agent, words)
            assert (on.item, on.part) == (number, place)
        beyond = OnItem(item=number, part=count + 2)
        refused = await started.run(
            "core", "comment", Commented[OnItem](on=beyond, words="no"), Operator()
        )
        assert isinstance(refused, Refused)

    @lup.promise
    async def an_answers_rulings_are_told_at_a_later_call(self, by: Testing) -> None:
        """An answer to a question nobody waits on is told at its asker's next call with each ruling, its comment whole, and the question it answers."""
        started = await by.started(project())
        agent = by.any(Agent)
        number = await asked(started, "Which way?", agent, decisions=1)
        comment = by.any(Highlight).phrase
        ruling = Ruling(number=1, verdict="leaning", comment=comment)
        answering = Answering(question=number, rulings=[ruling])
        answered = await started.run("core", "answer", answering, Operator())
        assert isinstance(answered, Accepted), answered
        [answer] = (await told(started, agent)).items
        assert comment in answer.text
        assert answer.on is not None
        assert answer.on.item == number

    @lup.promise
    async def words_on_no_item_are_told_with_the_lines_they_are_on(
        self, by: Testing
    ) -> None:
        """A comment to a party on lines no item holds, as a conversation's, is told with what it picks out of them, whole."""
        started = await by.started(project())
        agent = by.any(Agent)
        picked = by.any(Highlight)
        await said(started, "note", NoteSaid(remark="here"), agent)
        kept = await started.run(
            "core",
            "comment_to",
            Commented[Reached](
                on=Reached(party=agent),
                words="what's this?",
                lines=[picked.line()],
                start=picked.starts(),
                end=picked.ends(),
            ),
            Operator(),
        )
        assert isinstance(kept, Accepted), kept
        on = await told_on(started, agent, "what's this?")
        assert (on.item, on.quote) == (None, picked.phrase)

    @lup.promise
    async def a_part_is_answered_from_the_command_line(self, by: Testing) -> None:
        """`lup tell` on a part of an item, `@12.3`, is told to its writer as on that part, and clearing one isn't offered there; a part the item hasn't is refused."""
        started = await by.started(project())
        agent = by.any(Agent)
        place = by.any(Deciding).count + 1
        number = await asked(started, "Which way?", agent, decisions=place - 1)
        words = by.any(Highlight).phrase
        cited = f"@{number}.{place}"
        typed = await started.typed(["tell", cited, words], Operator())
        assert typed.status == 0, typed.error
        on = await told_on(started, agent, words)
        assert (on.item, on.part, on.quote) == (number, place, None)
        done = await started.typed(["done", cited], Operator())
        assert done.status != 0
        beyond = await started.typed(["tell", f"{cited}0", words], Operator())
        assert beyond.status != 0

    @lup.promise
    async def a_part_is_read_by_its_id(self, by: Testing) -> None:
        """An agent reads a part of an item alone by the item's number and its place, or the item whole with each part's id; a place it hasn't is refused, and so is clearing a part."""
        started = await by.started(project())
        agent = by.any(Agent)
        picked = by.any(Highlight)
        number = await asked(started, f"Which way?\n\n{picked.line()}", agent)
        part = await said(started, "inbox", Reading(number=number, part=2), agent)
        assert picked.line() in part
        assert "Which way?" not in part
        whole = await said(started, "inbox", Reading(number=number), agent)
        assert all(f"@{number}.{place}" in whole for place in [1, 2])
        missing = Reading(number=number, part=3)
        assert isinstance(await started.call("inbox", missing, agent), Refused)
        clearing = Clearing(repository="harness", what=f"{number}.2")
        cleared = await started.run("core", "clear", clearing, Operator())
        assert isinstance(cleared, Refused)

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
        await started.serve(
            "agent_ended", Ending(repository="harness", agent=agent), Machine()
        )
        left = placed(await inboxed(started), "the gate")
        assert left.holder == "@no-agent"
        assert left.left_by is not None
        await started.serve(
            "agent_started", Ending(repository="harness", agent=agent), Machine()
        )
        back = placed(await inboxed(started), "the gate")
        assert back.holder == left.left_by
        assert back.left_by is None

    @lup.promise
    async def a_question_waits_until_answered(self, by: Testing) -> None:
        """A question waits on the operator until they answer it, and a note never does."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(started, "ask", AskSaid(question="which way?", wait=False), agent)
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
        reader = Machine()
        await said(
            started,
            "ask",
            AskSaid(
                question="which way?",
                decisions=[Decision(decision="go left", lean="yes, it's shorter")],
                wait=False,
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
        await said(started, "ask", AskSaid(question="still needed?", wait=False), agent)
        [question] = (await inboxed(started)).waiting
        await said(
            started, "withdraw", WithdrawSaid(item=question, why="settled"), agent
        )
        assert not (await inboxed(started)).waiting

    @lup.promise
    async def news_stays_until_cleared(self, by: Testing) -> None:
        """News stays new until the operator clears it; clearing a concern clears the news in it, until something newer is said there."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started, "concern", ConcernSaid(text="first", title="a direction"), agent
        )
        await said(
            started, "note", NoteSaid(remark="a doubt", thread="a-direction"), agent
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
            started, "note", NoteSaid(remark="another", thread="a-direction"), agent
        )
        again = await inboxed(started)
        assert again.new
        assert not placed(again, "a direction").cleared

    @lup.promise
    async def a_comment_on_agents_exchange_reaches_both(self, by: Testing) -> None:
        """The operator's comment on a message one agent sent another reaches both: whoever wrote it, and whoever it was for."""
        started = await by.started(project())
        writer, reader = Agent.of("writer-id"), Agent.of("reader-id")
        await started.serve(
            "agent_named",
            Naming(repository="harness", agent=writer, name="writer"),
            Machine(),
        )
        await started.serve(
            "agent_named",
            Naming(repository="harness", agent=reader, name="reader"),
            Machine(),
        )
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
    async def an_agent_is_untold_until_what_is_theirs_is_told(
        self, by: Testing
    ) -> None:
        """An agent something was sent to is among those a session wakes until it's told them, and not after."""
        started = await by.started(project())
        writer, reader = Agent.of("writer-id"), Agent.of("reader-id")
        for agent, name in [(writer, "writer"), (reader, "reader")]:
            await started.serve(
                "agent_named",
                Naming(repository="harness", agent=agent, name=name),
                Machine(),
            )
        await said(started, "send", SendSaid(to="reader", text="over to you"), writer)
        assert await untold(started) == [reader]
        await told(started, reader)
        assert await untold(started) == []

    @lup.promise
    async def the_operator_finds_each_concern_from_the_list_of_parties(
        self, by: Testing
    ) -> None:
        """Every concern an agent opens is found from the list of parties, under the party holding it, and opens on what was said in it; a comment on it reaches its holder."""
        started = await by.started(project())
        agent = by.any(Agent)
        await started.serve(
            "agent_named",
            Naming(repository="harness", agent=agent, name="builder"),
            Machine(),
        )
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
        [slow] = [each for each in keys if each.kind == "friction"]
        assert slow.reaches == Pile(repository="harness", path="frictions/keys")
        number = int(gate.id.removeprefix("concern-"))
        words = await viewed(started, "concern_view", ConcernOf(number=number))
        assert any("it hung twice" in line for line in words.text().splitlines())

    @lup.promise
    async def what_waits_is_shown_as_waiting(self, by: Testing) -> None:
        """What waits on the operator is in their view of what waits, and leaves it once they answer it."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(started, "ask", AskSaid(question="which way?", wait=False), agent)
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

    @lup.promise
    async def a_modules_own_item_waits_until_the_module_settles_it(
        self, by: Testing
    ) -> None:
        """An item of a module's own kind, posted for an agent, waits on the operator, laid out as its kind says, until the module settles it, and what came of it is told to the agent; the inbox's own kinds can't be posted."""
        started = await by.started(reviewing())
        agent = by.any(Agent)
        waits = Posting.of(
            ChangeWaits,
            Change(change="tidy"),
            by=agent,
            repository="harness",
            text="it waits",
        )
        posted = await started.serve("post", waits, Machine())
        assert isinstance(posted, Accepted), posted
        assert isinstance(posted.output, Posted)
        number = posted.output.number
        assert number in (await inboxed(started)).waiting
        shown = await viewed(started, "waiting", PartiesOf(repository="harness"))
        [fold] = [each for each in folds(shown) if each.id == f"item-{number}-laid"]
        assert fold.content == Viewing(
            module="reviewing", view="review", given={"change": "tidy"}
        )
        assert [(each.module, each.command) for each in fold.offers[1:]] == [
            ("reviewing", "accept")
        ]
        settled = Settling(repository="harness", item=number, text="accepted")
        assert isinstance(await started.serve("settle", settled, HERE), Accepted)
        assert number not in (await inboxed(started)).waiting
        assert any(
            each.text == "accepted" for each in (await told(started, agent)).items
        )
        question = Posting.of(Question, by=agent, repository="harness", text="may I?")
        refused = await started.serve("post", question, Machine())
        assert isinstance(refused, Refused)

    @lup.promise
    async def the_second_lups_concerns_come_over_once(self, by: Testing) -> None:
        """A repository's threads in the second lup's ledger come over once, each a friction or a concern by the tool its first words were filed with, with its body, place, holder and done mark, and the words filed in it; the notes sent into one, another repository's threads, and a second run don't."""
        started = await by.started(project())
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.sqlite3"
            second_ledger(ledger)
            converting = Converting(
                ledger=ledger, named=SECOND_REPOSITORY, repository="harness"
            )
            converted = await started.run("core", "convert", converting, Operator())
            assert isinstance(converted, Accepted), converted
            again = await started.run("core", "convert", converting, Operator())
            assert isinstance(again, Refused)
            missing = converting.model_copy(update={"ledger": Path(directory) / "no"})
            assert isinstance(
                await started.run("core", "convert", missing, Operator()), Refused
            )
        state = await inboxed(started)
        assert [each.title for each in state.concerns] == [
            "How the port goes",
            "#10: the gate",
            "the keys lag",
        ]
        port = placed(state, "How the port goes")
        gate = placed(state, "#10: the gate")
        keys = placed(state, "the keys lag")
        assert (port.holder, port.left_by, port.said) == (
            "@no-agent",
            "agent s-plan",
            1,
        )
        assert (gate.left_by, gate.said, gate.done) == ("agent s-build", 2, True)
        assert gate.number in state.waiting
        assert (keys.kind, keys.holder) == ("inbox:friction", "@frictions")
        assert not state.new
        body = await viewed(started, "concern_view", ConcernOf(number=port.number))
        assert any(
            isinstance(each, Markdown) and each.text == "The port's body"
            for each in body.blocks
        )
        probe = await started.view(
            "core", "party", PartyOf(repository="harness", name="probe"), Operator()
        )
        assert isinstance(probe, Accepted), probe

    @lup.promise
    async def a_concerns_words_mark_it_rather_than_the_news(self, by: Testing) -> None:
        """Words filed in a concern aren't news: the concern's line is new until the operator has had what's in it on their screen, while a note in it is news."""
        started = await by.started(project())
        agent = by.any(Agent)
        await said(
            started, "concern", ConcernSaid(text="first", title="a direction"), agent
        )
        state = await inboxed(started)
        assert not state.new
        concern = placed(state, "a direction")
        assert concern.new
        opened = await viewed(started, "concern_view", ConcernOf(number=concern.number))
        for block in opened.blocks:
            if block.sighted is not None:
                seen = Showing.model_validate(block.sighted.given)
                shown = await started.run("core", "shown", seen, Operator())
                assert isinstance(shown, Accepted), shown
        assert not placed(await inboxed(started), "a direction").new
        await said(
            started, "note", NoteSaid(remark="a doubt", thread="a-direction"), agent
        )
        after = await inboxed(started)
        assert after.new
        assert placed(after, "a direction").new

    @lup.promise
    async def a_subagents_friction_reaches_its_parent_as_a_line(
        self, by: Testing
    ) -> None:
        """A subagent's friction is told to the agent who spawned them once, as a line saying what and where, never whole and never waiting; their concern isn't told to them."""
        started = await by.started(project())
        lead, probe = Agent.of("lead-id"), Agent.of("lead-id", "probe-id")
        for agent, name, spawner in [(lead, "lead", None), (probe, "probe", lead)]:
            await started.serve(
                "agent_named",
                Naming(repository="harness", agent=agent, name=name, spawner=spawner),
                Machine(),
            )
        await said(
            started,
            "friction",
            FrictionSaid(text="the keys lag\n\nEach press waits a second."),
            probe,
        )
        await said(
            started, "concern", ConcernSaid(text="watch the keys", title="keys"), probe
        )
        [line] = (await told(started, lead)).items
        assert "the keys lag" in line.text
        assert "Each press" not in line.text
        assert not (await told(started, lead)).items
        assert not (await inboxed(started)).waiting

    @lup.promise
    async def an_ask_holds_until_the_operator_answers(self, by: Testing) -> None:
        """An agent's `ask` holds until the operator answers or `within` passes, and the answer is told to them once, by the held call or at their next; what's held settles once the answer is in, and an ask that doesn't wait leaves its question waiting."""
        started = await by.started(project())
        agent = by.any(Agent)
        held = asyncio.ensure_future(
            said(
                started,
                "ask",
                AskSaid(
                    question="which way?",
                    decisions=[Decision(decision="go left", lean="it's shorter")],
                ),
                agent,
            )
        )
        while not (await inboxed(started)).waiting and not held.done():
            await asyncio.wait([held], timeout=60)
        [question] = (await inboxed(started)).waiting
        answered = await started.run(
            "core",
            "answer",
            Answering(
                question=question,
                rulings=[Ruling(number=1, verdict="leaning", comment="go")],
                text="and quickly",
            ),
            Operator(),
        )
        assert isinstance(answered, Accepted), answered
        await held
        await told(started, agent)
        state = await inboxed(started)
        [answer] = [
            each
            for each in state.told
            if each.party != "@operator" and each.item > question
        ]
        assert answer.times == 1
        settled = await started.serve(
            "awaited",
            Spoken(agent=agent, said=Awaiting(question=question)),
            HERE,
        )
        assert isinstance(settled, Accepted), settled
        assert isinstance(settled.output, Awaited)
        assert settled.output.settled
        await said(started, "ask", AskSaid(question="and then?", wait=False), agent)
        assert len((await inboxed(started)).waiting) == 1
