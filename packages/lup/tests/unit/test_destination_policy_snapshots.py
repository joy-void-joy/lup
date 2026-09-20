"""Launch grants bind exact Git owners and immutable generated policy bytes."""

import json
from pathlib import Path

import pytest

from lup.devtools.harness import launch
from lup.devtools.harness.policy_refresh import refresh_destination_policy
from lup.devtools.harness.preflight import (
    LaunchSentinels,
    ROOT_VARIABLE,
    NONCE_VARIABLE,
    record_preflight,
)
from lup.execution.shell import git
from lup.harness.models import HookSet, Plugin
from lup.harness.notice import Banner
from lup.policy.assets.host import policy_snapshot_digest
from lup.policy.profiles import compile_boundary, measured
from lup.policy.snapshots import accept_destination_policies, destination_authorities
from lup.sandbox.rail import AccessibleRoot, Lease, fleet_lease, repository_layout


def repository(path: Path, separate: Path | None = None) -> Path:
    """Create a checkout whose ownership Git can establish."""
    path.mkdir(parents=True)
    options = ["--separate-git-dir", str(separate)] if separate is not None else []
    git("init", "-q", "-b", "main", *options, str(path))
    return path


def evaluator(checkout: Path, runtime: str = "codex") -> Path:
    """An inert generated policy tree with one executable entry point."""
    hooks = checkout / f".{runtime}" / "plugins" / "example" / "hooks"
    (hooks / "scripts").mkdir(parents=True)
    (hooks / "runtime" / "kernel").mkdir(parents=True)
    (hooks / "scripts" / "policy_evaluator.py").write_text("print('inert')\n")
    (hooks / "runtime" / "policy_data.py").write_text("EDIT_LIMIT = 3\n")
    (hooks / "runtime" / "kernel" / "decision.py").write_text("VALUE = 1\n")
    return hooks


@pytest.mark.parametrize(
    "sandbox", [launch.LaunchSandbox.NONE, launch.LaunchSandbox.OUTER]
)
def test_every_launch_replaces_inherited_ledger_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: launch.LaunchSandbox
) -> None:
    checkout = repository(tmp_path / "checkout")
    monkeypatch.setattr(launch, "project_root", lambda: checkout)
    environment = {ROOT_VARIABLE: "/inherited", NONCE_VARIABLE: "inherited"}
    sentinels = LaunchSentinels()
    plugin = Plugin(
        id="test.policy",
        name="test",
        marketplace="test",
        version="1.0.0",
        description="Boundary authority test",
        skills=[],
        agents=[],
    )

    launch.settle_boundary(plugin, sandbox, [], sentinels, environment, Banner())

    assert environment[ROOT_VARIABLE] == str(checkout)
    assert environment[NONCE_VARIABLE] == sentinels.nonce
    assert (checkout / ".lup/preflight" / f"{sentinels.nonce}.json").is_file()


def test_mounting_a_parent_does_not_grant_unrelated_nested_repositories(
    tmp_path: Path,
) -> None:
    caller = repository(tmp_path / "caller")
    parent = tmp_path / "projects"
    destination = repository(parent / "destination")
    evaluator(destination)
    accessible = [AccessibleRoot(path=parent)]

    assert (
        accept_destination_policies(
            caller, accessible, fleet_lease(caller, accessible), "codex"
        )
        == []
    )


def test_grants_record_the_owner_and_explicit_scope_separately(tmp_path: Path) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    evaluator(destination)
    scope = destination / "src"
    scope.mkdir()
    accessible = [AccessibleRoot(path=scope)]

    row = accept_destination_policies(caller, accessible, Lease(), "codex")[0]

    assert row.checkout == str(destination)
    assert row.repository == str(repository_layout(destination).common)
    assert row.writable_roots == [str(scope)]
    assert row.digest == policy_snapshot_digest(Path(row.source))
    assert row.digest == policy_snapshot_digest(Path(row.snapshot))


