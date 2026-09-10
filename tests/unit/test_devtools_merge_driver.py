"""Behavior tests for the merge driver the generated trees are declared under.

Everything under those trees is compiled from typed source, so two branches
always disagree on every digest and every emitted line a regeneration touched.
Merging that text has no meaning: the driver keeps one side so the merge
resolves, and regeneration settles the tree against the merged source
afterwards.

For one file it is worse than meaningless. The compiled dispatcher is executed
for every routed call, so a text merge that leaves conflict markers in it
leaves a script that will not parse — and the boundary answers every shell
command and every edit by refusing, the merge it would take to undo included.
"""

import ast
import json
from pathlib import Path

import pytest
import sh

from lup.devtools.dev import worktree
from tests.unit.repos import initialized_repo

ATTRIBUTES = Path(__file__).parents[2] / ".gitattributes"
MANIFESTS = (".claude/.lup-ownership.json", ".codex/.lup-ownership.json")
DISPATCHERS = (
    ".claude/plugins/lup/hooks/scripts/policy.py",
    ".codex/plugins/lup/hooks/scripts/policy.py",
)
"""The compiled dispatchers, whose conflict markers refuse a whole session.

A mismerged manifest only misleads whoever reads it. These are executed by the
runtime for every routed call, so markers in one leave a script that will not
parse, and the boundary refuses the shell command that would have aborted the
merge that wrote them.
"""

GENERATED = MANIFESTS + DISPATCHERS


def manifest(digest: str) -> str:
    """Render a manifest shaped like the real proof, differing only in digests."""
    return json.dumps(
        {
            "schema_version": 1,
            "generator_version": "0.2.0",
            "source_digest": digest,
            "target_requirements": ["claude-code"],
            "files": [
                {
                    "path": ".claude/CLAUDE.md",
                    "category": "generated",
                    "sha256": digest,
                    "semantic_id": "harness.guidance",
                    "executable": False,
                }
            ],
        },
        indent=2,
    )


def dispatcher(marker: str) -> str:
    """Render a compiled dispatcher, differing only where a regeneration would."""
    return f'#!/usr/bin/env python3\n\n\ndef main():\n    return "{marker}"\n'


def write_generated(work: Path, marker: str) -> None:
    """Lay down every generated file this repository's attributes declare."""
    for name in GENERATED:
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dispatcher(marker) if name in DISPATCHERS else manifest(marker)
        path.write_text(body, encoding="utf-8")


def bare_git(work: Path) -> sh.Command:
    return sh.Command("git").bake(
        "-C", str(work), "-c", "commit.gpgsign=false", _tty_out=False
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    (work / ".claude").mkdir(parents=True)
    (work / ".codex").mkdir(parents=True)
    git = initialized_repo(work, tmp_path / "no-hooks")
    (work / ".gitattributes").write_text(
        ATTRIBUTES.read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_generated(work, "base")
    git("add", "-A")
    git("commit", "-m", "chore: base")

    git("switch", "-c", "feature")
    write_generated(work, "feature")
    git("add", "-A")
    git("commit", "-m", "feat: regenerate on the feature branch")

    git("switch", "main")
    write_generated(work, "main")
    (work / "unrelated.txt").write_text("main moved on\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "feat: regenerate on main")

    git("switch", "feature")
    return work


def unmerged(work: Path) -> list[str]:
    out = bare_git(work)("diff", "--name-only", "--diff-filter=U", _ok_code=[0, 1])
    return str(out).split()


def drop_driver(work: Path) -> None:
    bare_git(work)(
        "config", "--unset-all", "merge.lup-ownership.driver", _ok_code=[0, 5]
    )


def test_the_attributes_cover_every_generated_file(repo: Path) -> None:
    """A build product the attributes do not reach keeps conflicting silently.

    Asked of git rather than of the text, because the declaration is written
    as tree-wide patterns: whether one reaches a given path is git's own
    matching, and a test reading the file back would be a second, weaker copy
    of it that agrees with the real answer only by luck.
    """
    reported = bare_git(repo)("check-attr", "merge", "--", *GENERATED)

    assert str(reported).splitlines() == [
        f"{name}: merge: lup-ownership" for name in GENERATED
    ]


def test_a_divergent_generated_tree_merges_without_conflict(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    worktree.register_merge_driver()

    bare_git(repo)("merge", "main", "-m", "Merge branch 'main' into feature")

    assert unmerged(repo) == []
    assert (repo / "unrelated.txt").exists()
    for name in MANIFESTS:
        kept = json.loads((repo / name).read_text(encoding="utf-8"))
        assert kept["source_digest"] == "feature"
    for name in DISPATCHERS:
        kept_script = (repo / name).read_text(encoding="utf-8")
        assert kept_script == dispatcher("feature")
        ast.parse(kept_script)


def test_without_the_driver_the_dispatcher_conflicts(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git resolves driver names from config, so an unregistered clone degrades.

    Pinned rather than left implied: this is the shape of the lockout, and the
    declaration alone does not close it. Anything merging outside a clone that
    registered the driver — a forge's own merge button — lands here.
    """
    monkeypatch.chdir(repo)
    drop_driver(repo)

    with pytest.raises(sh.ErrorReturnCode):
        bare_git(repo)("merge", "main", "-m", "Merge branch 'main' into feature")

    assert sorted(unmerged(repo)) == sorted(GENERATED)
    for name in DISPATCHERS:
        with pytest.raises(SyntaxError):
            ast.parse((repo / name).read_text(encoding="utf-8"))


def test_a_rebase_replays_across_a_divergent_manifest(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conflict that stops a rebase mid-replay is the one that has to go.

    Each commit carries a source change beside its regenerated manifest, the
    shape a real one has — the manifest moved *because* the source did.
    """
    monkeypatch.chdir(repo)
    worktree.register_merge_driver()
    git = bare_git(repo)

    for step in ("second", "third"):
        (repo / f"{step}.py").write_text(f"# {step}\n", encoding="utf-8")
        write_generated(repo, step)
        git("add", "-A")
        git("commit", "-m", f"feat: {step}")

    git("rebase", "main")

    assert unmerged(repo) == []
    assert str(git("rev-parse", "--abbrev-ref", "HEAD")).strip() == "feature"
    subjects = str(git("log", "--format=%s", "main..HEAD")).splitlines()
    assert subjects == ["feat: third", "feat: second"]
    assert (repo / "unrelated.txt").exists()


def test_a_regeneration_only_commit_does_not_survive_a_rebase(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keeping one side empties a patch that carried nothing else, so git drops it.

    A commit whose whole content is a rebuilt tree has nothing left to say once
    regeneration settles it against the merged source, and the tree it would
    have written is reproduced from that source either way.
    """
    monkeypatch.chdir(repo)
    worktree.register_merge_driver()
    git = bare_git(repo)

    git("rebase", "main")

    assert unmerged(repo) == []
    assert str(git("log", "--format=%s", "main..HEAD")).splitlines() == []


def test_an_unregistered_driver_is_a_readable_state_not_a_silent_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `dev check` reads, so a checkout degrading has somewhere to show.

    The declaration is in the repository and the registration is not, so a
    clone that never ran `worktree create` carries the attributes, resolves
    the name to nothing, and text-merges the generated trees without saying
    a word about it.
    """
    monkeypatch.chdir(repo)
    worktree.register_merge_driver()
    assert worktree.MergeDriver().satisfied()

    drop_driver(repo)

    assert not worktree.MergeDriver().satisfied()
