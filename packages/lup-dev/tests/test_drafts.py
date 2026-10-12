"""Drafts: where each lives, its base, beginning one, and dropping it."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.checkpoint import SessionStarted, Worktree
from lup_dev.policy.drafts import (
    DraftError,
    Drafts,
    draft_path,
    drafted,
)
from lup_dev.policy.importers import Conversation

if TYPE_CHECKING:
    from conftest import Kit

CORE = Path("src/pkg/core.py")
NEW = Path("src/pkg/extra.py")
ME = Conversation(session="s1")


def drafts(kit: Kit, repo: Path) -> Drafts:
    return Drafts(store=Worktree.at(repo, kit.layout).store)


@pytest.fixture
def started(kit: Kit, repo: Path) -> Path:
    SessionStarted(session="s1", cwd=repo).apply(kit.bench)
    return repo


def test_a_draft_lives_under_lup_drafts_each_dot_segment_escaped() -> None:
    root = Path("/w")
    assert draft_path(root, Path("src/core.py")) == root / ".lup/drafts/src/core.py"
    assert draft_path(root, Path(".github/a/.env")) == root / (
        ".lup/drafts/%2Egithub/a/%2Eenv"
    )
    assert draft_path(root, Path("%41/b.py")) == root / ".lup/drafts/%2541/b.py"


def test_a_drafts_path_reads_back_to_its_file() -> None:
    root = Path("/w")
    for file in [Path(".github/x.yml"), Path("%2Eodd/y"), Path("a/b.c")]:
        assert drafted(root, draft_path(root, file)) == file
        assert drafted(root, root / file) == file
        assert draft_path(root, draft_path(root, file)) == draft_path(root, file)


def test_a_path_outside_the_worktree_or_climbing_out_refuses() -> None:
    with pytest.raises(DraftError, match="isn't in the worktree"):
        drafted(Path("/w"), Path("/elsewhere/a.py"))
    with pytest.raises(DraftError, match="climbs out"):
        drafted(Path("/w"), Path("src/../../a.py"))
    with pytest.raises(DraftError, match="where drafts are written"):
        drafted(Path("/w"), Path("/w/.lup/drafts"))


def test_a_write_shaped_draft_is_what_the_call_writes_its_base_accepted(
    kit: Kit, started: Path
) -> None:
    here = drafts(kit, started)
    draft = here.begin(CORE, ME)
    store = here.store
    assert draft.base == store.blob(store.accepted() or "", CORE)
    assert draft.began == ME
    assert not draft_path(started, CORE).exists()
    assert here.of(CORE) is None, "a draft stands only once it's written"
    draft_path(started, CORE).parent.mkdir(parents=True)
    draft_path(started, CORE).write_text("x = 1\n")
    assert here.of(CORE) == draft
    assert here.of(draft_path(started, CORE)) == draft
    assert here.of(started / CORE) == draft


def test_an_edit_shaped_draft_copies_the_file_as_it_stands_based_on_whats_accepted(
    kit: Kit, started: Path
) -> None:
    accepted = (started / CORE).read_text()
    unjudged = accepted + "y = 2\n"
    (started / CORE).write_text(unjudged)
    here = drafts(kit, started)
    draft = here.begin(CORE, ME, copy=True)
    assert draft_path(started, CORE).read_text() == unjudged
    assert here.store.object(draft.base or "") == accepted.encode()


def test_a_file_being_created_has_no_base(kit: Kit, started: Path) -> None:
    assert drafts(kit, started).begin(NEW, ME).base is None


def test_a_draft_written_before_it_began_is_kept_not_copied_over(
    kit: Kit, started: Path
) -> None:
    written = draft_path(started, CORE)
    written.parent.mkdir(parents=True)
    written.write_text("mine\n")
    drafts(kit, started).begin(written, ME, copy=True)
    assert written.read_text() == "mine\n"


def test_a_file_with_a_draft_standing_refuses_another(kit: Kit, started: Path) -> None:
    here = drafts(kit, started)
    here.begin(CORE, ME, copy=True)
    with pytest.raises(DraftError, match="has a draft already"):
        here.begin(CORE, Conversation(session="s2"), copy=True)


def test_no_draft_begins_where_nothing_is_accepted(kit: Kit, repo: Path) -> None:
    with pytest.raises(DraftError, match="no content is accepted"):
        drafts(kit, repo).begin(CORE, ME)


def test_an_edit_shaped_draft_of_no_file_refuses(kit: Kit, started: Path) -> None:
    with pytest.raises(DraftError, match="nothing to copy"):
        drafts(kit, started).begin(NEW, ME, copy=True)


def test_deleting_its_file_drops_a_draft_which_can_begin_again(
    kit: Kit, started: Path
) -> None:
    here = drafts(kit, started)
    here.begin(CORE, ME, copy=True)
    draft_path(started, CORE).unlink()
    assert here.of(CORE) is None
    assert here.all() == []
    assert [each.file for each in here.recorded()] == [CORE]
    again = here.begin(CORE, Conversation(session="s2"), copy=True)
    assert here.all() == [again]


def test_forgetting_a_draft_removes_its_file_record_and_empty_directories(
    kit: Kit, started: Path
) -> None:
    here = drafts(kit, started)
    hidden = Path(".github/workflows/ci.yml")
    (started / hidden).parent.mkdir(parents=True)
    (started / hidden).write_text("on: push\n")
    here.begin(hidden, ME, copy=True)
    here.begin(CORE, ME, copy=True)
    here.forget(draft_path(started, hidden))
    assert not (started / ".lup/drafts/%2Egithub").exists()
    assert [each.file for each in here.all()] == [CORE]
    assert [each.file for each in here.recorded()] == [CORE]


def test_a_rename_is_kept_with_the_draft(kit: Kit, started: Path) -> None:
    here = drafts(kit, started)
    draft = here.begin(NEW, ME)
    draft_path(started, NEW).parent.mkdir(parents=True)
    draft_path(started, NEW).write_text((started / CORE).read_text())
    here.keep(draft.model_copy(update={"renamed_from": CORE}))
    found = here.of(NEW)
    assert found is not None
    assert found.renamed_from == CORE
