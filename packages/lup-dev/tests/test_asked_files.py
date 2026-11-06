"""What a landing reads of its own diff: each file's role, by the objects' own bytes."""

import subprocess
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev import Core, Levels, Modules, Paths, Project
from lup_dev.declaration.resolve import Declaration
from lup_dev.git import Git, GitError
from lup_dev.policy.landing import asked_files, changed_files
from lup_dev.policy.roles import Roles

if TYPE_CHECKING:
    from conftest import FakeParser, Shell

    from lup_dev.policy.landing import AskedFile


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
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, shell, {".gitignore": "a\n", "src/kept.py": "x = 1\n"})
    (root / ".gitignore").unlink()
    tip = committed(
        root,
        shell,
        {".github/workflows/ci.yml": "on: push\n", "AGENTS.md": "A.\n", "b.py": "\n"},
    )
    found = asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser)
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
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    tip = committed(root, shell, {".github/x.yml": "a\n"})
    found = asked_files(Git.pinned(bare), ROLES, None, tip, parser=parser)
    assert ".github/x.yml" in {str(each.path) for each in found}


IGNORE = 'x = 1  # lup: ignore("regex", why="a grammar")\n'
"""A line holding an `ignore`, which the tests' parser reads as the engine does."""


def added(found: list[AskedFile]) -> dict[str, list[str]]:
    """Say what each file found asks about, by its name."""
    return {str(each.path): [ask.kind for ask in each.judgement.asks] for each in found}


def test_an_ignore_a_landing_adds_asks_whatever_its_hooks_heard(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, shell, {"src/kept.py": "y = 2\n"})
    tip = committed(
        root,
        shell,
        {
            "src/kept.py": f"y = 2\n{IGNORE}",
            "src/new.py": IGNORE,
            "src/clean.py": "z = 3\n",
        },
    )
    found = asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser)
    assert added(found) == {"src/kept.py": ["ignore"], "src/new.py": ["ignore"]}
    kept = next(each for each in found if str(each.path) == "src/kept.py")
    [ask] = kept.judgement.asks
    assert ask.line == 2
    assert ask.reason == (
        'adds `# lup: ignore("regex", why="a grammar")` to src/kept.py'
    )
    assert kept.judgement.outcome == "ask"
    assert kept.version == shell.git(root, "rev-parse", f"{tip}:src/kept.py")


def test_an_ignore_a_landing_keeps_moves_or_removes_asks_nothing(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = committed(
        root,
        shell,
        {"src/kept.py": IGNORE, "src/moved.py": IGNORE, "src/gone.py": IGNORE},
    )
    tip = committed(
        root,
        shell,
        {
            "src/kept.py": f"{IGNORE}y = 2\n",
            "src/moved.py": f"y = 2\n{IGNORE}",
            "src/gone.py": "x = 1\n",
        },
    )
    assert asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser) == []


def test_an_ignore_asks_only_in_a_module_lup_s_rules_read(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = shell.git(root, "rev-parse", "HEAD")
    tip = committed(
        root,
        shell,
        {
            "tests/test_a.py": IGNORE,
            "docs/a.md": f"# lup: {IGNORE}",
            "tmp/a.py": IGNORE,
            "notes.txt": IGNORE,
        },
    )
    assert asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser) == []


def test_an_ignore_is_read_in_a_file_that_isn_t_wholly_text(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = shell.git(root, "rev-parse", "HEAD")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "a.py").write_bytes(b"# caf\xe9\n" + IGNORE.encode())
    tip = committed(root, shell, {})
    assert added(asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser)) == {
        "src/a.py": ["ignore"]
    }