def test_read_only_grants_and_nested_read_only_mounts_are_not_erased(
    tmp_path: Path,
) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    evaluator(destination)
    withheld = destination / "authored"
    withheld.mkdir()
    accessible = [
        AccessibleRoot(path=destination),
        AccessibleRoot(path=withheld, writable=False),
    ]
    lease = fleet_lease(caller, accessible)

    row = accept_destination_policies(caller, accessible, lease, "codex")[0]

    assert row.writable_roots == [str(destination)]
    assert str(withheld) in row.read_only_roots
    only_read = [AccessibleRoot(path=destination, writable=False)]
    read_row = accept_destination_policies(
        caller, only_read, fleet_lease(caller, only_read), "codex"
    )[0]
    assert read_row.writable_roots == []
    assert str(destination) in read_row.read_only_roots


def test_symlink_mounts_are_bound_to_their_canonical_repository(tmp_path: Path) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    evaluator(destination)
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)
    accessible = [AccessibleRoot(path=alias)]

    row = accept_destination_policies(caller, accessible, Lease(), "codex")[0]

    assert row.checkout == str(destination)
    assert row.writable_roots == [str(destination)]
    elsewhere = repository(tmp_path / "elsewhere")
    alias.unlink()
    alias.symlink_to(elsewhere, target_is_directory=True)
    assert str(alias.resolve()) not in row.writable_roots


def test_linked_siblings_share_identity_but_not_an_implicit_destination_grant(
    tmp_path: Path,
) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    git(
        "-C",
        str(destination),
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    sibling = tmp_path / "sibling"
    git("-C", str(destination), "worktree", "add", "-q", "-b", "sibling", str(sibling))
    layout = repository_layout(sibling)
    relative = layout.private.relative_to(sibling, walk_up=True)
    (sibling / ".git").write_text(f"gitdir: {relative}\n")
    evaluator(sibling)
    accessible = [AccessibleRoot(path=sibling)]

    rows = accept_destination_policies(
        caller, accessible, fleet_lease(caller, accessible), "codex"
    )

    assert len(rows) == 1
    assert rows[0].checkout == str(sibling)
    assert rows[0].repository == str(repository_layout(destination).common)
    assert rows[0].writable_roots == [str(sibling)]


def test_separate_git_directory_is_the_destination_repository_identity(
    tmp_path: Path,
) -> None:
    caller = repository(tmp_path / "caller")
    administrative = tmp_path / "admin"
    destination = repository(tmp_path / "destination", administrative)
    evaluator(destination)

    row = accept_destination_policies(
        caller, [AccessibleRoot(path=destination)], Lease(), "codex"
    )[0]

    assert row.repository == str(administrative)


def test_snapshot_retains_accepted_bytes_and_detects_changed_runtime(
    tmp_path: Path,
) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    source = evaluator(destination)
    row = accept_destination_policies(
        caller, [AccessibleRoot(path=destination)], Lease(), "codex"
    )[0]
    (source / "runtime" / "kernel" / "decision.py").write_text("VALUE = 2\n")

    assert policy_snapshot_digest(Path(row.snapshot)) == row.digest
    assert policy_snapshot_digest(source) != row.digest
    replacement = row.accepted(caller, "codex")
    assert replacement.digest != row.digest
    assert Path(row.snapshot).exists()


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_current_native_runtime_selects_the_destination_evaluator(
    tmp_path: Path,
    runtime: str,
) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    evaluator(destination, "claude")
    evaluator(destination, "codex")

    row = accept_destination_policies(
        caller, [AccessibleRoot(path=destination)], Lease(), runtime
    )[0]

    assert row.runtime == runtime
    assert f".{runtime}" in Path(row.source).parts
    assert not row.error


def test_missing_or_symlinked_evaluator_is_an_unusable_grant(tmp_path: Path) -> None:
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    accessible = [AccessibleRoot(path=destination)]
    missing = accept_destination_policies(caller, accessible, Lease(), "codex")[0]
    assert missing.error
    source = evaluator(destination)
    data = source / "runtime" / "policy_data.py"
    data.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text("EDIT_LIMIT = 3\n")
    data.symlink_to(outside)

    refused = accept_destination_policies(caller, accessible, Lease(), "codex")[0]

    assert "symlink" in refused.error
    assert not refused.snapshot


def test_operator_refresh_preserves_grants_and_other_launch_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    source = evaluator(destination)
    accessible = [AccessibleRoot(path=destination)]
    lease = fleet_lease(caller, accessible)
    policies = accept_destination_policies(caller, accessible, lease, "codex")
    boundary = compile_boundary(
        HookSet(id="test", policy_ids=[]), contained=True, writable=list(lease.writable)
    )
    sentinels = LaunchSentinels()
    ledger = record_preflight(
        measured(boundary, [], []),
        sentinels,
        caller,
        launch=["harness", "codex"],
        destination_policies=policies,
        read_only_roots=list(lease.read_only),
    )
    before = json.loads(ledger.read_text())
    (source / "runtime" / "policy_data.py").write_text("EDIT_LIMIT = 4\n")

    refreshed = refresh_destination_policy(caller, sentinels.nonce, destination)

    assert refreshed.digest != policies[0].digest
    assert refreshed.writable_roots == policies[0].writable_roots
    assert refreshed.read_only_roots == policies[0].read_only_roots
    after = json.loads(ledger.read_text())
    assert {
        key: value for key, value in before.items() if key != "destination_policies"
    } == {key: value for key, value in after.items() if key != "destination_policies"}
    assert json.loads(after["destination_policies"][0])["digest"] == refreshed.digest
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, tmp_path / "ungranted")
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", sentinels.nonce)
    with pytest.raises(ValueError, match="independent operator"):
        refresh_destination_policy(caller, sentinels.nonce, destination)


