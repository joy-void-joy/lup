"""One log in two journals, placed per kind: a committed kind's records travel
with the code and merge by union, a local kind's stay under the git directory,
and every reader folds both into one log with one id space."""

from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Blocks, Task
from lup.devtools.roster import writeup_writers
from lup.execution.shell import git
from lup.ledger.journal import LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode, Placement
from lup.ledger.store import InTree, LedgerLayout, merges_by_union
from lup.ledger.views import kinds_view
from lup.ledger.writeup import Listing, Stamp, Writeup

AUTHOR = ActorRef(kind="test", id="t")


class Note(LedgerNode, frozen=True):
    """A kind the layout leaves local."""

    kind: Literal["test:note"] = "test:note"


class Mentions(LedgerEdge, frozen=True):
    """A relation drawn between any two nodes."""

    kind: Literal["test:mentions"] = "test:mentions"


LAYOUT = LedgerLayout(committed=InTree(), placements={Task: "committed"})
"""Tasks committed, everything else local."""


def repository(root: Path) -> Path:
    git("init", "-q", "-b", "main", str(root))
    git("-C", str(root), "config", "user.email", "t@example.test")
    git("-C", str(root), "config", "user.name", "t")
    return root


def committed(root: Path, message: str) -> None:
    git("-C", str(root), "add", "-A")
    git("-C", str(root), "commit", "-q", "-m", message)


def placed(store: LedgerStore) -> dict[str, Placement]:
    """Which journal holds each record: a node by its id, an edge by its ends."""
    return {
        str(each.line["id"])
        if "id" in each.line
        else f"{each.line['source']}->{each.line['target']}": each.placement
        for each in store.stored()
    }


def test_a_record_goes_to_the_journal_its_kind_declares(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path, AUTHOR, LAYOUT)

    kept = store.record(Task, "kept")
    scratch = store.record(Note, "scratch")

    assert store.journal("committed") == tmp_path / "ledger" / "journal.jsonl"
    assert store.journal("local") == tmp_path / "lup" / "ledger" / "journal.jsonl"
    assert placed(store) == {kept.id: "committed", scratch.id: "local"}
    # One id space: every reader folds both journals into one log.
    assert [node.id for node in store.all_nodes([Task, Note])] == [kept.id, scratch.id]
    assert store.read(Task) == [kept] and store.read(Note) == [scratch]
    assert store.resolve(scratch.id, [Task, Note]) == scratch


def test_an_edge_is_committed_only_where_both_of_its_ends_are(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path, AUTHOR, LAYOUT)
    first = store.record(Task, "first")
    second = store.record(Task, "second")
    note = store.record(Note, "note")

    store.relate(Blocks, first, second)
    store.relate(Mentions, note, first)
    store.relate(Mentions, second, note)

    assert placed(store) == {
        first.id: "committed",
        second.id: "committed",
        note.id: "local",
        f"{first.id}->{second.id}": "committed",
        f"{note.id}->{first.id}": "local",
        f"{second.id}->{note.id}": "local",
    }
    # The fold still answers "what points at this node" across both journals.
    assert {edge.source for edge in store.into(first.id)} == {note.id}
    assert {edge.target for edge in store.out_of(second.id)} == {note.id}


def test_a_kind_that_never_declares_a_committed_half_keeps_one_journal(
    tmp_path: Path,
) -> None:
    store = LedgerStore(tmp_path, AUTHOR)
    recorded = store.record(Task, "kept")

    assert store.roots == {"local": tmp_path / "lup" / "ledger"}
    assert placed(store) == {recorded.id: "local"}
    assert LedgerLayout().describe() == "every kind shared under the git directory"


