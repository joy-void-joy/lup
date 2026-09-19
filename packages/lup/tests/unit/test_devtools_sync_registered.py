"""A registration naming a path is read where its owner works: a checkout at HEAD, a bare clone at its named branch.

The failure this answers: marking a linked library synced recorded the
bare clone's HEAD — the default branch — as the checkpoint, which sat
behind the branch the project actually links against, so the checkpoint
moved backwards.
"""

from pathlib import Path

import sh

from lup.devtools.sync import registered_upstream


def repository(root: Path) -> sh.Command:
    root.mkdir(parents=True)
    git = sh.git.bake("-C", str(root), "-c", "user.email=t@x", "-c", "user.name=t")
    git("init", "-q", "-b", "main")
    (root / "a").write_text("a\n", encoding="utf-8")
    git("add", "a")
    git("commit", "-q", "-m", "one")
    return git


def test_a_bare_clone_is_read_at_the_branch_the_registration_names(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    git = repository(source)
    git("branch", "dev")
    git("checkout", "-q", "dev")
    (source / "b").write_text("b\n", encoding="utf-8")
    git("add", "b")
    git("commit", "-q", "-m", "two")
    bare = tmp_path / "bare.git"
    sh.git("clone", "-q", "--bare", str(source), str(bare))
    sh.git("-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main")
    (bare / "tree").mkdir()
    sh.git("-C", str(bare), "worktree", "add", "-q", str(bare / "tree" / "dev"), "dev")

    linked = registered_upstream(
        {"name": "lib", "path": str(bare), "branch": "dev"}, bare
    )
    unattached = registered_upstream(
        {"name": "lib", "path": str(bare), "branch": "main"}, bare
    )
    plain = registered_upstream({"name": "lib", "path": str(source)}, source)

    assert linked.checkout == bare / "tree" / "dev" and linked.tip == "refs/heads/dev"
    dev_tip = sh.git("-C", str(source), "rev-parse", "dev").strip()
    assert (
        sh.git("-C", str(linked.checkout), "rev-parse", linked.tip).strip() == dev_tip
    )
    assert unattached.checkout == bare and unattached.tip == "refs/heads/main"
    assert plain.checkout == source and plain.tip == "HEAD"
