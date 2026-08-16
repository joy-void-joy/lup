"""Where editing is happening, published by one process and read by another.

The writer is the hermetic hook runtime, which may not import the module that
owns the record — so the shape is a contract across a boundary no type checker
spans, and these pin both ends of it against each other.
"""

import json
from pathlib import Path

from lup.policy.assets.host import publish_edition, worktree_root
from lup.workspace.edition import Edition, read_edition


def checkout(root: Path) -> Path:
    """A directory that looks like a checkout to the walk that finds one."""
    (root / ".git").mkdir(parents=True)
    return root


def test_a_file_belongs_to_the_checkout_that_holds_it(tmp_path: Path) -> None:
    work = checkout(tmp_path / "repo")
    edited = work / "src" / "module.py"
    edited.parent.mkdir(parents=True)
    edited.write_text("x = 1\n", encoding="utf-8")

    assert worktree_root(str(edited)) == str(work)


def test_a_checkout_root_answers_for_itself(tmp_path: Path) -> None:
    """Codex hands over a directory, and the walk has to admit one.

    Only the parents were candidates, so the one directory that is already
    a checkout was answered for by whatever encloses it — or, at the top of
    a filesystem, by nothing.
    """
    work = checkout(tmp_path / "repo")

    assert worktree_root(str(work)) == str(work)


def test_a_path_in_no_checkout_names_none(tmp_path: Path) -> None:
    loose = tmp_path / "loose.py"
    loose.write_text("x = 1\n", encoding="utf-8")

    assert worktree_root(str(loose)) == ""


def test_a_relative_path_names_none(tmp_path: Path) -> None:
    """The hook is promised no working directory to resolve one against."""
    assert worktree_root("src/module.py") == ""


def test_what_the_hook_writes_is_what_the_library_reads(
    tmp_path: Path, monkeypatch
) -> None:
    """The contract: the hermetic writer cannot import the model it satisfies."""
    work = checkout(tmp_path / "repo")
    edited = work / "module.py"
    edited.write_text("x = 1\n", encoding="utf-8")
    destination = tmp_path / "state" / "edition.json"
    monkeypatch.setenv("LUP_EDITION", str(destination))

    publish_edition(str(edited))

    published = read_edition(destination)
    assert published == Edition(workspace=work, file=edited)


def test_a_later_edit_replaces_an_earlier_one(tmp_path: Path, monkeypatch) -> None:
    first = checkout(tmp_path / "one")
    second = checkout(tmp_path / "two")
    for work in (first, second):
        (work / "module.py").write_text("x = 1\n", encoding="utf-8")
    destination = tmp_path / "edition.json"
    monkeypatch.setenv("LUP_EDITION", str(destination))

    publish_edition(str(first / "module.py"))
    publish_edition(str(second / "module.py"))

    read = read_edition(destination)
    assert read is not None and read.workspace == second


def test_nothing_is_published_without_a_destination(
    tmp_path: Path, monkeypatch
) -> None:
    """Absent means nobody asked for one, which is not a failure."""
    monkeypatch.delenv("LUP_EDITION", raising=False)
    work = checkout(tmp_path / "repo")
    (work / "module.py").write_text("x = 1\n", encoding="utf-8")

    publish_edition(str(work / "module.py"))

    assert list(tmp_path.glob("**/edition.json")) == []


def test_an_unwritable_destination_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    """A verdict must never turn on this, and neither must an edit.

    The permission path already converts anything raised into a conservative
    ask. Publishing runs after the tool, where there is no verdict left to
    corrupt — but a failure that propagated would still reach that handler,
    and the edit would be answered for by a filesystem error.
    """
    work = checkout(tmp_path / "repo")
    (work / "module.py").write_text("x = 1\n", encoding="utf-8")
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("occupied\n", encoding="utf-8")
    monkeypatch.setenv("LUP_EDITION", str(blocked / "edition.json"))

    publish_edition(str(work / "module.py"))


def test_a_corrupt_record_reads_as_none(tmp_path: Path) -> None:
    """This only refines a root the caller already has, so it may decline."""
    destination = tmp_path / "edition.json"
    destination.write_text("{ not json", encoding="utf-8")

    assert read_edition(destination) is None


def test_a_missing_record_reads_as_none(tmp_path: Path) -> None:
    assert read_edition(tmp_path / "nowhere.json") is None
    assert read_edition(None) is None


def test_the_published_bytes_are_the_declared_fields(
    tmp_path: Path, monkeypatch
) -> None:
    """The hook writes JSON by hand; drift here is drift in the contract."""
    work = checkout(tmp_path / "repo")
    edited = work / "module.py"
    edited.write_text("x = 1\n", encoding="utf-8")
    destination = tmp_path / "edition.json"
    monkeypatch.setenv("LUP_EDITION", str(destination))

    publish_edition(str(edited))

    written = json.loads(destination.read_text(encoding="utf-8"))
    assert set(written) == set(Edition.model_fields)
