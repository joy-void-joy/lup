"""Files that hold secrets, hidden from a room: which files are found, which a commit holds as they are, what's passed over, and what a launch says.

git runs for real on the test's repositories, with the operator's own git
configuration kept out; no test runs podman, so the mounts are compared as data.
"""

import resource
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup.programs import run
from lup.rooms.container import Mount
from lup_dev.catalog.paths import CorePaths
from lup_dev.launch.hidden import Found
from lup_dev.launch.secrets import (
    RoomSecrets,
    Search,
    Tree,
    git_directory,
    hiding,
)
from lup_dev.layout import Layout

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULTS = Search(patterns=CorePaths().secret)


def git(root: Path, *arguments: str) -> None:
    run("git", *arguments, cwd=root)


@pytest.fixture(autouse=True)
def own_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's git configuration out: an empty global file, no system one."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def hidden(tree: Tree, search: Search = DEFAULTS) -> list[Path]:
    """What a launch hides in `tree`, files and directories, each from the tree's root, sorted."""
    found = hiding(search, tree)
    return sorted(
        each.relative_to(tree.path) for each in [*found.files, *found.unlisted]
    )


def test_a_file_with_a_secret_s_name_is_hidden_unless_its_commit_holds_it_as_it_is(
    repo: Path,
) -> None:
    (repo / ".env.example").write_text("TOKEN=\n")
    (repo / "config").mkdir()
    (repo / "config" / "master.key").write_text("committed")
    (repo / "same.pem").write_text("aaaa")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "templates")
    # Changed since, to content of the same size; ignored; untracked; staged by
    # force, as a room would to have git call it tracked; a link; another name.
    (repo / "config" / "master.key").write_text("Committed")
    (repo / ".gitignore").write_text(".venv/\n.lup/\n.env.local\n")
    (repo / ".env.local").write_text("TOKEN=the operator's\n")
    (repo / ".env").write_text("TOKEN=forgotten\n")
    (repo / ".env.staged").write_text("TOKEN=staged\n")
    git(repo, "add", "-f", ".env.staged")
    (repo / ".env.link").symlink_to(repo / ".env.local")
    (repo / "notes.txt").write_text("nothing secret\n")

    assert hidden(Tree(path=repo, git=git_directory(repo))) == [
        Path(".env"),
        Path(".env.local"),
        Path(".env.staged"),
        Path("config/master.key"),
    ]


def test_each_of_the_repository_s_worktrees_is_looked_in_and_what_s_outside_them_too(
    bare: Path,
) -> None:
    main = bare / "tree" / "main"
    (main / ".env.example").write_text("TOKEN=\n")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "the example")
    git(bare, "worktree", "add", "-q", "-b", "feat", "tree/feat")
    feat = bare / "tree" / "feat"
    # A worktree whose example changed; one git no longer lists, its `.git`
    # file gone; and a file beside the git directory's own.
    (feat / ".env.example").write_text("TOKEN=a value\n")
    stray = bare / "tree" / "unlisted"
    stray.mkdir()
    (stray / ".env").write_text("TOKEN=\n")
    (bare / "id_ed25519").write_text("")

    assert hidden(Tree(path=bare, git=git_directory(bare))) == [
        Path("id_ed25519"),
        Path("tree/feat/.env.example"),
        Path("tree/unlisted/.env"),
    ]


def test_a_pattern_is_matched_from_the_root_of_the_worktree_holding_the_file(
    repo: Path,
) -> None:
    git(repo, "worktree", "add", "-q", "-b", "feat", ".git/tree/feat")
    feat = repo / ".git" / "tree" / "feat"
    for root in [repo, feat]:
        (root / "config").mkdir()
        (root / "config" / "a.key").write_text("")
        (root / "src" / "config").mkdir(parents=True)
        (root / "src" / "config" / "b.key").write_text("")

    found = hidden(
        Tree(path=repo, git=git_directory(repo)), Search(patterns=["config/*.key"])
    )

    assert found == [Path(".git/tree/feat/config/a.key"), Path("config/a.key")]


def test_a_repository_without_a_commit_holds_none_of_its_files(tmp_path: Path) -> None:
    root = tmp_path / "new"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / ".env.example").write_text("TOKEN=\n")
    git(root, "add", "-A")

    assert hidden(Tree(path=root, git=git_directory(root))) == [Path(".env.example")]


def test_what_package_managers_install_and_what_s_hidden_already_aren_t_looked_in(
    repo: Path,
) -> None:
    packages = repo / ".venv" / "lib" / "python3.14" / "site-packages" / "certifi"
    packages.mkdir(parents=True)
    (packages / "cacert.pem").write_text("")
    elsewhere = repo / "tools" / "env" / "lib" / "site-packages" / "tornado"
    elsewhere.mkdir(parents=True)
    (elsewhere / "test.key").write_text("")
    (repo / "web" / "node_modules" / "npm").mkdir(parents=True)
    (repo / "web" / "node_modules" / "npm" / ".env").write_text("")
    (repo / ".venv" / ".env").write_text("")
    # A planted `pyvenv.cfg` doesn't have a directory passed over.
    (repo / "deploy").mkdir()
    (repo / "deploy" / "pyvenv.cfg").write_text("")
    (repo / "deploy" / "server.key").write_text("")
    search = DEFAULTS.model_copy(update={"hidden": [repo / ".venv"]})

    assert hidden(Tree(path=repo, git=git_directory(repo)), search) == [
        Path("deploy/server.key")
    ]


