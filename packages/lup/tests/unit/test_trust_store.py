"""The launcher's own object store, its export, and how it reads a live checkout.

What is pinned: a tree the launcher hashes is the tree git itself would name,
an object that is not what its id says is refused rather than shown, an export
holds exactly the approved tree and never a link reaching out of it, and
reading a checkout never starts a program the checkout's configuration names.
"""

import os
from pathlib import Path, PurePosixPath

import pytest
import sh

from lup.devtools import sync
from lup.trust.approved import APPROVED_TREE_ENV, LaunchApproval, declarations_root
from lup.trust.handoff import EXPORT_MARKER, escapes, materialized
from lup.trust.objects import ObjectStore, ObjectUnreadable
from lup.trust.zone import (
    FreeZones,
    LiveCheckout,
    TrustError,
    declared_free_zones,
    host_zone,
)
from lup.workspace import paths


def run_git(cwd: Path, *arguments: str) -> str:
    """Run one git command in a fixture repository and answer its output."""
    return str(sh.Command("git")("-C", str(cwd), *arguments, _tty_out=False))


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A committed checkout holding a nested file, an executable and a symlink."""
    work = tmp_path / "work"
    run_git(tmp_path, "init", "-q", "-b", "main", str(work))
    (work / "src" / "pkg").mkdir(parents=True)
    (work / "src" / "pkg" / "module.py").write_text("value = 1\n")
    (work / "src" / "pkg-extra.txt").write_text("sorted after the directory\n")
    (work / "run.sh").write_text("#!/bin/sh\necho run\n")
    (work / "run.sh").chmod(0o755)
    (work / "link").symlink_to("src/pkg/module.py")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-q", "-m", "base")
    return work


def checkout_of(root: Path) -> LiveCheckout:
    return LiveCheckout.at(root, {"PATH": os.defpath})


def test_a_hashed_zone_is_the_tree_git_itself_writes(
    repository: Path, tmp_path: Path
) -> None:
    store = ObjectStore(root=tmp_path / "store.git").prepared()

    zone = host_zone(checkout_of(repository), store, FreeZones())

    assert zone.tree == run_git(repository, "write-tree").strip()
    listed = run_git(
        repository, "--git-dir", str(store.root), "ls-tree", "-r", zone.tree
    )
    assert "120000 blob" in listed
    assert "100755 blob" in listed


def test_an_object_that_is_not_what_its_id_says_is_refused(tmp_path: Path) -> None:
    store = ObjectStore(root=tmp_path / "store.git").prepared()
    genuine = store.write("blob", b"approved bytes\n")
    substitute = store.write("blob", b"other bytes\n")
    store.location(genuine).chmod(0o644)
    store.location(genuine).write_bytes(store.location(substitute).read_bytes())

    with pytest.raises(ObjectUnreadable, match="does not hash to its own id"):
        store.read(genuine, "blob")
    with pytest.raises(ObjectUnreadable, match="is missing"):
        store.read("0" * 40, "blob")
    with pytest.raises(ObjectUnreadable, match="is not a tree"):
        store.read(substitute, "tree")


def test_reading_a_checkout_never_runs_what_its_configuration_names(
    repository: Path, tmp_path: Path
) -> None:
    ran = tmp_path / "ran"
    program = f"touch {ran}"
    run_git(repository, "config", "core.fsmonitor", program)
    run_git(repository, "config", "filter.planted.clean", program)
    run_git(repository, "config", "filter.planted.process", program)
    (repository / ".gitattributes").write_text("* filter=planted\n")
    (repository / "hooks").mkdir()
    run_git(repository, "config", "core.hooksPath", str(repository / "hooks"))
    store = ObjectStore(root=tmp_path / "store.git").prepared()
    run_git(repository, "status", "--short")
    assert ran.exists(), (
        "the planted program must be live for this test to mean anything"
    )
    ran.unlink()

    host_zone(checkout_of(repository), store, FreeZones())

    assert not ran.exists()


def test_free_zones_are_declared_as_data_and_refused_outside_the_checkout() -> None:
    declared = declared_free_zones(
        b'[tool.lup.trust]\nfree = ["studio/", "tmp", "studio"]\n'
    )

    assert declared.free == [PurePosixPath("studio"), PurePosixPath("tmp")]
    assert declared.frees(PurePosixPath("studio/kits/painted.js"))
    assert not declared.frees(PurePosixPath("studios/other.py"))
    assert declared_free_zones(b"[project]\nname = 'x'\n").free == []
    with pytest.raises(ValueError, match="inside the checkout"):
        declared_free_zones(b'[tool.lup.trust]\nfree = ["../outside"]\n')
    with pytest.raises(ValueError, match="inside the checkout"):
        declared_free_zones(b'[tool.lup.trust]\nfree = ["."]\n')
    with pytest.raises(TrustError, match="does not parse"):
        declared_free_zones(b"[tool.lup.trust\n")


def test_an_export_holds_the_approved_tree_and_withholds_escaping_links(
    repository: Path, tmp_path: Path
) -> None:
    (repository / "escape").symlink_to("/etc/passwd")
    (repository / "climb").symlink_to("../../outside")
    run_git(repository, "add", "-A")
    store = ObjectStore(root=tmp_path / "store.git").prepared()
    zone = host_zone(checkout_of(repository), store, FreeZones())

    export = materialized(store, zone.tree, tmp_path / "exports" / zone.tree)

    assert sorted(export.withheld) == ["climb", "escape"]
    assert (export.path / "link").readlink() == Path("src/pkg/module.py")
    assert (export.path / "link").read_text() == "value = 1\n"
    assert (export.path / "run.sh").stat().st_mode & 0o111
    assert not (export.path / "escape").exists(follow_symlinks=False)
    assert (export.path / EXPORT_MARKER).read_text() == zone.tree


def test_an_interrupted_export_is_written_again_and_a_complete_one_reused(
    repository: Path, tmp_path: Path
) -> None:
    store = ObjectStore(root=tmp_path / "store.git").prepared()
    zone = host_zone(checkout_of(repository), store, FreeZones())
    destination = tmp_path / "exports" / zone.tree
    destination.mkdir(parents=True)
    (destination / "half-written.py").write_text("partial\n")

    materialized(store, zone.tree, destination)
    (destination / "src" / "pkg" / "module.py").write_text("kept\n")
    materialized(store, zone.tree, destination)

    assert not (destination / "half-written.py").exists()
    assert (destination / "src" / "pkg" / "module.py").read_text() == "kept\n"


def test_a_link_is_judged_by_where_it_lands() -> None:
    assert not escapes(PurePosixPath("a/b/link"), "../c")
    assert not escapes(PurePosixPath("link"), "./a/../b")
    assert escapes(PurePosixPath("a/link"), "../../x")
    assert escapes(PurePosixPath("link"), "/abs")


def test_the_registries_are_read_from_the_approved_snapshot_when_one_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname = "x"\n')
    export = tmp_path / "export"
    previous = paths.project_root()
    paths.configure(root=checkout)
    try:
        assert sync.local_file() == checkout / "sync.json.local"
        monkeypatch.setenv(APPROVED_TREE_ENV, str(export))
        assert sync.local_file() == export / "sync.json.local"
        assert sync.sync_file() == export / "sync.json"
    finally:
        paths.configure(root=previous)
    assert declarations_root(checkout, LaunchApproval(approved_tree=None)) == checkout
