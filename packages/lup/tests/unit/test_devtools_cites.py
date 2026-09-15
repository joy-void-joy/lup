"""The cite sweep reads every tracked document against one fold of the log.

A repository's tracked markdown runs to a hundred files and its journal to
hundreds of thousands of lines, so a sweep that folded the log once per
document would cost a hundred parses of it. The sweep holds one fold for
every document, and a document with no cites never asks the log at all.
"""

from pathlib import Path

import pytest

from lup.coordination.refs import ActorRef
from lup.coordination.tasks import Task
from lup.devtools.dev.cites import sweep_cites
from lup.ledger import journal
from lup.ledger.journal import LedgerStore
from tests.unit.test_ledger_placement import committed, repository


def test_a_sweep_over_many_documents_folds_the_log_once(
    tmp_lup_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_lup_project)
    store = LedgerStore(root, ActorRef(kind="session", id="writer"))
    task = store.record(Task, "a task")
    (root / "cited.md").write_text(
        f"# cited\n\nHeld by [a task](lup:{task.id}).\n", encoding="utf-8"
    )
    for name in ("plain.md", "docs.md", "README.md"):
        (root / name).write_text(f"# {name}\n\nNo cite here.\n", encoding="utf-8")
    committed(root, "documents")
    monkeypatch.chdir(root)
    folds: list[int] = []
    folding = journal.Fold.__init__

    def counted(self: journal.Fold, stored: list[journal.Stored]) -> None:
        folds.append(len(stored))
        folding(self, stored)

    monkeypatch.setattr(journal.Fold, "__init__", counted)

    sweep = sweep_cites([Task])

    assert sweep.checked == 1 and sweep.failing == []
    assert len(folds) == 1