def test_a_directory_lup_can_t_list_is_hidden_whole(repo: Path, tmp_path: Path) -> None:
    closed = repo / "closed"
    closed.mkdir()
    (closed / ".env").write_text("")
    launch = Layout(state=tmp_path / "state").launch("0f3a")
    closed.chmod(0)
    try:
        made = RoomSecrets.of(
            DEFAULTS, Tree(path=repo, git=git_directory(repo)), [], launch
        )
    finally:
        closed.chmod(0o755)

    assert made.mounts == [
        Mount(source=launch.empty_directory, target=closed, read_only=True)
    ]
    assert made.said() == [
        (
            "Hidden from the room whole, since lup couldn't look in it for files "
            f"with a secret's name: {closed}"
        )
    ]


@pytest.fixture
def few_descriptors() -> Iterator[None]:
    """Hold this process to 64 open files, as a walk opening every directory it meets at once would exceed."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


@pytest.mark.usefixtures("few_descriptors")
def test_a_directory_holding_more_directories_than_open_files_is_walked_whole(
    tmp_path: Path,
) -> None:
    wide = tmp_path / "wide"
    for at in range(200):
        (wide / f"d{at}").mkdir(parents=True)
    (wide / "d199" / ".env").write_text("")

    assert hidden(Tree(path=wide, git=None)) == [Path("d199/.env")]


def test_a_launch_mounts_its_empty_file_over_each_says_them_and_says_what_appeared(
    repo: Path, tmp_path: Path
) -> None:
    (repo / ".env.example").write_text("TOKEN=\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the example")
    (repo / ".env.local").write_text("TOKEN=the operator's\n")
    notes = tmp_path / "notes"
    (notes / "profile").mkdir(parents=True)
    (notes / "profile" / ".credentials.json").write_text("{}")
    launch = Layout(state=tmp_path / "state").launch("0f3a")

    made = RoomSecrets.of(
        DEFAULTS,
        Tree(path=repo, git=git_directory(repo)),
        [Tree(path=notes, git=git_directory(notes))],
        launch,
    )
    made.write()

    assert made.mounts == [
        Mount(source=launch.empty_file, target=repo / ".env.local", read_only=True),
        Mount(
            source=launch.empty_file,
            target=notes / "profile" / ".credentials.json",
            read_only=True,
        ),
    ]
    assert launch.empty_file.read_text() == ""
    assert made.said() == [
        (
            "Hidden from the room, each reading as an empty file: the files with a "
            "secret's name no commit holds as they are (`docs/launch.md`, *Files "
            f"with a secret's name*):\n  {repo / '.env.local'}\n"
            f"  {notes / 'profile' / '.credentials.json'}"
        )
    ]
    # The room makes its own `.env`, and changes the example.
    (repo / "web").mkdir()
    (repo / "web" / ".env").write_text("TOKEN=the room's\n")
    (repo / ".env.example").write_text("TOKEN=\nOTHER=\n")

    assert made.end() == [
        (
            "These files with a secret's name appeared or changed while the room "
            "ran, so the room may have written them, and your tools read such a "
            f"file: look at each before they do.\n  {repo / '.env.example'}\n"
            f"  {repo / 'web' / '.env'}"
        )
    ]
    assert (repo / "web" / ".env").read_text() == "TOKEN=the room's\n"
    assert (repo / ".env.local").read_text() == "TOKEN=the operator's\n"


def test_a_launch_finding_nothing_says_nothing(repo: Path, tmp_path: Path) -> None:
    made = RoomSecrets.of(
        DEFAULTS,
        Tree(path=repo, git=git_directory(repo)),
        [],
        Layout(state=tmp_path / "state").launch("0f3a"),
    )
    assert made.found == []
    assert made.said() == []
    assert made.end() == []


def test_the_git_directory_is_a_clone_s_or_a_bare_repository_s_own_and_nothing_else(
    repo: Path, bare: Path, linked: Path, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_directory(repo) == repo / ".git"
    assert git_directory(bare) == bare
    assert git_directory(linked) is None
    assert git_directory(plain) is None


def test_what_s_found_is_recorded_as_a_file_or_a_directory(repo: Path) -> None:
    (repo / ".env").write_text("")
    assert Found.at(repo, repo / ".env") == Found(
        path=repo / ".env",
        directory=False,
        device=(repo / ".env").stat().st_dev,
        inode=(repo / ".env").stat().st_ino,
    )
