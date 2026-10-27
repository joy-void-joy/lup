"""The page's fixtures, held to what lup's Python says: the looks the page's tests read are those the host gives it, and each view the page lays out itself answers blocks its module's Python can."""

import json
from pathlib import Path

from lup.blocks import Block, Blocks, Fold
from lup_dev.declaration.project import Project
from lup_dev.declaration.resolve import resolve
from lup_dev.host.protocol import Looks

FIXTURES = Path(__file__).resolve().parents[1] / "page" / "src" / "fixtures"


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
