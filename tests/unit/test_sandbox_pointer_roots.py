"""Behavior tests for anchoring a launch's roots before host git reads them.

Every root a launch mounts, and every repository sync runs git in, is judged
from what its path holds rather than from the pointer under test: a bare clone
on its own path, a worktree on the repository holding the `tree/` it sits in,
a plain checkout on its `.git` directory. One test per shape, one per way a
container could plant a config for host git to read, and one per place the
check is wired, each asserting the refusal lands before any git runs.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from lup.execution.shell import git
from lup.sandbox.pointers import (
    anchored,
    fleet_refusal,
    pointer_drift,
    root_refusal,
    tree_checkouts,
)


class Reached(Exception):
    """Raised by a stand-in for the step a refusal must come before."""


def unreachable(*_args: object, **_kwargs: object) -> None:
    raise Reached


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A plain checkout with one commit, the thing a bare clone is cut from."""
    checkout = tmp_path / "source"
    checkout.mkdir()
    git("-C", str(checkout), "init", "-q", "-b", "main")
    git("-C", str(checkout), "config", "user.email", "test@example.invalid")
    git("-C", str(checkout), "config", "user.name", "Test")
    (checkout / "README.md").write_text("readme\n", encoding="utf-8")
    git("-C", str(checkout), "add", "-A")
    git("-C", str(checkout), "commit", "-qm", "first")
    return checkout


@pytest.fixture
def clone(tmp_path: Path, source: Path) -> Path:
    """A bare clone holding its worktrees in `tree/`, as the cache and registry lay one out."""
    bare = tmp_path / "proj.git"
    git("clone", "-q", "--bare", str(source), str(bare))
    git("-C", str(bare), "worktree", "add", "-q", str(bare / "tree" / "main"), "main")
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        str(bare / "tree" / "side"),
        "-b",
        "side",
    )
    return bare


