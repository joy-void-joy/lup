"""Where a repository keeps its log: shared under the git directory by default,
or declared in the tree, where the journal travels with commits and two
branches that both appended merge by union."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import lup.devtools.ledger.app as ledger_app
from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Task
from lup.devtools.roster import writeup_writers
from lup.execution.shell import git
from lup.ledger.journal import LedgerStore
from lup.ledger.store import InTree, SharedStore, ledger_root, merges_by_union
from lup.ledger.writeup import Listing, Writeup

AUTHOR = ActorRef(kind="test", id="t")


def repository(root: Path) -> Path:
    git("init", "-q", "-b", "main", str(root))
    git("-C", str(root), "config", "user.email", "t@example.test")
    git("-C", str(root), "config", "user.name", "t")
    return root


def committed(root: Path, message: str) -> None:
    git("-C", str(root), "add", "-A")
    git("-C", str(root), "commit", "-q", "-m", message)


def test_the_placement_decides_where_the_store_writes(tmp_path: Path) -> None:
    shared = LedgerStore(tmp_path, AUTHOR)
    in_tree = LedgerStore(tmp_path, AUTHOR, InTree())
    elsewhere = LedgerStore(tmp_path, AUTHOR, InTree(path=Path("notes/log")))

    assert shared.path == tmp_path / "lup" / "ledger" / "journal.jsonl"
    assert in_tree.path == tmp_path / "ledger" / "journal.jsonl"
    assert elsewhere.path == tmp_path / "notes" / "log" / "journal.jsonl"
    assert ledger_root(tmp_path) == SharedStore().root(tmp_path)
    recorded = in_tree.record(Task, "kept in the tree")
    assert [task.id for task in in_tree.read(Task)] == [recorded.id]
    assert shared.read(Task) == []


def test_an_in_tree_journal_has_to_be_declared_to_merge_by_union(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path / "repo")
    placement = InTree()

    assert not merges_by_union(root, placement.journal())
    [problem] = placement.problems(root)
    assert '"ledger/journal.jsonl merge=union"' in problem
    (root / ".gitattributes").write_text(
        "ledger/journal.jsonl merge=union\n", encoding="utf-8"
    )
    assert merges_by_union(root, placement.journal())
    assert placement.problems(root) == []
    assert SharedStore().problems(root) == []
    # Outside any repository nothing answers, which reads as undeclared.
    assert placement.problems(tmp_path) == [problem]


def test_two_branches_that_both_appended_merge_losslessly(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    (root / ".gitattributes").write_text(
        "ledger/journal.jsonl merge=union\n", encoding="utf-8"
    )
    store = LedgerStore(root, AUTHOR, InTree())
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


def test_snapshot_refuses_where_the_log_is_committed_with_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_app, "project_root", lambda: tmp_path)
    LedgerStore(tmp_path, AUTHOR, InTree()).record(Task, "kept")
    app = ledger_app.create_ledger_app([Task], [], placement=InTree())

    refused = CliRunner().invoke(app, ["snapshot"])
    listed = CliRunner().invoke(app, ["list"])

    assert refused.exit_code == 1 and "committed with the code" in refused.output
    assert listed.exit_code == 0 and "kept" in listed.output


def test_writeups_join_the_generation_only_where_the_log_is_in_the_tree(
    tmp_path: Path,
) -> None:
    writeup = Writeup(
        name="tasks",
        path="docs/tasks.md",
        source="tests",
        parts=[Listing(heading="Tasks", of="coordination:task", empty="None.")],
    )
    LedgerStore(tmp_path, AUTHOR, InTree()).record(Task, "kept")

    assert writeup_writers(SharedStore(), [writeup], [Task]) == []
    [write] = writeup_writers(InTree(), [writeup], [Task])
    written = write(tmp_path)

    assert "kept" in written.read_text(encoding="utf-8")
    assert write(tmp_path, check=True) == written
