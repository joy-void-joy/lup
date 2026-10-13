"""git as lup_dev runs it: a commit's files written from git's objects, not its archive."""

from typing import TYPE_CHECKING

import pytest

from lup_dev.git import Git, GitError
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


def test_a_missing_object_is_refused(repo: Path) -> None:
    with pytest.raises(GitError, match="not its size"):
        Git(cwd=repo).contents(["0" * 40])


def test_a_revision_naming_no_commit_is_none(repo: Path, shell: Shell) -> None:
    git = Git(cwd=repo)
    assert git.commit("HEAD") == shell.git(repo, "rev-parse", "HEAD")
    assert git.commit("refs/heads/nowhere") is None