def evil_gitdir(at: Path) -> Path:
    """A gitdir a container could build anywhere it may write, config and all."""
    (at / "objects").mkdir(parents=True)
    (at / "refs").mkdir()
    (at / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (at / "config").write_text("[core]\n\thooksPath = /evil\n", encoding="utf-8")
    return at


# -- root shapes --


def test_a_bare_clone_is_anchored_on_its_own_path(clone: Path) -> None:
    assert anchored(clone).common == clone
    assert root_refusal(clone) == ""


def test_a_worktree_in_tree_is_anchored_on_the_clone_holding_it(clone: Path) -> None:
    anchor = anchored(clone / "tree" / "side")
    assert (anchor.common, anchor.linked) == (clone, True)
    assert root_refusal(clone / "tree" / "side") == ""


def test_a_resolver_worker_below_tree_is_anchored_on_the_same_clone(
    clone: Path,
) -> None:
    """A run cuts workers in `tree/<name>-resolve-<id>/`, a level below `tree/`.

    Anchoring only a direct child of `tree/` would refuse every one of them.
    """
    worker = clone / "tree" / "main-resolve-1" / "c1"
    git("-C", str(clone), "worktree", "add", "-q", "--detach", str(worker), "main")
    assert anchored(worker).common == clone
    assert root_refusal(worker) == ""
    assert worker in tree_checkouts(clone / "tree")


def test_a_plain_checkout_is_anchored_on_its_git_directory(source: Path) -> None:
    assert anchored(source).common == source / ".git"
    assert root_refusal(source) == ""


def test_a_directory_in_no_repository_passes(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    assert anchored(corpus).common is None
    assert root_refusal(corpus) == ""


def test_a_linked_worktree_outside_any_tree_is_refused_as_unanchorable(
    tmp_path: Path, source: Path
) -> None:
    """`git worktree add ../x` has no anchor but its own pointer, so it is refused."""
    elsewhere = tmp_path / "elsewhere"
    git("-C", str(source), "worktree", "add", "-q", str(elsewhere), "-b", "x")
    message = root_refusal(elsewhere)
    assert "outside any tree/" in message
    assert str(elsewhere) in message


def test_a_symlinked_dot_git_is_refused(tmp_path: Path, source: Path) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").symlink_to(source / ".git")
    assert "symlink" in root_refusal(linked)


# -- what a container could plant --


def test_a_redirected_worktree_root_is_refused(clone: Path, tmp_path: Path) -> None:
    built = evil_gitdir(tmp_path / "built")
    side = clone / "tree" / "side"
    (side / ".git").write_text(f"gitdir: {built}\n", encoding="utf-8")
    message = root_refusal(side)
    assert str(side) in message
    assert str(built) in message


def test_a_pointer_swapped_for_a_directory_is_refused(clone: Path) -> None:
    """The swap that makes a worktree look like a plain checkout with its own config."""
    side = clone / "tree" / "side"
    (side / ".git").unlink()
    evil_gitdir(side / ".git")
    assert "without being a linked worktree" in root_refusal(side)
    assert pointer_drift(clone) != []


def test_a_commondir_planted_in_the_clone_is_refused(
    clone: Path, tmp_path: Path
) -> None:
    built = evil_gitdir(tmp_path / "built")
    (clone / "commondir").write_text(f"{built}\n", encoding="utf-8")
    assert str(built) in root_refusal(clone)
    assert str(built) in root_refusal(clone / "tree" / "side")


def test_a_repository_planted_inside_tree_is_refused(clone: Path) -> None:
    """A run directory given a gitdir's shape, which discovery would stop at."""
    planted = evil_gitdir(clone / "tree" / "main-resolve-2")
    assert "without being a linked worktree" in root_refusal(planted)


def test_a_hidden_entry_is_caught_from_the_checkout(
    clone: Path, tmp_path: Path
) -> None:
    """The entry's back-pointer rewritten too, blinding a scan that starts there."""
    built = evil_gitdir(tmp_path / "built")
    side = clone / "tree" / "side"
    (side / ".git").write_text(f"gitdir: {built}\n", encoding="utf-8")
    (clone / "worktrees" / "side" / "gitdir").write_text(
        f"{tmp_path / 'gone' / '.git'}\n", encoding="utf-8"
    )
    assert pointer_drift(clone) == []
    assert pointer_drift(clone, tree_checkouts(clone / "tree")) != []


def test_an_entry_without_commondir_is_drift_only_where_it_stands_alone(
    clone: Path,
) -> None:
    """Git refuses an entry with neither `commondir` nor objects, and reads nothing."""
    entry = clone / "worktrees" / "side"
    (entry / "commondir").unlink()
    assert pointer_drift(clone) == []
    (entry / "objects").mkdir()
    (entry / "refs").mkdir(exist_ok=True)
    assert pointer_drift(clone) != []


def test_a_relative_worktree_pointer_is_not_drift(clone: Path) -> None:
    """`worktree.useRelativePaths` writes relative pointers, resolved where git does."""
    git(
        "-C",
        str(clone),
        "-c",
        "worktree.useRelativePaths=true",
        "worktree",
        "add",
        "-q",
        str(clone / "tree" / "rel"),
        "-b",
        "rel",
    )
    assert not (clone / "tree" / "rel" / ".git").read_text().split()[1].startswith("/")
    assert root_refusal(clone / "tree" / "rel") == ""
    assert pointer_drift(clone, tree_checkouts(clone / "tree")) == []


def test_fleet_refusal_names_every_refused_root(
    clone: Path, tmp_path: Path, source: Path
) -> None:
    built = evil_gitdir(tmp_path / "built")
    (clone / "tree" / "side" / ".git").write_text(
        f"gitdir: {built}\n", encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    git("-C", str(source), "worktree", "add", "-q", str(elsewhere), "-b", "x")
    message = fleet_refusal(
        [clone / "tree" / "main", clone / "tree" / "side", elsewhere]
    )
    assert str(clone / "tree" / "side") in message
    assert str(elsewhere) in message
    assert f"at {clone / 'tree' / 'main'}" not in message


# -- where it is wired --


def test_sync_refuses_a_redirected_registration_before_running_git(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lup.devtools import sync

    built = evil_gitdir(tmp_path / "built")
    side = clone / "tree" / "side"
    (side / ".git").write_text(f"gitdir: {built}\n", encoding="utf-8")
    monkeypatch.setattr(sync, "registered_upstream", unreachable)
    said: list[str] = []  # lup: ignore[empty-collection] — collects what is reported
    registration: sync.ProjectEntry = {"name": "proj", "path": str(side)}
    with pytest.raises(typer.Exit):
        sync.existing_upstream(registration)
    with pytest.raises(typer.Exit):
        sync.ensure_local(registration, said.append)
    assert any(str(built) in line for line in said)


def test_sync_refuses_a_redirected_cached_clone_before_refreshing(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lup.devtools import sync

    built = evil_gitdir(tmp_path / "built")
    (clone / "commondir").write_text(f"{built}\n", encoding="utf-8")
    monkeypatch.setattr(sync, "cached_clone", lambda _name: clone)
    monkeypatch.setattr(sync, "transport_url", lambda _proj: "https://example.invalid")
    monkeypatch.setattr(sync, "require_registered_origin", unreachable)
    monkeypatch.setattr(sync, "refresh", unreachable)
    with pytest.raises(typer.Exit):
        sync.ensure_local({"name": "proj"}, lambda _line: None)


def test_the_boundary_refuses_a_redirected_root_before_leasing_it(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both postures settle their boundary here, so both refuse here."""
    from lup.devtools.harness import launch

    side = clone / "tree" / "side"
    monkeypatch.setattr(launch, "project_root", lambda: side)
    monkeypatch.setattr(launch, "fleet_lease", unreachable)
    plugin = SimpleNamespace(hooks=None)
    arguments = {"sandbox": None, "findings": [], "sentinels": None}
    extra = {"environment": None, "banner": None}
    with pytest.raises(Reached):
        launch.settle_boundary(plugin, **arguments, **extra)  # type: ignore[arg-type]

    built = evil_gitdir(tmp_path / "built")
    (side / ".git").write_text(f"gitdir: {built}\n", encoding="utf-8")
    with pytest.raises(typer.BadParameter, match="redirected"):
        launch.settle_boundary(plugin, **arguments, **extra)  # type: ignore[arg-type]


def test_a_container_start_refuses_a_redirected_root_before_any_broker(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker launches reach the engine here without a boundary preflight."""
    from lup.devtools.harness import contained

    side = clone / "tree" / "side"
    monkeypatch.setattr(contained, "resolved_agent_clis", unreachable)
    arguments = {
        "image": None,
        "manifest": None,
        "root": side,
        "editor_rendezvous": None,
        "credential": None,
        "login": None,
        "engine": object(),
    }
    with pytest.raises(Reached):
        contained.contained_argv(**arguments)  # type: ignore[arg-type]

    built = evil_gitdir(tmp_path / "built")
    (side / ".git").write_text(f"gitdir: {built}\n", encoding="utf-8")
    with pytest.raises(typer.BadParameter, match="redirected"):
        contained.contained_argv(**arguments)  # type: ignore[arg-type]