def test_a_duplicate_id_across_the_two_journals_folds_latest_wins(
    tmp_path: Path,
) -> None:
    # A kind moved from local to committed: its lines were copied across, and
    # the copy in the journal the kind now declares has since been amended.
    before = LedgerStore(tmp_path, AUTHOR, LedgerLayout(committed=InTree()))
    task = before.record(Task, "as recorded")
    after = LedgerStore(tmp_path, AUTHOR, LAYOUT)
    after.journal("committed").write_text(
        after.journal("local").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert [each.title for each in after.read(Task)] == ["as recorded"]
    after.amend(task.model_copy(update={"title": "as amended"}))

    assert [each.title for each in after.read(Task)] == ["as amended"]
    assert placed(after) == {task.id: "committed"}


def test_blobs_land_beside_the_journal_of_the_node_attaching_them(
    tmp_path: Path,
) -> None:
    store = LedgerStore(tmp_path, AUTHOR, LAYOUT)

    kept = store.record(Task, "kept", attachments=[b"proof"])
    scratch = store.record(Note, "scratch", attachments=[b"draft"])

    [proof] = kept.attachments
    [draft] = scratch.attachments
    assert (tmp_path / "ledger" / "blobs" / proof).read_bytes() == b"proof"
    assert (tmp_path / "lup" / "ledger" / "blobs" / draft).read_bytes() == b"draft"
    assert not (tmp_path / "lup" / "ledger" / "blobs" / proof).exists()
    assert store.blobs.read(proof) == b"proof" and store.blobs.read(draft) == b"draft"
    assert store.blobs.holds(proof) and store.blobs.holds(draft)
    assert store.blobs.read("0" * 64) is None


def test_a_committed_kind_needs_a_committed_half_at_declaration() -> None:
    with pytest.raises(ValidationError, match="coordination:task placed committed"):
        LedgerLayout(placements={Task: "committed"})

    assert LedgerLayout(placements={Task: "local"}).placement("coordination:task") == (
        "local"
    )
    assert LAYOUT.placement("coordination:task") == "committed"
    assert LAYOUT.placement("test:note") == "local"
    assert LAYOUT.tracked(["coordination:task"])
    assert not LAYOUT.tracked(["coordination:task", "test:note"])
    assert LAYOUT.tracked([])


def test_the_committed_journal_has_to_be_declared_to_merge_by_union(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path / "repo")
    layout = LedgerLayout(committed=InTree())

    assert not merges_by_union(root, InTree().journal())
    [problem] = layout.problems(root)
    assert '"ledger/journal.jsonl merge=union"' in problem
    (root / ".gitattributes").write_text(
        "ledger/journal.jsonl merge=union\n", encoding="utf-8"
    )
    assert merges_by_union(root, InTree().journal())
    assert layout.problems(root) == []
    assert LedgerLayout().problems(root) == []
    assert layout.describe() == (
        "committed kinds in the tree at ledger/, merged by union;"
        " local kinds shared under the git directory"
    )
    # Outside any repository nothing answers, which reads as undeclared.
    assert layout.problems(tmp_path) == [problem]


def test_two_branches_that_both_appended_merge_losslessly(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    (root / ".gitattributes").write_text(
        "ledger/journal.jsonl merge=union\n", encoding="utf-8"
    )
    store = LedgerStore(root, AUTHOR, LAYOUT)
    base = store.record(Task, "base")
    committed(root, "base")
    git("-C", str(root), "switch", "-q", "-c", "left")
    left = store.record(Task, "left")
    committed(root, "left")
    git("-C", str(root), "switch", "-q", "main")
    right = store.record(Task, "right")
    committed(root, "right")

    git("-C", str(root), "merge", "-q", "--no-edit", "left")

    assert {task.id for task in store.read(Task)} == {base.id, left.id, right.id}
    assert store.movements()[base.id] == base.at


def test_snapshot_copies_the_local_half_and_says_the_rest_is_in_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path / "repo")
    monkeypatch.setattr(ledger_app, "project_root", lambda: root)
    app = ledger_app.create_ledger_app([Task, Note], [], layout=LAYOUT)
    store = LedgerStore(root, AUTHOR, LAYOUT)

    nothing = CliRunner().invoke(app, ["snapshot"])
    kept = store.record(Task, "kept")
    scratch = store.record(Note, "scratch")
    taken = CliRunner().invoke(app, ["snapshot"])

    assert nothing.exit_code == 1 and "nothing local" in nothing.output
    assert taken.exit_code == 0, taken.output
    assert "already in git" in taken.output
    snapshotted = str(git("-C", str(root), "show", "lup/ledger:journal.jsonl"))
    assert scratch.id in snapshotted and kept.id not in snapshotted


def test_types_says_which_half_each_node_kind_is_written_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    app = ledger_app.create_ledger_app([Task, Note], [Mentions], layout=LAYOUT)

    listed = CliRunner().invoke(app, ["types"])

    assert listed.exit_code == 0, listed.output
    assert "coordination:task  (Task, committed)" in listed.output
    assert "test:note  (Note, local)" in listed.output
    assert "test:mentions  (Mentions)" in listed.output
    view = kinds_view([Task, Note], [Mentions], LAYOUT)
    assert [kind.placement for kind in view.nodes] == ["committed", "local"]
    assert [kind.placement for kind in view.edges] == [""]


def test_a_writeup_is_a_repository_writer_only_over_committed_kinds(
    tmp_path: Path,
) -> None:
    over_tasks = Writeup(
        name="tasks",
        path="docs/tasks.md",
        source="tests",
        parts=[
            Listing(heading="Tasks", of="coordination:task", empty="None."),
            Stamp(of=["coordination:task"]),
        ],
    )
    over_notes = Writeup(
        name="notes",
        path="docs/notes.md",
        source="tests",
        parts=[Listing(heading="Notes", of="test:note")],
    )
    naming = Writeup(
        name="named",
        path="docs/named.md",
        source="tests",
        parts=[Listing(heading="Named", nodes=["kept"])],
    )
    whole = Writeup(name="whole", path="docs/whole.md", source="tests", parts=[Stamp()])
    store = LedgerStore(tmp_path, AUTHOR, LAYOUT)
    store.record(Task, "kept")
    store.record(Note, "scratch")

    assert over_tasks.kinds() == ["coordination:task"]
    assert over_notes.kinds() == ["test:note"]
    assert naming.kinds() is None and whole.kinds() is None
    assert writeup_writers(LedgerLayout(), [over_tasks], [Task]) == []
    [write] = writeup_writers(
        LAYOUT, [over_tasks, over_notes, naming, whole], [Task, Note]
    )
    written = write(tmp_path)

    text = written.read_text(encoding="utf-8")
    assert written == tmp_path / "docs" / "tasks.md"
    assert "kept" in text and "scratch" not in text
    # The stamp counts the kinds the document renders and nothing else.
    assert "1 node(s), 0 edge(s)" in text
    assert write(tmp_path, check=True) == written
