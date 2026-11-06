"""What a landing reads of its own diff: each file's role, by the objects' own bytes."""

import hashlib
import subprocess
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import Project
from lup_dev.declaration.resolve import Declaration
from lup_dev.git import Git, GitError
from lup_dev.policy.landing import asked_files
from lup_dev.policy.roles import Roles

if TYPE_CHECKING:
    from conftest import Shell


ROLES = Roles(root=Path("/nowhere"), declaration=Declaration.of(Project()))
"""lup's default roles, which read no file of a worktree for these paths."""


def object_file(repository: Path, name: str) -> Path:
    """Where the store at `repository` keeps the object `name` loose."""
    return repository / "objects" / name[:2] / name[2:]


def planted(repository: Path, name: str, kind: str, content: bytes) -> None:
    """Keep `content` in the store at `repository` under the id `name`, which isn't its own."""
    framed = f"{kind} {len(content)}".encode() + b"\0" + content
    kept = object_file(repository, name)
    kept.parent.mkdir(exist_ok=True)
    if kept.exists():
        kept.chmod(0o644)
    kept.write_bytes(zlib.compress(framed))


def committed(root: Path, shell: Shell, files: dict[str, str]) -> str:
    """Write `files` in the worktree at `root`, commit them, and return the commit."""
    for path, content in files.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    shell.commit(root, "the files")
    return shell.git(root, "rev-parse", "HEAD")


def test_it_reads_each_file_the_diff_changes_that_its_role_asks_about(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, shell, {".gitignore": "a\n", "src/kept.py": "x = 1\n"})
    (root / ".gitignore").unlink()
    tip = committed(
        root,
        shell,
        {".github/workflows/ci.yml": "on: push\n", "AGENTS.md": "A.\n", "b.py": "\n"},
    )
    found = asked_files(Git.pinned(bare), ROLES, old, tip)
    assert {str(each.path): each.judgement.role for each in found} == {
        ".github/workflows/ci.yml": "protected",
        "AGENTS.md": "operator",
        ".gitignore": "protected",
    }
    gone = next(each for each in found if str(each.path) == ".gitignore")
    assert (gone.version, gone.content) == (None, None)
    written = next(each for each in found if str(each.path) == "AGENTS.md")
    assert written.content == b"A.\n"
    assert written.version == shell.git(root, "rev-parse", f"{tip}:AGENTS.md")


def test_it_reads_as_git_s_diff_does_a_directory_a_file_replaces_and_a_mode_changed(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    old = committed(
        root,
        shell,
        {"a/b/one.py": "1\n", "a/two.py": "2\n", "c": "file\n", "d/same.py": "s\n"},
    )
    (root / "a/b/one.py").unlink()
    (root / "a/two.py").unlink()
    (root / "a/b").rmdir()
    (root / "a").rmdir()
    (root / "c").unlink()
    (root / "d/same.py").chmod(0o755)
    tip = committed(root, shell, {"a": "now a file\n", "c/three.py": "3\n"})
    own = {str(path) for path in Git.pinned(bare).own_changes(old, tip)}
    listed = shell.git(root, "diff", "--name-only", "--no-renames", old, tip)
    assert own == set(listed.splitlines())
    assert own == {"a", "a/b/one.py", "a/two.py", "c", "c/three.py", "d/same.py"}


@pytest.mark.parametrize("name", [".claude", ".github", ".vscode", ".githooks"])
def test_a_link_at_a_protected_directory_s_name_asks_what_a_file_under_it_would(
    bare: Path, shell: Shell, name: str
) -> None:
    root = bare / "tree" / "main"
    old = shell.git(root, "rev-parse", "HEAD")
    (root / "elsewhere").mkdir()
    (root / "elsewhere" / "settings.json").write_text("{}\n")
    (root / name).symlink_to("elsewhere")
    shell.commit(root, "a link")
    tip = shell.git(root, "rev-parse", "HEAD")
    [found] = asked_files(Git.pinned(bare), ROLES, old, tip)
    assert str(found.path) == name
    assert found.judgement.role == "protected"
    assert found.content == b"elsewhere"
    assert found.version == shell.git(root, "rev-parse", f"{tip}:{name}")


def test_a_link_elsewhere_into_a_protected_directory_changes_nothing_there_and_asks_nothing(
    bare: Path, shell: Shell
) -> None:
    """What's under the protected directory is what a landing asks about, by its own path."""
    root = bare / "tree" / "main"
    old = committed(root, shell, {".claude/settings.json": "{}\n"})
    (root / "into").symlink_to(".claude")
    tip = committed(root, shell, {})
    assert asked_files(Git.pinned(bare), ROLES, old, tip) == []
    changed = committed(root, shell, {"into/settings.json": "{}\n# more\n"})
    [found] = asked_files(Git.pinned(bare), ROLES, tip, changed)
    assert str(found.path) == ".claude/settings.json"


def test_every_file_of_a_tip_is_read_where_the_remote_has_no_such_branch(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    tip = committed(root, shell, {".github/x.yml": "a\n"})
    found = asked_files(Git.pinned(bare), ROLES, None, tip)
    assert ".github/x.yml" in {str(each.path) for each in found}


@pytest.mark.parametrize("kind", ["commit", "tree", "blob"])
def test_an_object_that_isn_t_what_its_id_says_refuses_the_reading(
    kind: str, bare: Path, shell: Shell
) -> None:
    """A room writes the store, so an object read here is what its id says, or nothing is read."""
    root = bare / "tree" / "main"
    old = committed(root, shell, {"AGENTS.md": "before\n", "a.py": "1\n"})
    tip = committed(root, shell, {"AGENTS.md": "after\n", "a.py": "2\n"})
    named = {
        "commit": old,
        "tree": shell.git(root, "rev-parse", f"{old}^{{tree}}"),
        "blob": shell.git(root, "rev-parse", f"{tip}:AGENTS.md"),
    }[kind]
    content = subprocess.run(
        ["git", "cat-file", kind, f"{tip}^{{tree}}" if kind == "tree" else named],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    planted(bare, named, kind, content + b"\n" if kind != "tree" else content)
    with pytest.raises(GitError, match="isn't that"):
        asked_files(Git.pinned(bare), ROLES, old, tip)


def test_what_a_commit_holds_is_read_from_the_commit_whatever_a_commit_graph_says(
    bare: Path, shell: Shell
) -> None:
    """Only the commit's own bytes say what tree it holds."""
    root = bare / "tree" / "main"
    old = committed(root, shell, {"a.py": "1\n"})
    tip = committed(root, shell, {"AGENTS.md": "after\n"})
    shell.git(root, "commit-graph", "write", "--reachable")
    graph = bare / "objects" / "info" / "commit-graph"
    data = bytearray(graph.read_bytes())
    tree = {
        each: bytes.fromhex(shell.git(root, "rev-parse", f"{each}^{{tree}}"))
        for each in [old, tip]
    }
    at = bytes(data).index(tree[tip])
    data[at : at + len(tree[tip])] = tree[old]
    data[-20:] = hashlib.sha1(bytes(data[:-20]), usedforsecurity=False).digest()
    graph.chmod(0o644)
    graph.write_bytes(bytes(data))
    found = asked_files(Git.pinned(bare), ROLES, old, tip)
    assert [str(each.path) for each in found] == ["AGENTS.md"]