def test_an_operator_can_accept_a_later_worktree_inside_an_explicit_bare_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    caller = repository(tmp_path / "caller")
    bare = tmp_path / "upstream.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    accessible = [AccessibleRoot(path=bare)]
    lease = fleet_lease(caller, accessible)
    sentinels = LaunchSentinels()
    boundary = compile_boundary(
        HookSet(id="test", policy_ids=[]), contained=True, writable=list(lease.writable)
    )
    ledger = record_preflight(
        measured(boundary, [], []),
        sentinels,
        caller,
        destination_policies=accept_destination_policies(
            caller, accessible, lease, "codex"
        ),
        read_only_roots=list(lease.read_only),
        destination_authorities=destination_authorities(accessible, "codex"),
    )
    checkout = bare / "tree" / "feature"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "feature",
        str(checkout),
    )
    evaluator(checkout)

    accepted = refresh_destination_policy(caller, sentinels.nonce, checkout)

    assert accepted.checkout == str(checkout)
    assert accepted.repository == str(bare)
    assert accepted.writable_roots == [str(checkout)]
    assert len(json.loads(ledger.read_text())["destination_policies"]) == 1
    unrelated = repository(bare / "unrelated")
    evaluator(unrelated)
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, unrelated)
    outside = tmp_path / "outside"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "outside",
        str(outside),
    )
    evaluator(outside)
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, outside)
    withheld = bare / "restricted"
    protected = withheld / "worktree"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "protected",
        str(protected),
    )
    evaluator(protected)
    document = json.loads(ledger.read_text())
    document["read_only_roots"].append(str(withheld))
    ledger.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, protected)


def test_submodule_repository_identity_comes_from_git(tmp_path: Path) -> None:
    caller = repository(tmp_path / "caller")
    source = repository(tmp_path / "source")
    git(
        "-C",
        str(source),
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    parent = repository(tmp_path / "parent")
    git(
        "-C",
        str(parent),
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(source),
        "dependency",
    )
    submodule = parent / "dependency"
    evaluator(submodule)

    row = accept_destination_policies(
        caller, [AccessibleRoot(path=submodule)], Lease(), "codex"
    )[0]

    assert row.checkout == str(submodule)
    assert row.repository == str(parent / ".git" / "modules" / "dependency")
