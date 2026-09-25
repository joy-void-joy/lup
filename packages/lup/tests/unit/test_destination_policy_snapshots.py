"""Launch grants bind exact Git owners and immutable generated policy bytes."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lup.devtools.harness import launch
from lup.devtools.harness.app import create_harness_app
from lup.devtools.harness.composition import NativeTargets
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
from lup.policy.snapshots import (
    DestinationPolicy,
    accept_destination_policies,
    destination_authorities,
)
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

    launch.settle_boundary(
        plugin, sandbox, [], sentinels, environment, Banner(), runtime="claude"
    )

    assert environment[ROOT_VARIABLE] == str(checkout)
    assert environment[NONCE_VARIABLE] == sentinels.nonce
    ledger = checkout / ".lup/preflight" / f"{sentinels.nonce}.json"
    assert json.loads(ledger.read_text())["runtime"] == ["claude"]


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


def launched_in_own_repository(
    tmp_path: Path, runtime: str = "codex"
) -> tuple[Path, Path, LaunchSentinels]:
    """A launch from one worktree of a bare repository, as `tree/main` opens one.

    Nothing was mounted by name: the lease is the checkout's own, which holds
    the shared directory writable around every worktree beneath it and its
    `config` and `hooks/` read-only, and the ledger records no grant.
    """
    bare = tmp_path / "project.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    caller = bare / "tree" / "main"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "launch",
        str(caller),
    )
    lease = fleet_lease(caller)
    sentinels = LaunchSentinels()
    record_preflight(
        measured(
            compile_boundary(
                HookSet(id="test", policy_ids=[]),
                contained=True,
                writable=list(lease.writable),
            ),
            [],
            [],
        ),
        sentinels,
        caller,
        read_only_roots=list(lease.read_only),
        runtime=runtime,
    )
    return bare, caller, sentinels


def test_an_operator_can_accept_a_worktree_the_session_cut_in_its_own_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    assert json.loads(ledger.read_text())["destination_authorities"] == []
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
    assert accepted.runtime == "codex"
    assert accepted.writable_roots == [str(checkout)]
    assert accepted.digest == policy_snapshot_digest(Path(accepted.source))
    assert [
        json.loads(row)["checkout"]
        for row in json.loads(ledger.read_text())["destination_policies"]
    ] == [str(checkout)]


def test_the_launch_repository_authority_reaches_no_other_repository_or_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    unrelated = repository(bare / "tree" / "unrelated")
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
    withheld = bare / "tree" / "restricted"
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
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    document = json.loads(ledger.read_text())
    document["read_only_roots"].append(str(withheld))
    ledger.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, protected)
    assert json.loads(ledger.read_text())["destination_policies"] == []


def test_a_ledger_recording_no_runtime_takes_the_operators_word_for_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path, runtime="")
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
    evaluator(checkout, "claude")
    evaluator(checkout, "codex")

    with pytest.raises(ValueError, match="--runtime claude or --runtime codex"):
        refresh_destination_policy(caller, sentinels.nonce, checkout)
    accepted = refresh_destination_policy(caller, sentinels.nonce, checkout, "claude")

    assert accepted.runtime == "claude"
    assert ".claude" in Path(accepted.source).parts
    with pytest.raises(ValueError, match="names another runtime"):
        refresh_destination_policy(caller, sentinels.nonce, checkout, "codex")


def test_a_recorded_runtime_outranks_an_operator_naming_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path, runtime="codex")
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
    evaluator(checkout, "claude")
    evaluator(checkout, "codex")

    with pytest.raises(ValueError, match="This launch opened codex"):
        refresh_destination_policy(caller, sentinels.nonce, checkout, "claude")
    assert (
        refresh_destination_policy(caller, sentinels.nonce, checkout).runtime == "codex"
    )


def test_the_command_line_names_only_a_runtime_a_policy_is_generated_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime is spelled into the path an evaluator is read from, so it is a choice.

    Named as a path instead, it walks out of the checkout to a tree the
    session wrote beside it, which a ledger recording no runtime would
    otherwise have accepted.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path, runtime="")
    feature = bare / "tree" / "feature"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "feature",
        str(feature),
    )
    (feature / ".x").mkdir()
    evaluator(bare / "tree" / "elsewhere", "y")

    result = CliRunner().invoke(
        create_harness_app(NativeTargets(builders={}), []),
        [
            "policy-refresh",
            "--nonce",
            sentinels.nonce,
            "--repository",
            str(feature),
            "--runtime",
            "x/../../elsewhere/.y",
        ],
    )

    assert result.exit_code == 2
    assert "'claude', 'codex'" in result.output
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    assert json.loads(ledger.read_text())["destination_policies"] == []
    assert not (caller / ".lup" / "policy-snapshots").exists()


@pytest.mark.parametrize("field", ["runtime", "destination_authorities"])
def test_a_ledger_naming_a_path_for_its_runtime_accepts_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """The ledger is a file in the checkout the session works in, read as a vocabulary."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path, runtime="")
    feature = bare / "tree" / "feature"
    git(
        "-C",
        str(bare),
        "worktree",
        "add",
        "-q",
        "--orphan",
        "-b",
        "feature",
        str(feature),
    )
    evaluator(feature)
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    document = json.loads(ledger.read_text())
    named = "x/../../elsewhere/.y"
    document[field] = (
        [named]
        if field == "runtime"
        else [
            json.dumps({"repository": str(bare), "root": str(bare), "runtime": named})
        ]
    )
    ledger.write_text(json.dumps(document))
    written = ledger.read_text()

    with pytest.raises(ValidationError, match="'claude' or 'codex'"):
        refresh_destination_policy(caller, sentinels.nonce, feature)

    assert ledger.read_text() == written
    assert not (caller / ".lup" / "policy-snapshots").exists()


def test_acceptance_reads_no_evaluator_tree_the_checkout_does_not_hold(
    tmp_path: Path,
) -> None:
    """Neither a path spelled as a runtime nor a runtime tree linked from elsewhere."""
    caller = repository(tmp_path / "caller")
    destination = repository(tmp_path / "destination")
    evaluator(tmp_path / "elsewhere")
    row = DestinationPolicy(
        repository=str(repository_layout(destination).common),
        checkout=str(destination),
        writable_roots=[str(destination)],
        read_only_roots=[],
    )

    walked = row.accepted(caller, "x/../../elsewhere/.codex")
    (destination / ".codex").symlink_to(
        tmp_path / "elsewhere" / ".codex", target_is_directory=True
    )
    linked = row.accepted(caller, "codex")

    assert "not a runtime" in walked.error and walked.runtime == ""
    assert "outside" in linked.error and str(tmp_path / "elsewhere") in linked.error
    assert not walked.snapshot and not linked.snapshot
    assert not (caller / ".lup" / "policy-snapshots").exists()


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
