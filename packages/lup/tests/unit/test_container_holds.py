"""What a contained session is held from rewriting, proved against real mounts.

A lease is a table, and a table can be right on paper and wrong once mounted:
nesting order, a parent renamed from under a hold, a file bind whose source
was missing. So each test here applies the lease the launcher computes the way
an engine does — parent before child, same path inside as out — in a user and
mount namespace of this test's own, and then does to it what a session would.
Where the host cannot make such a namespace the mounted tests are skipped and
the lease-level ones still run.

What a namespace cannot show is the container's own filesystem: everything
the lease does not mount is still visible here, so these tests only ever ask
about paths the lease covers.
"""

import shlex
import shutil
from pathlib import Path, PurePosixPath

import pytest
import sh
import typer

from lup.devtools.harness.contained import container_lease, launch_record
from lup.execution.shell import git
from lup.harness.image import HeldPaths, Image
from lup.harness.ownership import OWNERSHIP_FILENAME, OwnedArtifact, OwnershipManifest
from lup.sandbox.rail import Lease, NestedRepository, demoted, lease_for, rooted


def namespaces_work() -> bool:
    """Whether this host lets an unprivileged process make a user and mount namespace."""
    if shutil.which("unshare") is None:
        return False
    try:
        sh.Command("unshare")("-rm", "true")
    except sh.ErrorReturnCode:
        return False
    return True


mounted = pytest.mark.skipif(
    not namespaces_work(), reason="no unprivileged user and mount namespace here"
)


def inside(lease: Lease, command: str) -> bool:
    """Whether ``command`` succeeds with this lease mounted as an engine mounts it."""
    sources = {
        **{target: host for host, target in lease.mounted_writable().items()},
        **{target: host for host, target in lease.read_only.items()},
    }
    frozen = set(lease.read_only.values())
    steps = [
        step
        for target in sorted(sources, key=lambda target: PurePosixPath(target).parts)
        for step in [
            f"mount --bind {shlex.quote(str(sources[target]))} {shlex.quote(target)}",
            *(
                [f"mount -o remount,bind,ro {shlex.quote(target)}"]
                if target in frozen
                else []
            ),
        ]
    ]
    script = " && ".join(steps) + f" || exit 97\n{command}\n"
    try:
        sh.Command("unshare")("-rm", "sh", "-c", script)
    except sh.ErrorReturnCode as refused:
        assert refused.exit_code != 97, f"the lease did not mount: {refused.stderr!r}"
        return False
    return True


