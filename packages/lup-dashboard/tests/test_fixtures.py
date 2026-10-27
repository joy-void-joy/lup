"""The page's fixtures, held to what lup's Python says, so the page's tests read the looks the host gives it."""

from pathlib import Path

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
