"""The page's fixtures, held to what lup's Python says: the looks the page's tests read are those the host gives it, each view the page lays out itself answers blocks its module's Python can, and the conversation its tests lay out is `Transcripts`' own answer."""

import asyncio
import json
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
from lup_dev.layout import Layout

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
