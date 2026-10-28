"""Files that hold secrets, hidden from a room: which files are found, whose content their repository's store holds, what's passed over, and what a launch says.

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
from lup_dev.git import Git
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


def test_a_file_with_a_secret_s_name_is_shown_where_its_repository_s_objects_hold_its_content(
    repo: Path,
) -> None:
    (repo / ".env.example").write_text("TOKEN=\n")
    (repo / "config").mkdir()
    (repo / "config" / "master.key").write_text("committed")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "templates")
    # Changed since, to content of the same size; ignored; untracked. Staged by
    # force, which writes its content to the store; a committed file's content
    # under another name; a link; another name.
    (repo / "config" / "master.key").write_text("Committed")
    (repo / ".gitignore").write_text(".venv/\n.lup/\n.env.local\n")
    (repo / ".env.local").write_text("TOKEN=the operator's\n")
    (repo / ".env").write_text("TOKEN=forgotten\n")
    (repo / ".env.staged").write_text("TOKEN=staged\n")
    git(repo, "add", "-f", ".env.staged")
    (repo / ".env.copy").write_text("TOKEN=\n")
    (repo / ".env.link").symlink_to(repo / ".env.local")
    (repo / "notes.txt").write_text("nothing secret\n")

    assert hidden(Tree(path=repo, git=git_directory(repo))) == [
        Path(".env"),
        Path(".env.local"),
        Path("config/master.key"),
    ]


def test_a_moved_repository_s_files_are_shown_though_git_lists_its_worktrees_where_they_were(
    bare: Path, tmp_path: Path
) -> None:
    main = bare / "tree" / "main"
    (main / ".env").write_text("PORT=8000\n")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "the interface")
    git(bare, "worktree", "add", "-q", "-b", "feat", "tree/feat")
    (bare / "tree" / "feat" / ".env.local").write_text("TOKEN=a value\n")
    (tmp_path / "moved").mkdir()
    moved = bare.rename(tmp_path / "moved" / "proj.git")
    listed = run("git", "worktree", "list", "--porcelain", cwd=moved).output.decode()
    assert listed.count("prunable") == 2

    assert hidden(Tree(path=moved, git=git_directory(moved))) == [
        Path("tree/feat/.env.local")
    ]


def test_a_pattern_is_matched_from_the_root_of_the_worktree_holding_the_file(
    repo: Path,
) -> None:
    git(repo, "worktree", "add", "-q", "-b", "feat", ".git/tree/feat")
    # Moved by hand, so git lists it where it was: its `.git` marks its root.
    moved = (repo / ".git" / "tree" / "feat").rename(repo / ".git" / "tree" / "moved")
    for root in [repo, moved]:
        (root / "config").mkdir()
        (root / "config" / "a.key").write_text("")
        (root / "src" / "config").mkdir(parents=True)
        (root / "src" / "config" / "b.key").write_text("")

    found = hidden(
        Tree(path=repo, git=git_directory(repo)), Search(patterns=["config/*.key"])
    )

    assert found == [Path(".git/tree/moved/config/a.key"), Path("config/a.key")]


def test_every_file_with_a_secret_s_name_in_a_repository_nested_in_the_tree_is_hidden(
    repo: Path,
) -> None:
    (repo / ".env.example").write_text("TOKEN=\n")
    (repo / ".gitignore").write_text(".venv/\n.lup/\ntmp/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the example")
    scratch = repo / "tmp"
    scratch.mkdir()
    # A copy of the example; a clone; a bare clone with a worktree. Each holds
    # the example as committed, which the tree's store holds.
    (scratch / ".env.example").write_text("TOKEN=\n")
    git(scratch, "clone", "-q", str(repo), "clone")
    git(scratch, "clone", "-q", "--bare", str(repo), "copy.git")
    git(scratch / "copy.git", "worktree", "add", "-q", "tree/main", "main")
    # A `.git` directory that isn't a git directory nests nothing: a worktree
    # of the tree's own under one is checked, as git would read it.
    (repo / "tree" / ".git").mkdir(parents=True)
    git(repo, "worktree", "add", "-q", "-b", "feat", "tree/feat")
    assert (repo / "tree" / "feat" / ".env.example").exists()

    assert hidden(Tree(path=repo, git=git_directory(repo))) == [
        Path("tmp/clone/.env.example"),
        Path("tmp/copy.git/tree/main/.env.example"),
    ]


def test_a_store_that_reads_objects_from_elsewhere_has_every_file_hidden(
    repo: Path, tmp_path: Path
) -> None:
    (repo / ".env.example").write_text("TOKEN=\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the example")
    # A repository the room doesn't mount holds a real value, which the
    # operator keeps in the tree too, untracked.
    private = tmp_path / "private"
    private.mkdir()
    git(private, "init", "-q", "-b", "main")
    (private / ".env").write_text("TOKEN=real\n")
    git(private, "add", ".env")
    (repo / ".env").write_text("TOKEN=real\n")
    real = run("git", "hash-object", ".env", cwd=repo).output.decode().strip()
    objects = repo / ".git" / "objects"
    alternates = objects / "info" / "alternates"
    alternates.write_text(f"{private / '.git' / 'objects'}\n")
    # git asked there would answer from the other store.
    assert Git.pinned(repo / ".git").blobs([real]) == [real]
    tree = Tree(path=repo, git=git_directory(repo))

    assert hidden(tree) == [Path(".env"), Path(".env.example")]
    alternates.unlink()
    (objects / "pack" / "theirs").symlink_to(private / ".git" / "objects" / "pack")
    assert hidden(tree) == [Path(".env"), Path(".env.example")]


def test_a_sha256_repository_s_store_is_asked_by_sha256_ids(tmp_path: Path) -> None:
    root = tmp_path / "sha256"
    root.mkdir()
    git(root, "init", "-q", "-b", "main", "--object-format=sha256")
    (root / ".env.example").write_text("TOKEN=\n")
    git(root, "add", "-A")
    (root / ".env").write_text("TOKEN=forgotten\n")

    assert hidden(Tree(path=root, git=git_directory(root))) == [Path(".env")]


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
            "secret's name whose content their repository's git objects don't hold "
            f"(`docs/launch.md`, *Files with a secret's name*):\n  {repo / '.env.local'}\n"
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
