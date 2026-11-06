"""The page's fixtures, held to what lup's Python says: the looks the page's tests read are those the host gives it, each view the page lays out itself answers blocks its module's Python can, the items its tests lay out say what the host's table of kinds says, and the conversation its tests lay out is `Transcripts`' own answer."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import override

from pydantic import JsonValue

from lup.blocks import Block, Blocks, Fold, OfAgent
from lup.types import Model
from lup_dashboard.handled import Modules
from lup_dashboard.standins import StandInReader, StandInRecords, StoodIn
from lup_dev.declaration.project import Project
from lup_dev.declaration.resolve import resolve
from lup_dev.host.protocol import Looks
from lup_dev.host.records import Entry, Recorded, Transcript
from lup_dev.host.workers import Viewing
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.marks import MarkStore, StoredMarks
from lup_dev.inbox.protocol import Exchanged
from lup_dev.inbox.store import (
    Answer,
    Approval,
    Done,
    Ended,
    Flagged,
    Friction,
    HeldChange,
    HowItFelt,
    Item,
    Message,
    Question,
    Reason,
    Review,
    State,
    Stop,
    Superseded,
    Unresolved,
    Waiting,
)
from lup_dev.layout import Layout
from lup_ledger.parties import Conversation, Operator, Party

FIXTURES = Path(__file__).resolve().parents[1] / "page" / "src" / "fixtures"


class Answered(Model):
    """One of a module's views, by its name, of what it's given, and what it answers."""

    view: str
    argument: JsonValue
    answer: Blocks


class Transcribed(Model):
    """A conversation's record, of which agent of which repository, and each of `Transcripts`' views of it answered."""

    repository: Path
    of: OfAgent
    entries: list[Entry]
    answers: list[Answered]


def test_the_page_s_looks_are_lup_s_default_declaration_s() -> None:
    """`looks.json` is what the host's listing stands in for a repository with: regenerate it where this fails.

    `uv run python -c "from lup_dev.declaration.project import Project;
    from lup_dev.declaration.resolve import resolve;
    print(resolve(Project()).looks.model_dump_json(indent=2))"
    > packages/lup-dashboard/page/src/fixtures/looks.json`
    """
    fixed = Looks.model_validate_json((FIXTURES / "looks.json").read_text())
    assert fixed == resolve(Project()).looks


def answered() -> list[tuple[str, Blocks]]:
    """Return each answer the page's own views' fixtures pin, by its view and its case."""
    return [
        (
            f"{case['module']} {case['view']}: {case['name']}",
            Blocks.model_validate(case["answer"]),
        )
        for path in sorted((FIXTURES / "views").glob("*.json"))
        for case in json.loads(path.read_text())
        if case["answer"] is not None
    ]


def test_each_view_the_page_lays_out_answers_blocks_its_module_s_python_can() -> None:
    """Each answer the page's producers pin is `Blocks` as lup's Python reads them, naming only the tones, fold kinds and verbs lup's default declaration declares: what a module's view, once it answers itself (#113, step 4), answers alike."""
    looks = resolve(Project()).looks
    tones = {tone.name for tone in looks.tones}
    kinds = {fold.name for fold in looks.folds} | {each.view for each in looks.drawers}
    verbs = {verb.name for verb in looks.verbs}

    def blocks(each: Block) -> list[Block]:
        match each:
            case Fold(content=list() as content):
                return [each, *(inner for block in content for inner in blocks(block))]
            case _:
                return [each]

    found = answered()
    assert found
    for name, answer in found:
        every = [inner for block in answer.blocks for inner in blocks(block)]
        assert set(answer.tones()) <= tones, name
        assert {each.kind for each in every if isinstance(each, Fold)} <= kinds, name
        offered = [*answer.offers, *(offer for each in every for offer in each.offers)]
        assert {each.verb for each in offered if each.verb is not None} <= verbs, name


KINDS = FIXTURES / "kinds.json"
"""What the host says of an item of each kind, from each party, standing each way: what the page's tests give the items they lay out (`fixtures/kinds.ts`), rather than a table of the page's own."""


def kinds() -> list[Item]:
    """Return an item of each kind, from a conversation and from the operator, waiting on the operator, standing past that, replaced, and waiting on someone else.

    `uv run python -c "import sys; sys.path.insert(0, 'packages/lup-dashboard/tests');
    import test_fixtures as t; t.KINDS.write_text(t.kinds_written())"`
    """
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    agent = Conversation(repository=Path("/r"), runtime="claude", session="s1")
    reasons: list[Reason] = [
        Approval(text="?", summary="", repository=Path("/r"), fingerprint="f"),
        HeldChange(text="?", summary="", worktree=Path("/w"), key="k"),
        Question(text="?"),
        Message(kind="note", text="."),
        Message(kind="problem", text="."),
        Message(kind="disagreement", text="."),
        Message(kind="question", text="."),
        Message(kind="note", text=".", to=agent),
        Friction(text="."),
        HowItFelt(text="."),
        Stop(why="."),
        Ended(name="a"),
        Unresolved(of=1, citations=[]),
        Flagged(text=".", summary="", worktree=Path("/w"), path=Path("a")),
        Answer(question=1),
        Review(covers=[]),
    ]
    standing: list[tuple[Party, Party, State]] = [
        (agent, Operator(), Waiting()),
        (agent, Operator(), Done(at=at)),
        (agent, Operator(), Superseded(at=at, by=9)),
        (agent, agent, Waiting()),
        (Operator(), Operator(), Waiting()),
    ]
    return [
        Item(
            number=7,
            reason=reason,
            sender=sender,
            recipient=recipient,
            state=state,
            made=at,
        )
        for reason in reasons
        for sender, recipient, state in standing
    ]


def kinds_written() -> str:
    """Return `kinds.json` as the host's table of kinds says it: what each is, and what the host says of it, a line each."""
    rows = [
        json.dumps(
            {
                "reason": each.reason.model_dump(mode="json")["reason"],
                "kind": getattr(each.reason, "kind", None),
                "to": getattr(each.reason, "to", None) is not None,
                "sender": each.sender.party,
                "recipient": each.recipient.party,
                "state": each.state.state,
                "rank": each.rank.name,
                "asks": each.asks,
                "holds": each.holds,
                "offers": [offer.model_dump(mode="json") for offer in each.offers],
                "spent": [spent.model_dump(mode="json") for spent in each.spent],
            }
        )
        for each in kinds()
    ]
    return "[\n" + ",\n".join(rows) + "\n]\n"


def test_the_items_the_page_s_tests_lay_out_say_what_the_host_s_table_of_kinds_says() -> (
    None
):
    """`kinds.json` is what each kind is to the host: rewrite it where this fails (`kinds`)."""
    assert KINDS.read_text() == kinds_written()


CONVERSATION = FIXTURES / "conversation.json"
"""An agent's conversation as `Transcripts` answers its views, which the page's review tests lay out as its drawer: the record it's of, and each view's answer."""


class NothingExchanged(Exchanges):
    """No item of the inbox a conversation exchanged: the fixture's record holds none."""

    @override
    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        return Exchanged(sent=[], received=[])


def transcribed(fixed: Transcribed) -> list[Answered]:
    """Return each view `fixed` names as `Transcripts` answers it now, over its record, through the repository's process as the demo makes it (`lup_dashboard.handled.Modules`).

    `uv run python -c "import sys; sys.path.insert(0, 'packages/lup-dashboard/tests');
    import test_fixtures as t; t.CONVERSATION.write_text(t.rewritten())"`
    """

    async def answered(modules: Modules, each: Answered) -> Answered:
        viewing = Viewing(
            repository=fixed.repository,
            module="transcripts",
            view=each.view,
            argument=each.argument,
        )
        return each.model_copy(update={"answer": (await modules.view(viewing)).blocks})

    async def every(modules: Modules) -> list[Answered]:
        return [await answered(modules, each) for each in fixed.answers]

    with TemporaryDirectory() as kept:
        layout = Layout(state=Path(kept), data=Path(kept) / "data")
        records = StandInRecords(
            runtime=fixed.of.runtime,
            directory=Path(kept) / "records",
            stands=lambda runtime, session, _: StoodIn(
                transcript=Transcript(
                    runtime=runtime, session=session, entries=fixed.entries
                )
            ),
        )
        return asyncio.run(
            every(
                Modules(
                    repository=fixed.repository,
                    resolved=resolve(Project()),
                    recorded={
                        fixed.of.runtime: Recorded(
                            records=records, reader=StandInReader()
                        )
                    },
                    layout=layout,
                    exchanges=NothingExchanged(),
                    marks=StoredMarks(store=MarkStore.kept_in(layout)),
                )
            )
        )


def rewritten() -> str:
    """Return the fixture with each answer as `Transcripts` answers it now."""
    fixed = Transcribed.model_validate_json(CONVERSATION.read_text())
    now = fixed.model_copy(update={"answers": transcribed(fixed)})
    return f"{now.model_dump_json(indent=2)}\n"


def test_the_conversation_the_page_s_tests_lay_out_is_transcripts_own() -> None:
    """`conversation.json` is what `Transcripts` answers of its record: rewrite it where this fails (`transcribed`)."""
    fixed = Transcribed.model_validate_json(CONVERSATION.read_text())
    assert transcribed(fixed) == fixed.answers
