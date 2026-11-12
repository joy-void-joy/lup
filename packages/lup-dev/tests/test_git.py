"""git as lup_dev runs it: a commit's files written from git's objects, not its archive."""

import os
from typing import TYPE_CHECKING

import pytest

from lup.programs import run
from lup_dev.git import Git, GitError, Worktree
from lup_dev.layout import Layout
from lup_dev.policy.store import Store

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import Shell

ATTRIBUTES = "stamped.py export-subst\nhidden.py export-ignore\n"
"""What `git archive` would apply: a placeholder filled in, and a file left out."""

STAMPED = '"""Stamped."""\n\nCOMMIT = "$Format:%H$"\n'


def committed(root: Path, files: dict[str, str], shell: Shell) -> str:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    shell.commit(root, "files")
    return shell.git(root, "rev-parse", "HEAD")


def test_an_export_writes_each_file_as_the_commit_holds_it(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    commit = committed(
        repo,
        {
            ".gitattributes": ATTRIBUTES,
            "stamped.py": STAMPED,
            "hidden.py": '"""Hidden from an archive."""\n',
            "docs/note.md": "# Note\n",
        },
        shell,
    )
    into = tmp_path / "export"
    Git(cwd=repo).export(commit, into)
    assert (into / "stamped.py").read_text() == STAMPED
    assert (into / "hidden.py").read_text() == '"""Hidden from an archive."""\n'
    assert (into / "docs/note.md").read_text() == "# Note\n"
    assert (into / "src/pkg/core.py").read_bytes() == (
        repo / "src/pkg/core.py"
    ).read_bytes()
    archived = shell.git(repo, "archive", "--format=tar", commit, "stamped.py")
    assert "$Format:%H$" not in archived


def test_a_replace_ref_a_room_plants_changes_neither_the_listing_nor_the_export(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    approved = '"""The declaration as approved."""\n'
    commit = committed(repo, {"lup_project.py": approved}, shell)
    listed = Git(cwd=repo).text("ls-tree", "-r", commit)
    planted = tmp_path / "planted.py"
    planted.write_text('"""A room\'s own."""\n')
    blob = shell.git(repo, "rev-parse", f"{commit}:lup_project.py")
    shell.git(repo, "replace", blob, shell.git(repo, "hash-object", "-w", str(planted)))
    assert shell.git(repo, "cat-file", "-p", blob) == '"""A room\'s own."""'
    assert Git(cwd=repo).text("ls-tree", "-r", commit) == listed
    into = tmp_path / "export"
    Git(cwd=repo).export(commit, into)
    assert (into / "lup_project.py").read_text() == approved


def test_an_export_refuses_a_blob_that_isn_t_what_its_id_says(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    commit = committed(repo, {"lup_project.py": '"""As approved."""\n'}, shell)
    blob = shell.git(repo, "rev-parse", f"{commit}:lup_project.py")
    listed = Git(cwd=repo).text("ls-tree", "-r", commit)
    shell.planted(repo / ".git" / "objects", blob, "blob", b'"""Another."""\n')
    assert Git(cwd=repo).text("ls-tree", "-r", commit) == listed
    into = tmp_path / "export"
    with pytest.raises(GitError, match=f"{blob} isn't that blob"):
        Git(cwd=repo).export(commit, into)
    assert not (into / "lup_project.py").exists()


@pytest.mark.parametrize("kind", ["commit", "tree"])
def test_an_export_refuses_a_commit_or_a_tree_that_isn_t_what_its_id_says(
    repo: Path, tmp_path: Path, shell: Shell, kind: str
) -> None:
    first = committed(repo, {"a.py": "1\n"}, shell)
    commit = committed(repo, {"a.py": "2\n"}, shell)
    named = (
        commit
        if kind == "commit"
        else shell.git(repo, "rev-parse", f"{commit}^{{tree}}")
    )
    other = (
        first if kind == "commit" else shell.git(repo, "rev-parse", f"{first}^{{tree}}")
    )
    content = run("git", "cat-file", kind, other, cwd=repo).output
    shell.planted(repo / ".git" / "objects", named, kind, content)
    with pytest.raises(GitError, match=named):
        Git(cwd=repo).export(commit, tmp_path / "export")


def test_what_a_commit_holds_is_listed_from_its_objects_as_git_lists_it(
    repo: Path, shell: Shell
) -> None:
    names = {"a-b": "1\n", "a/b.py": "2\n", "a.py": "3\n", "a0": "4\n", "é.py": "5\n"}
    commit = committed(repo, names, shell)
    (repo / "run.sh").write_text("#!/bin/sh\n")
    (repo / "run.sh").chmod(0o755)
    (repo / "link").symlink_to("a.py")
    shell.commit(repo)
    commit = shell.git(repo, "rev-parse", "HEAD")
    git = Git(cwd=repo)
    assert git.held(commit) == git.tracked(commit)
    assert git.held("HEAD") == git.tracked(commit)


def test_the_judges_export_keeps_python_and_project_files_from_the_objects(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    commit = committed(
        repo,
        {
            ".gitattributes": ATTRIBUTES,
            "stamped.py": STAMPED,
            "hidden.py": '"""Hidden from an archive."""\n',
            "stubs/typed.pyi": "x: int\n",
            "docs/note.md": "# Note\n",
        },
        shell,
    )
    store = Store(layout=Layout(state=tmp_path / "state").store(repo), worktree=repo)
    into = tmp_path / "declaration"
    store.export(commit, into)
    written = sorted(
        path.relative_to(into).as_posix() for path in into.rglob("*") if path.is_file()
    )
    assert written == [
        "hidden.py",
        "pyproject.toml",
        "src/pkg/__init__.py",
        "src/pkg/core.py",
        "stamped.py",
        "stubs/typed.pyi",
        "tests/test_core.py",
    ]
    assert (into / "stamped.py").read_text() == STAMPED


def test_an_export_keeps_the_executable_bit_and_a_link_inside(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    (repo / "run.sh").write_text("#!/bin/sh\n")
    (repo / "run.sh").chmod(0o755)
    (repo / "AGENTS.md").write_text("# Agents\n")
    (repo / "CLAUDE.md").symlink_to("AGENTS.md")
    shell.commit(repo, "a script and a link")
    into = tmp_path / "export"
    Git(cwd=repo).export(shell.git(repo, "rev-parse", "HEAD"), into)
    assert (into / "run.sh").stat().st_mode & 0o111
    assert (into / "CLAUDE.md").is_symlink()
    assert (into / "CLAUDE.md").read_text() == "# Agents\n"


def test_an_export_refuses_a_link_outside_it(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    (repo / "escape").symlink_to("../../outside")
    shell.commit(repo, "a link outside")
    into = tmp_path / "export"
    with pytest.raises(GitError, match=r"a link to \.\./\.\./outside"):
        Git(cwd=repo).export(shell.git(repo, "rev-parse", "HEAD"), into)


def test_an_export_reads_in_batches(repo: Path, tmp_path: Path, shell: Shell) -> None:
    commit = committed(repo, {f"many/{n}.py": f"N = {n}\n" for n in range(7)}, shell)
    into = tmp_path / "export"
    Git(cwd=repo).export(commit, into, batch=3)
    assert [(into / f"many/{n}.py").read_text() for n in range(7)] == [
        f"N = {n}\n" for n in range(7)
    ]


def test_contents_refuses_a_blob_that_isn_t_what_its_id_says(
    repo: Path, shell: Shell
) -> None:
    commit = committed(repo, {"a.py": "1\n"}, shell)
    blob = shell.git(repo, "rev-parse", f"{commit}:a.py")
    assert Git(cwd=repo).contents([blob]) == [b"1\n"]
    shell.planted(repo / ".git" / "objects", blob, "blob", b"2\n")
    with pytest.raises(GitError, match=f"{blob} isn't that blob"):
        Git(cwd=repo).contents([blob])


def test_a_missing_object_is_refused(repo: Path) -> None:
    with pytest.raises(GitError, match="not its size"):
        Git(cwd=repo).contents(["0" * 40])


def test_a_revision_naming_no_commit_is_none(repo: Path, shell: Shell) -> None:
    git = Git(cwd=repo)
    assert git.commit("HEAD") == shell.git(repo, "rev-parse", "HEAD")
    assert git.commit("refs/heads/nowhere") is None


def test_the_commits_a_push_publishes_are_those_beyond_what_the_remote_holds(
    repo: Path, shell: Shell
) -> None:
    held = shell.git(repo, "rev-parse", "HEAD")
    committed(repo, {"one.md": "one\n"}, shell)
    first = shell.git(repo, "rev-parse", "HEAD")
    tip = committed(repo, {"two.md": "two\n"}, shell)
    git = Git.pinned(repo / ".git")
    assert git.walked([tip], [held]) == [first, tip]
    assert git.walked([tip], [held, "0" * 40]) == [first, tip]
    assert git.walked([tip], [tip]) == []


def test_the_store_says_which_objects_it_holds_as_blobs(
    repo: Path, shell: Shell
) -> None:
    readme = shell.git(repo, "rev-parse", "HEAD:README.md")
    tree = shell.git(repo, "rev-parse", "HEAD^{tree}")
    git = Git.pinned(repo / ".git")
    assert git.blobs(["0" * 40, readme, tree]) == [readme]
    assert git.blobs([]) == []


def test_a_partial_clone_is_never_asked_for_what_it_left_out(
    repo: Path, tmp_path: Path, shell: Shell
) -> None:
    (repo / "README.md").write_text("# Work, again\n")
    shell.commit(repo, "again")
    first = shell.git(repo, "rev-parse", "HEAD~1:README.md")
    shell.git(repo, "config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "partial"
    shell.git(
        tmp_path, "clone", "-q", "--filter=blob:none", f"file://{repo}", str(clone)
    )
    git = Git.pinned(clone / ".git")

    assert git.blobs([first]) == []
    # Asked as git is by default, the clone fetches it from its remote.
    assert shell.git(clone, "cat-file", "-t", first) == "blob"
    assert git.blobs([first]) == [first]


def test_a_branch_s_checkout_is_the_worktree_that_has_it_checked_out(
    bare: Path, shell: Shell
) -> None:
    shell.git(bare, "branch", "dev", "main")
    shell.git(bare, "branch", "live", "main")
    dev = bare / "tree" / "dev"
    shell.git(bare, "worktree", "add", "-q", str(dev), "dev")
    pinned = Git.pinned(bare)
    assert pinned.checkout("dev") == dev
    assert pinned.checkout("main") == bare / "tree" / "main"
    # Nothing has it checked out, as a bare repository's own directory doesn't count.
    assert pinned.checkout("live") is None
    assert pinned.checkout("none") is None


def test_a_checkout_that_s_gone_is_no_checkout(bare: Path, shell: Shell) -> None:
    shell.git(bare, "branch", "dev", "main")
    dev = bare / "tree" / "dev"
    shell.git(bare, "worktree", "add", "-q", str(dev), "dev")
    dev.rename(dev.with_name("moved"))
    assert Git.pinned(bare).checkout("dev") is None


def test_git_reads_what_a_commit_holds_from_the_commit_whatever_a_commit_graph_says(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, {"a.py": "1\n"}, shell)
    tip = committed(root, {"b.py": "2\n"}, shell)
    shell.forged_tree(bare, tip, old)
    listed = Git.pinned(bare).text("diff", "--name-only", "--no-renames", old, tip)
    assert listed == "b.py"


def test_git_reads_a_commit_s_parents_from_the_commit_whatever_a_graft_says(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    base = committed(root, {"a.py": "1\n"}, shell)
    shell.git(root, "switch", "-q", "-c", "side")
    side = committed(root, {"side.py": "2\n"}, shell)
    shell.git(root, "switch", "-q", "main")
    tip = committed(root, {"tip.py": "3\n"}, shell)
    (bare / "info" / "grafts").write_text(f"{tip} {side}\n")
    git = Git.pinned(bare)
    assert git.text("merge-base", tip, side) == base
    assert git.text("log", "-1", "--format=%P", tip) != side


def test_a_commits_subject_is_read_from_its_own_bytes(repo: Path, shell: Shell) -> None:
    (repo / "a.txt").write_text("a\n")
    shell.git(repo, "add", "a.txt")
    shell.git(repo, "commit", "-q", "-m", "the subject\n\nthe body")
    head = shell.git(repo, "rev-parse", "HEAD")
    assert Git(cwd=repo).subject(head) == "the subject"


def test_a_commits_subject_refuses_what_isnt_that_commit(
    repo: Path, shell: Shell
) -> None:
    (repo / "a.txt").write_text("a\n")
    shell.git(repo, "add", "a.txt")
    shell.git(repo, "commit", "-q", "-m", "the subject")
    blob = shell.git(repo, "rev-parse", "HEAD:a.txt")
    with pytest.raises(GitError, match="isn't that commit"):
        Git(cwd=repo).subject(blob)


# A repository's worktrees


def planted(bare: Path, name: str, gitdir: str) -> None:
    """Write an entry under the git directory's `worktrees/`, as a room can, naming `gitdir` as a worktree's `.git`."""
    entry = bare / "worktrees" / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "gitdir").write_text(f"{gitdir}\n")
    (entry / "HEAD").write_text("ref: refs/heads/main\n")
    (entry / "commondir").write_text("../..\n")


@pytest.mark.parametrize(
    "plant",
    [
        "the directory holding the repository",
        "another repository",
        "another repository's worktree",
        "another repository, by a path out of the tree through `..`",
    ],
)
def test_a_directory_a_room_names_as_a_worktree_isnt_one(
    bare: Path, repo: Path, linked: Path, tmp_path: Path, plant: str
) -> None:
    gitdir = {
        "the directory holding the repository": tmp_path / ".git",
        "another repository": repo / ".git",
        "another repository's worktree": linked / ".git",
        "another repository, by a path out of the tree through `..`": (
            f"{bare}/tree/../../{repo.name}/.git"
        ),
    }[plant]
    planted(bare, "planted", str(gitdir))

    assert Git.pinned(bare).worktrees() == [bare, bare / "tree" / "main"]


def test_a_link_into_a_worktree_isnt_the_worktree(bare: Path, tmp_path: Path) -> None:
    worktree = bare / "tree" / "main"
    current = tmp_path / "current"
    current.symlink_to(worktree)
    # The room names the link, which an operator keeps outside the tree, as
    # the worktree's place: its `.git`, read through the link, names the entry
    # back.
    (bare / "worktrees" / "main" / "gitdir").write_text(f"{current}/.git\n")

    assert Git.pinned(bare).worktrees() == [bare]


def test_a_worktree_git_adds_is_listed_with_its_own_git_directory(
    bare: Path, repo: Path, linked: Path, shell: Shell
) -> None:
    shell.git(
        bare, "worktree", "add", "-q", "--relative-paths", "-b", "rel", "tree/rel"
    )

    assert Git.pinned(bare).listed() == [
        Worktree(root=bare),
        Worktree(
            root=bare / "tree" / "main",
            own=bare / "worktrees" / "main",
            branch="refs/heads/main",
            head=shell.git(bare, "rev-parse", "main"),
        ),
        Worktree(
            root=bare / "tree" / "rel",
            own=bare / "worktrees" / "rel",
            branch="refs/heads/rel",
            head=shell.git(bare, "rev-parse", "main"),
        ),
    ]
    # A clone's worktree beside it, outside its own directory, is one too.
    assert Git.pinned(repo / ".git").worktrees() == [repo, linked]
    assert Git(cwd=linked).worktrees() == [repo, linked]


def test_git_within_a_worktree_reads_no_config_through_its_links(
    bare: Path, tmp_path: Path, shell: Shell
) -> None:
    worktree = bare / "tree" / "main"
    ran = tmp_path / "ran"
    # A git directory of the room's own, inside the tree, whose `config` names
    # a clean filter, which writes down each file it reads; the worktree's
    # files go through it.
    own = worktree / "own.git"
    shell.git(tmp_path, "init", "-q", "--bare", str(own))
    shell.git(
        own, "config", "filter.probe.clean", f"sh -c 'echo $1 >> {ran}; cat' - %f"
    )
    (worktree / ".gitattributes").write_text("* filter=probe\n")
    (worktree / "probe.txt").write_text("probe\n")
    shell.git(worktree, "add", ".gitattributes", "probe.txt")
    # One has changed on disk since it was staged, to as many bytes at another
    # time, so `git status` reads it to tell, and, finding it changed, leaves
    # its entry in the index as it was: the second `status` reads what the
    # first did. Only touched, it was written back as clean by the first, and
    # the second read nothing of it: that one ran the filter only on a file
    # git took as racily clean, written in the same second as the index, and
    # missed it in 133 of 2000 runs on 96 workers on 2026-11-12.
    (worktree / "probe.txt").write_text("PROBE\n")
    os.utime(worktree / "probe.txt", (0, 0))
    (bare / "worktrees" / "main" / "commondir").write_text(f"{own}\n")
    [listed] = [each for each in Git.pinned(bare).listed() if each.root == worktree]

    Git.within(bare, listed).run("status", "--porcelain")

    assert not ran.exists()
    # Found from the worktree, git reads the room's `config`, and runs its
    # filter on the file the pinned `status` read.
    Git(cwd=worktree).run("status", "--porcelain")
    assert "probe.txt" in ran.read_text().splitlines()