def test_an_ignore_asks_on_top_of_a_protected_module_s_role(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    roles = Roles(
        root=Path("/nowhere"),
        declaration=Declaration.of(
            Project(
                modules=Modules.default().edit(
                    Core(paths=Paths().add(protected=["src/**"]))
                )
            )
        ),
    )
    root = bare / "tree" / "main"
    old = shell.git(root, "rev-parse", "HEAD")
    tip = committed(root, shell, {"src/a.py": IGNORE})
    assert added(asked_files(Git.pinned(bare), roles, old, tip, parser=parser)) == {
        "src/a.py": ["protected", "ignore"]
    }


def test_the_declaration_says_how_an_added_ignore_is_taken_whatever_the_role_s_level(
    bare: Path, shell: Shell, parser: FakeParser
) -> None:
    root = bare / "tree" / "main"
    old = shell.git(root, "rev-parse", "HEAD")
    tip = committed(root, shell, {"src/a.py": IGNORE})
    git = Git.pinned(bare)

    def roles(project: Project) -> Roles:
        return Roles(root=Path("/nowhere"), declaration=Declaration.of(project))

    automatic = Project(
        modules=Modules.default().edit(Core(levels=Levels(production="automatic")))
    )
    assert added(asked_files(git, roles(automatic), old, tip, parser=parser)) == {
        "src/a.py": ["ignore"]
    }
    flagging = Project(held=[], flagged=["ignore"])
    [flagged] = asked_files(git, roles(flagging), old, tip, parser=parser)
    assert (flagged.judgement.outcome, flagged.judgement.asks) == ("allow", [])
    assert [each.kind for each in flagged.judgement.flags] == ["ignore"]
    assert asked_files(git, roles(Project(held=[])), old, tip, parser=parser) == []


@pytest.mark.parametrize("kind", ["commit", "tree", "blob"])
def test_an_object_that_isn_t_what_its_id_says_refuses_the_reading(
    kind: str, bare: Path, shell: Shell, parser: FakeParser
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
        asked_files(Git.pinned(bare), ROLES, old, tip, parser=parser)


def test_what_a_commit_holds_is_read_from_the_commit_whatever_a_commit_graph_says(
    bare: Path, shell: Shell
) -> None:
    """Only the commit's own bytes say what tree it holds."""
    root = bare / "tree" / "main"
    old = committed(root, shell, {"a.py": "1\n"})
    tip = committed(root, shell, {"AGENTS.md": "after\n"})
    shell.forged_tree(bare, tip, old)
    found = asked_files(Git.pinned(bare), ROLES, old, tip)
    assert [str(each.path) for each in found] == ["AGENTS.md"]


def test_a_landing_s_changed_files_are_read_from_the_commits_whatever_a_commit_graph_says(
    bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, shell, {"a.py": "1\n"})
    tip = committed(root, shell, {"src/b.py": "2\n", "a.py": "3\n"})
    shell.forged_tree(bare, tip, old)
    assert changed_files(Git.pinned(bare), old, tip) == [
        Path("a.py"),
        Path("src/b.py"),
    ]
    whole = changed_files(Git.pinned(bare), None, tip)
    assert [Path("a.py"), Path("src/b.py")] == [
        each for each in whole if each in [Path("a.py"), Path("src/b.py")]
    ]


@pytest.mark.parametrize("kind", ["commit", "tree"])
def test_a_landing_s_changed_files_aren_t_read_past_an_object_that_isn_t_what_its_id_says(
    kind: str, bare: Path, shell: Shell
) -> None:
    root = bare / "tree" / "main"
    old = committed(root, shell, {"a.py": "1\n"})
    tip = committed(root, shell, {"a.py": "2\n"})
    if kind == "commit":
        content = subprocess.run(
            ["git", "cat-file", "commit", tip],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        old_tree = shell.git(root, "rev-parse", f"{old}^{{tree}}").encode()
        new_tree = shell.git(root, "rev-parse", f"{tip}^{{tree}}").encode()
        planted(bare, tip, "commit", content.replace(new_tree, old_tree))
    else:
        content = subprocess.run(
            ["git", "cat-file", "tree", f"{old}^{{tree}}"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        planted(bare, shell.git(root, "rev-parse", f"{tip}^{{tree}}"), "tree", content)
    with pytest.raises(GitError, match="isn't that"):
        changed_files(Git.pinned(bare), old, tip)