def committed(root: Path) -> Path:
    """A plain repository with one commit, ignoring what a launch keeps beside it."""
    root.mkdir(parents=True)
    git("-C", str(root), "init", "-q", "-b", "main")
    (root / ".gitignore").write_text(".lup/\nworks/\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    git("-C", str(root), "add", "-A")
    git("-C", str(root), "commit", "-qm", "first")
    return root


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    return committed(tmp_path / "project")


def session_lease(root: Path, image: Image = Image()) -> Lease:
    """The lease a launched session's container runs under, holds and all."""
    return container_lease(root, image, lease_for(root)).lease


@mounted
def test_a_session_cannot_write_its_launch_record(checkout: Path) -> None:
    """The ledger, the accepted policies and the mount table: read inside, never written."""
    lease = session_lease(checkout)
    record = checkout / ".lup"

    assert not inside(lease, f"echo '{{}}' > {record}/preflight/forged.json")
    assert not inside(lease, f"mkdir {record}/policy-snapshots/forged")
    assert not inside(lease, f"echo '{{}}' > {record}/boundary.json")
    assert not inside(lease, f"mv {record} {checkout}/.lup-moved")
    assert not inside(lease, f"mv {record}/preflight {record}/elsewhere")


@mounted
def test_what_a_session_writes_under_its_record_stays_writable(checkout: Path) -> None:
    """The relay a gated session asks through, and what its hooks keep, are its to write."""
    lease = session_lease(checkout)
    record = checkout / ".lup"

    assert inside(lease, f"echo '{{}}' >> {record}/questions.jsonl")
    assert inside(
        lease, f"mkdir -p {record}/hooks && echo x >> {record}/hooks/approvals.jsonl"
    )
    assert inside(
        lease, f"mkdir -p {record}/hooks && echo x >> {record}/hooks/learned.jsonl"
    )
    assert inside(
        lease, f"mkdir -p {record}/review-claims && echo x > {record}/review-claims/one"
    )
    assert inside(lease, f"echo '{{}}' > {record}/script-runs.json")
    assert inside(lease, f"echo 'print(1)' > {checkout}/src/app.py")


def test_the_launch_record_exists_before_anything_mounts_it(checkout: Path) -> None:
    """A bind whose source is missing refuses the whole container."""
    held = launch_record(checkout)

    assert [path.relative_to(checkout).as_posix() for path in held] == [
        ".lup/preflight",
        ".lup/policy-snapshots",
        ".lup/boundary.json",
    ]
    assert all(path.exists() for path in held)


@mounted
def test_the_checkout_git_configuration_stays_where_git_reads_it(
    checkout: Path,
) -> None:
    """Not only the files: the directory holding them, and where git is sent for them."""
    lease = session_lease(checkout)
    repository = f"git -C {checkout}"

    assert not inside(lease, f"{repository} config alias.planted '!touch planted'")
    assert not inside(lease, f"echo '#!/bin/sh' > {checkout}/.git/hooks/pre-commit")
    assert not inside(lease, f"mv {checkout}/.git {checkout}/.git-moved")
    assert not inside(lease, f"echo ../elsewhere > {checkout}/.git/commondir")
    assert inside(
        lease,
        f"echo more >> {checkout}/src/app.py && {repository} add src/app.py && "
        f"{repository} commit -qm second && {repository} status --short",
    )
    assert (checkout / ".git" / "commondir").read_text(encoding="utf-8") == ".\n"
    assert git.lines("-C", str(checkout), "log", "--format=%s") == ["second", "first"]


def test_a_repository_already_redirected_is_refused_before_launch(
    checkout: Path,
) -> None:
    """Holding a planted ``commondir`` read-only would keep the redirection in place."""
    git("init", "-q", "--bare", str(checkout / "elsewhere"))
    (checkout / ".git" / "commondir").write_text("../elsewhere\n", encoding="utf-8")

    with pytest.raises(typer.BadParameter, match="commondir"):
        container_lease(checkout, Image(), lease_for(checkout))


@pytest.fixture
def linked(tmp_path: Path) -> Path:
    """A bare repository with the session's worktree and a sibling beside it."""
    source = committed(tmp_path / "source")
    bare = tmp_path / "repo.git"
    git("clone", "-q", "--bare", str(source), str(bare))
    git("-C", str(bare), "worktree", "add", "-q", str(tmp_path / "mine"), "-b", "mine")
    git(
        "-C", str(bare), "worktree", "add", "-q", str(tmp_path / "other"), "-b", "other"
    )
    return tmp_path


@mounted
def test_a_linked_worktree_cannot_be_pointed_elsewhere(linked: Path) -> None:
    """The pointer, the administrative files, and the directories holding them."""
    mine = linked / "mine"
    admin = linked / "repo.git" / "worktrees" / "mine"
    lease = session_lease(mine)

    assert not inside(lease, f"echo 'gitdir: {linked}/planted' > {mine}/.git")
    assert not inside(lease, f"echo ../../planted > {admin}/commondir")
    assert not inside(lease, f"mv {admin} {admin}-moved")
    assert not inside(lease, f"mv {linked}/repo.git/worktrees {linked}/repo.git/moved")
    assert not inside(lease, f"echo ../elsewhere > {linked}/repo.git/commondir")
    assert inside(
        lease,
        f"echo more >> {mine}/src/app.py && git -C {mine} commit -qam second",
    )


@mounted
def test_a_declared_nested_repository_is_held_like_the_checkout(
    checkout: Path,
) -> None:
    """Committed to by path as ever; its configuration and its place, never rewritten."""
    works = committed(checkout / "works")
    image = Image(
        held=HeldPaths(repositories=[NestedRepository(path=PurePosixPath("works"))])
    )
    lease = session_lease(checkout, image)

    assert inside(
        lease,
        f"echo piece > {works}/piece.txt && git -C {works} add piece.txt && "
        f"git -C {works} commit -qm piece -- piece.txt",
    )
    assert not inside(lease, f"git -C {works} config core.fsmonitor 'touch planted'")
    assert not inside(lease, f"echo '#!/bin/sh' > {works}/.git/hooks/post-commit")
    assert not inside(lease, f"mv {works}/.git {works}/.git-moved")
    assert not inside(lease, f"mv {works} {checkout}/works-moved")
    assert not inside(lease, f"echo ../elsewhere > {works}/.git/commondir")


def test_a_declared_repository_is_created_on_the_host_when_asked(
    checkout: Path,
) -> None:
    """So the first session to use it finds a configuration the host wrote."""
    image = Image(
        held=HeldPaths(
            repositories=[NestedRepository(path=PurePosixPath("works"), create=True)]
        )
    )

    held = container_lease(checkout, image, lease_for(checkout))

    assert (checkout / "works" / ".git" / "config").is_file()
    assert (
        checkout / "works" / ".git" / "config"
    ).as_posix() in held.lease.read_only.values()
    assert [notice.text for notice in held.notices] == [
        "Nested repository works: initialized on the host"
    ]


def test_an_absent_declared_repository_holds_nothing_and_says_so(
    checkout: Path,
) -> None:
    image = Image(
        held=HeldPaths(repositories=[NestedRepository(path=PurePosixPath("works"))])
    )

    held = container_lease(checkout, image, lease_for(checkout))

    assert not (checkout / "works").exists()
    assert "Nested repository works: not there" in held.notices[0].text


def generated_tree(root: Path) -> None:
    """Generated files and the proof listing them, beside one file the proof does not list."""
    listed = [
        ".claude/plugins/sample/skills/one/SKILL.md",
        ".claude/plugins/sample/hooks/hooks.json",
        ".claude/CLAUDE.md",
        ".claude/settings.json",
        "docs/guide.md",
    ]
    for path in listed:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"generated {path}\n", encoding="utf-8")
    (root / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
    (root / ".claude" / OWNERSHIP_FILENAME).write_text(
        OwnershipManifest(
            schema_version=1,
            generator_version="0",
            source_digest="0",
            target_requirements=[],
            files=[
                OwnedArtifact(
                    path=Path(path), category="generated", sha256="0", semantic_id=path
                )
                for path in listed
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )


@mounted
def test_generated_trees_are_held_where_the_image_asks(checkout: Path) -> None:
    """Each plugin whole, every other generated file alone, local files beside them free."""
    generated_tree(checkout)
    lease = session_lease(checkout, Image(held=HeldPaths(generated=True)))
    plugin = checkout / ".claude" / "plugins" / "sample"

    assert not inside(lease, f"echo x > {plugin}/skills/one/SKILL.md")
    assert not inside(lease, f"mkdir -p {plugin}/skills/planted")
    assert not inside(lease, f"echo x > {checkout}/.claude/CLAUDE.md")
    assert not inside(lease, f"echo x > {checkout}/docs/guide.md")
    assert not inside(lease, f"echo x > {checkout}/.claude/{OWNERSHIP_FILENAME}")
    assert not inside(lease, f"mv {checkout}/.claude {checkout}/.claude-moved")
    assert inside(lease, f"echo '{{}}' > {checkout}/.claude/settings.local.json")
    assert inside(lease, f"echo notes > {checkout}/docs/draft.md")


@mounted
def test_generated_trees_stay_writable_by_default(checkout: Path) -> None:
    """Regenerating from inside is an ordinary session's work until a project moves it."""
    generated_tree(checkout)
    lease = session_lease(checkout)

    assert inside(lease, f"echo x > {checkout}/.claude/CLAUDE.md")
    assert inside(lease, f"echo x > {checkout}/.claude/plugins/sample/hooks/hooks.json")


def test_a_launch_mount_wins_over_a_hold_at_the_same_path(
    checkout: Path, tmp_path: Path
) -> None:
    """A mode's guidance mounted over the committed document is the one mount there."""
    generated_tree(checkout)
    overlay = tmp_path / "variant" / "CLAUDE.md"
    overlay.parent.mkdir()
    overlay.write_text("the mode's guidance\n", encoding="utf-8")
    target = (checkout / ".claude" / "CLAUDE.md").as_posix()

    lease = container_lease(
        checkout,
        Image(held=HeldPaths(generated=True)),
        lease_for(checkout),
        {overlay: target},
    ).lease

    assert [host for host, inside in lease.read_only.items() if inside == target] == [
        overlay
    ]


def test_a_hold_never_makes_a_read_only_lease_writable(checkout: Path) -> None:
    """A reviewer's lease writes nothing, and holding paths inside it changes that not at all."""
    reviewing = demoted(lease_for(checkout))

    lease = container_lease(checkout, Image(), reviewing).lease

    assert lease.mounted_writable() == {}


def test_rooting_pins_every_directory_between_a_hold_and_its_mount(
    tmp_path: Path,
) -> None:
    held = tmp_path / "a" / "b" / "c"

    lease = rooted(
        Lease(
            writable={tmp_path: tmp_path.as_posix()}, read_only={held: held.as_posix()}
        )
    )

    assert sorted(lease.pinned) == [tmp_path / "a", tmp_path / "a" / "b"]
    assert lease.read_only == {held: held.as_posix()}
