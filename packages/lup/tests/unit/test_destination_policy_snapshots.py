"""Launch grants bind exact Git owners and immutable generated policy bytes."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lup.devtools.harness import launch
from lup.devtools.harness.app import create_harness_app
from lup.devtools.harness.composition import NativeTargets
from lup.devtools.harness.policy_refresh import (
    PolicyPreview,
    RefreshDeclined,
    UnreviewedCode,
    refresh_destination_policy,
    terminal_control,
)
from lup.devtools.harness.preflight import (
    LaunchSentinels,
    ROOT_VARIABLE,
    NONCE_VARIABLE,
    record_preflight,
)
from lup.execution.shell import git
from lup.harness.models import HookSet, Plugin
from lup.harness.notice import Banner
from lup.policy.assets.host import (
    policy_data_literals,
    policy_snapshot_digest,
    refreshable_checkout,
)
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


def evaluator(
    checkout: Path, runtime: str = "codex", data: str = "MAXIMUM_ADDED_LINES = 3\n"
) -> Path:
    """An inert generated policy tree with one executable entry point."""
    hooks = checkout / f".{runtime}" / "plugins" / "example" / "hooks"
    (hooks / "scripts").mkdir(parents=True)
    (hooks / "runtime" / "kernel").mkdir(parents=True)
    (hooks / "scripts" / "policy_evaluator.py").write_text("print('inert')\n")
    (hooks / "runtime" / "policy_data.py").write_text(data)
    (hooks / "runtime" / "kernel" / "decision.py").write_text("VALUE = 1\n")
    return hooks


def policy_data(rules: list[str], owners: list[str]) -> str:
    """Generated policy data holding these anti-pattern rules and composition roots."""
    rows = {
        ".py": [
            {
                "id": rule,
                "pattern": rule,
                "message": f"no {rule}",
                "context": "",
                "matcher": "call",
                "strength": "",
                "resolution": "",
            }
            for rule in rules
        ]
    }
    boundaries = [
        {
            "modules": ["lup.providers.claude"],
            "owners": owners,
            "source_roots": ["src/"],
            "rule_id": "seam-boundary",
            "message": "adapters stay in composition roots",
        }
    ]
    return (
        '"""Generated application-owned policy data."""\n\n'
        "from kernel.rows import AntiPatternRow, ImportBoundaryRow\n\n"
        f"ANTI_PATTERN_ROWS: dict[str, list[AntiPatternRow]] = {rows!r}\n\n"
        f"IMPORT_BOUNDARIES: list[ImportBoundaryRow] = {boundaries!r}\n\n"
        "MAXIMUM_ADDED_LINES = 3\n"
    )


def approved(_preview: PolicyPreview) -> bool:
    """The operator's yes, to whatever the refresh shows."""
    return True


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
    outside.write_text("MAXIMUM_ADDED_LINES = 3\n")
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
    (source / "runtime" / "policy_data.py").write_text("MAXIMUM_ADDED_LINES = 4\n")

    refreshed = refresh_destination_policy(
        caller, sentinels.nonce, destination, approved
    )

    assert refreshed.digest != policies[0].digest
    assert refreshed.writable_roots == policies[0].writable_roots
    assert refreshed.read_only_roots == policies[0].read_only_roots
    after = json.loads(ledger.read_text())
    assert {
        key: value for key, value in before.items() if key != "destination_policies"
    } == {key: value for key, value in after.items() if key != "destination_policies"}
    assert json.loads(after["destination_policies"][0])["digest"] == refreshed.digest
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(
            caller, sentinels.nonce, tmp_path / "ungranted", approved
        )
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", sentinels.nonce)
    with pytest.raises(ValueError, match="independent operator"):
        refresh_destination_policy(caller, sentinels.nonce, destination, approved)


def test_an_operator_can_accept_a_later_worktree_inside_an_explicit_bare_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    caller = repository(tmp_path / "caller")
    evaluator(caller)
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

    accepted = refresh_destination_policy(caller, sentinels.nonce, checkout, approved)

    assert accepted.checkout == str(checkout)
    assert accepted.repository == str(bare)
    assert accepted.writable_roots == [str(checkout)]
    assert len(json.loads(ledger.read_text())["destination_policies"]) == 1
    unrelated = repository(bare / "unrelated")
    evaluator(unrelated)
    with pytest.raises(ValueError, match="No recorded writable repository authority"):
        refresh_destination_policy(caller, sentinels.nonce, unrelated, approved)
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
        refresh_destination_policy(caller, sentinels.nonce, outside, approved)
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
        refresh_destination_policy(caller, sentinels.nonce, protected, approved)


def launched_in_own_repository(
    tmp_path: Path, runtime: str = "codex"
) -> tuple[Path, Path, LaunchSentinels]:
    """A launch from one worktree of a bare repository, as `tree/main` opens one.

    Nothing was mounted by name: the lease is the checkout's own, which holds
    the shared directory writable around every worktree beneath it and its
    `config` and `hooks/` read-only, and the ledger records no grant. The
    checkout generates its own policy for either runtime, which is what judges
    every worktree no grant names.
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
    evaluator(caller, "claude")
    evaluator(caller, "codex")
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

    accepted = refresh_destination_policy(caller, sentinels.nonce, checkout, approved)

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
        refresh_destination_policy(caller, sentinels.nonce, unrelated, approved)
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
        refresh_destination_policy(caller, sentinels.nonce, outside, approved)
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
        refresh_destination_policy(caller, sentinels.nonce, protected, approved)
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
        refresh_destination_policy(caller, sentinels.nonce, checkout, approved)
    accepted = refresh_destination_policy(
        caller, sentinels.nonce, checkout, approved, "claude"
    )

    assert accepted.runtime == "claude"
    assert ".claude" in Path(accepted.source).parts
    with pytest.raises(ValueError, match="names another runtime"):
        refresh_destination_policy(caller, sentinels.nonce, checkout, approved, "codex")


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
        refresh_destination_policy(
            caller, sentinels.nonce, checkout, approved, "claude"
        )
    assert (
        refresh_destination_policy(caller, sentinels.nonce, checkout, approved).runtime
        == "codex"
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
        refresh_destination_policy(caller, sentinels.nonce, feature, approved)

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


def cut(bare: Path, path: Path, branch: str) -> Path:
    """A worktree Git cuts itself, on a branch of its own."""
    git("-C", str(bare), "worktree", "add", "-q", "--orphan", "-b", branch, str(path))
    return path


def forged(bare: Path, name: str, branch: str) -> Path:
    """A plain directory dressed as a worktree by writing what `git worktree add` writes.

    An entry under the shared directory naming the directory's `.git` back,
    and a `.git` naming the entry -- every file Git itself would have written,
    with a HEAD on whichever branch the writer chose.
    """
    target = bare / "tree" / name
    (target / "payload").mkdir(parents=True)
    entry = bare / "worktrees" / name
    entry.mkdir(parents=True)
    (entry / "gitdir").write_text(f"{target / '.git'}\n")
    (entry / "commondir").write_text("../..\n")
    (entry / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    (target / ".git").write_text(f"gitdir: {entry}\n")
    return target


@pytest.mark.parametrize(
    "shape, refusal",
    [
        ("launch", "is the launch checkout itself"),
        ("nested in the launch", "nested inside the launch checkout"),
        ("nested in a sibling", "nested inside .*another checkout of its repository"),
        ("forged on the launch branch", "which .* also checks out"),
        ("pointing at another's entry", "registered for another checkout"),
        ("pointing at no entry", "is not a Git worktree"),
    ],
)
def test_the_own_repository_authority_accepts_only_a_worktree_git_cut_beside_the_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    refusal: str,
) -> None:
    """Each shape a `.git` file can be dressed in, refused for what it is.

    The forged entry writes every file `git worktree add` writes, and is
    refused only because it checks out the branch the launch checkout already
    has: Git keeps one branch to one worktree, and a hand-written entry on a
    branch of its own would pass -- which is what the operator's preview is
    for, not a proof this could make.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    match shape:
        case "launch":
            target = caller
        case "nested in the launch":
            target = cut(bare, caller / "tmp" / "wt", "nested")
        case "nested in a sibling":
            sibling = cut(bare, bare / "tree" / "sibling", "sibling")
            target = cut(bare, sibling / "tmp" / "wt", "nested")
        case "forged on the launch branch":
            target = forged(bare, "data", "launch")
        case "pointing at another's entry":
            cut(bare, bare / "tree" / "feature", "feature")
            target = bare / "tree" / "copy"
            target.mkdir()
            (target / ".git").write_text(f"gitdir: {bare / 'worktrees' / 'feature'}\n")
        case _:
            target = bare / "tree" / "ghost"
            target.mkdir()
            (target / ".git").write_text(f"gitdir: {bare / 'worktrees' / 'ghost'}\n")
    if shape != "launch":
        evaluator(target)
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    written = ledger.read_text()
    approve = Mock(return_value=True)

    with pytest.raises(ValueError, match=refusal):
        refresh_destination_policy(caller, sentinels.nonce, target, approve)

    assert not approve.called
    assert ledger.read_text() == written
    assert not (caller / ".lup" / "policy-snapshots").exists()


def test_the_own_repository_authority_reaches_only_the_launch_repository_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worktree another writable mount holds is not one the launch repository leased.

    Git lists it as a worktree of the repository wherever it sits, so the
    lease recomputed from Git holds it only as a mount of its own; the launch
    measured no such mount, and only a scratch directory mounted beside it
    makes it writable at all. The dispatcher, which reads what the launch
    measured rather than asking Git, draws the same line.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    document = json.loads(ledger.read_text())
    document["writable_roots"].append(str(scratch))
    ledger.write_text(json.dumps(document))
    elsewhere = cut(bare, scratch / "feature", "elsewhere")
    evaluator(elsewhere)
    inside = cut(bare, bare / "tree" / "inside", "inside")
    evaluator(inside)
    written = ledger.read_text()
    approve = Mock(return_value=True)

    with pytest.raises(ValueError, match="outside the launch repository's own lease"):
        refresh_destination_policy(caller, sentinels.nonce, elsewhere, approve)
    monkeypatch.setenv("LUP_BOUNDARY_NONCE", sentinels.nonce)
    monkeypatch.setenv("LUP_BOUNDARY_ROOT", str(caller))
    offered = [
        refreshable_checkout(str(checkout / "module.py"), caller)
        for checkout in (elsewhere, inside)
    ]
    monkeypatch.delenv("LUP_BOUNDARY_NONCE")

    assert not approve.called and ledger.read_text() == written
    assert offered == ["", str(inside)]
    assert refresh_destination_policy(
        caller, sentinels.nonce, inside, approved
    ).checkout == str(inside)


def test_the_operator_sees_what_accepting_changes_before_anything_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retired rule and a widened import boundary, read without running either side."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    (caller / ".codex/plugins/example/hooks/runtime/policy_data.py").write_text(
        policy_data(["dict-get", "any-type"], ["src/app/harness/"])
    )
    feature = cut(bare, bare / "tree" / "feature", "feature")
    hooks = evaluator(
        feature,
        "codex",
        policy_data(["any-type"], ["src/app/harness/", "src/renamed/harness/"]),
    )
    (hooks / "runtime" / "kernel" / "decision.py").write_text("VALUE = 2\n")
    approve = Mock(return_value=True)

    with pytest.raises(UnreviewedCode, match="--accept-code") as unreviewed:
        refresh_destination_policy(caller, sentinels.nonce, feature, approve)
    assert not approve.called
    accepted = refresh_destination_policy(
        caller, sentinels.nonce, feature, approve, accept_code=True
    )

    (preview,) = approve.call_args.args
    assert unreviewed.value.preview.lines() == preview.lines()
    changes = {change.name: change for change in preview.changes}
    assert list(changes) == ["ANTI_PATTERN_ROWS", "IMPORT_BOUNDARIES"]
    assert changes["ANTI_PATTERN_ROWS"].removed == [
        '".py": id="dict-get" pattern="dict-get" message="no dict-get" context="" '
        'matcher="call" strength="" resolution=""'
    ]
    assert changes["ANTI_PATTERN_ROWS"].added == []
    (before,) = changes["IMPORT_BOUNDARIES"].removed
    (after,) = changes["IMPORT_BOUNDARIES"].added
    assert "src/renamed/harness/" in after and "src/renamed/harness/" not in before
    (code,) = preview.code
    assert (code.name, code.state) == ("runtime/kernel/decision.py", "changed")
    assert "-VALUE = 1" in code.diff and "+VALUE = 2" in code.diff
    shown = "\n".join(preview.lines())
    assert '    - ".py": id="dict-get"' in shown
    assert "  IMPORT_BOUNDARIES" in shown
    assert "    runtime/kernel/decision.py (changed)" in shown
    assert "      +VALUE = 2" in shown
    assert accepted.digest == preview.digest


def test_a_reordered_first_match_table_is_shown_where_each_entry_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two path roles swapped: nothing added, nothing dropped, and a path judged apart.

    Roles are read first match first, so the order is part of what they say.
    A comparison of which entries each side holds reads the two as one table.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    roles = [
        {"root": "src/data/", "role": "data"},
        {"root": "src/", "role": "production"},
    ]
    (caller / ".codex/plugins/example/hooks/runtime/policy_data.py").write_text(
        f"PATH_ROLES = {roles!r}\n"
    )
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(feature, "codex", f"PATH_ROLES = {roles[::-1]!r}\n")
    approve = Mock(return_value=True)

    refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    (preview,) = approve.call_args.args
    (change,) = preview.changes
    assert change.name == "PATH_ROLES"
    # `src/` now comes first, and so wins for everything under `src/data/`.
    assert change.lines == [
        "@ entry 1 of 2",
        '+ root="src/" role="production"',
        "@ entry 2 of 2",
        '- root="src/" role="production"',
    ]


def rule(value: str, reason: str) -> dict[str, str | bool]:
    """One protected-path row as generation writes it."""
    return {
        "kind": "exact",
        "value": value,
        "reason": reason,
        "recovery": "",
        "allow_autonomous": False,
    }


def test_the_preview_spells_out_whatever_could_rewrite_the_screen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed protected path stays on screen, whatever the session wrote after it.

    A carriage return and an erase-line in a reason, cursor movement and a
    clear-screen in a suffix key, a right-to-left override: each would reach a
    terminal as an instruction to it. Every one is spelled as its code point,
    and every field of a row is shown, empty ones included.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    kept = rule("pyproject.toml", "protected path requires approval")
    (caller / ".codex/plugins/example/hooks/runtime/policy_data.py").write_text(
        f"PATH_RULES = {[rule('README.md', 'README.md is human-authored'), kept]!r}\n"
    )
    hostile = rule("notes.md", "fine\r\x1b[2K\u202e")
    pattern = {
        "id": "x",
        "pattern": "x",
        "message": "x",
        "context": "",
        "matcher": "",
        "strength": "",
        "resolution": "",
    }
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(
        feature,
        "codex",
        f"PATH_RULES = {[kept, hostile]!r}\n"
        f"ANTI_PATTERN_ROWS = { ({'.py\x1b[1A\x1b[2J': [pattern]})!r}\n",
    )
    approve = Mock(return_value=True)

    refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    (preview,) = approve.call_args.args
    shown = preview.lines()
    assert not [line for line in shown if any(terminal_control(c) for c in line)]
    assert (
        '    - kind="exact" value="README.md" reason="README.md is human-authored" '
        'recovery="" allow_autonomous=false'
    ) in shown
    assert any("\\u001b[2K" in line and "\\u202e" in line for line in shown)
    assert any("\\u001b[1A\\u001b[2J" in line for line in shown)


@pytest.mark.parametrize(
    "row, departure",
    [
        ({**rule("a", "b"), "hidden": "x"}, r'PATH_RULES\[0\]\["hidden"\] is no field'),
        (
            {"kind": "exact", "value": "a", "reason": "b"},
            r"PATH_RULES\[0\] lacks recovery",
        ),
        ({**rule("a", "b"), "allow_autonomous": 0}, r"allow_autonomous is not bool"),
        ({**rule("a", "b"), "kind": "anything"}, r"PATH_RULES\[0\]\.kind is none of"),
    ],
)
def test_a_row_is_held_to_its_row_type_before_anything_is_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row: dict[str, object],
    departure: str,
) -> None:
    """A field the row type lacks, one it left out, one of another type: all refused."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(feature, "codex", f"PATH_RULES = {[row]!r}\n")
    approve = Mock(return_value=True)

    with pytest.raises(ValueError, match=departure):
        refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    assert not approve.called


@pytest.mark.parametrize(
    "character", ["\x1b", "\r", "\u202e", "\u2066", "\x85", "\u2028"]
)
def test_code_holding_a_control_is_refused_rather_than_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    character: str,
) -> None:
    """A diff whose lines a terminal would redraw is no diff an operator can read."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    hooks = evaluator(feature, "codex")
    (hooks / "runtime" / "kernel" / "decision.py").write_text(
        f"VALUE = 1\nOTHER = 2  # {character}hidden\n"
    )
    approve = Mock(return_value=True)

    with pytest.raises(
        ValueError, match=rf"decision\.py:2 holds U\+{ord(character):04X}"
    ):
        refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    assert not approve.called


def test_a_declined_refresh_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(feature, "codex", policy_data(["any-type"], []))
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    written = ledger.read_text()

    with pytest.raises(RefreshDeclined):
        refresh_destination_policy(
            caller, sentinels.nonce, feature, Mock(return_value=False)
        )

    assert ledger.read_text() == written
    assert not (caller / ".lup" / "policy-snapshots").exists()


def test_the_command_asks_before_accepting_and_yes_answers_for_the_operator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preview is printed either way; only the question is skipped."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(feature, "codex", policy_data(["any-type"], ["src/app/harness/"]))
    monkeypatch.setattr("lup.devtools.harness.app.project_root", lambda: caller)
    app = create_harness_app(NativeTargets(builders={}), [])
    arguments = [
        "policy-refresh",
        "--nonce",
        sentinels.nonce,
        "--repository",
        str(feature),
    ]
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"

    declined = CliRunner().invoke(app, arguments, input="n\n")
    untouched = json.loads(ledger.read_text())["destination_policies"]
    accepted = CliRunner().invoke(app, [*arguments, "--yes"])

    assert declined.exit_code == 1
    assert "ANTI_PATTERN_ROWS" in declined.output
    assert "Accept this policy for the launch?" in declined.output
    assert "Nothing accepted" in declined.output and untouched == []
    assert accepted.exit_code == 0, accepted.output
    assert "ANTI_PATTERN_ROWS" in accepted.output
    assert "Accept this policy" not in accepted.output
    assert len(json.loads(ledger.read_text())["destination_policies"]) == 1


def test_the_command_shows_differing_code_and_accepts_it_only_when_told_to(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code the launch's lup would not generate is shown as a diff, then refused.

    `--yes` answers the question about data and nothing else: running other
    code is its own answer, given once the diff has been read.
    """
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    hooks = evaluator(feature, "codex")
    (hooks / "runtime" / "kernel" / "decision.py").write_text("VALUE = 2\n")
    monkeypatch.setattr("lup.devtools.harness.app.project_root", lambda: caller)
    app = create_harness_app(NativeTargets(builders={}), [])
    arguments = [
        "policy-refresh",
        "--nonce",
        sentinels.nonce,
        "--repository",
        str(feature),
        "--yes",
    ]
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"

    refused = CliRunner().invoke(app, arguments)
    untouched = json.loads(ledger.read_text())["destination_policies"]
    accepted = CliRunner().invoke(app, [*arguments, "--accept-code"])

    assert refused.exit_code == 1
    assert "runtime/kernel/decision.py (changed)" in refused.output
    assert "-VALUE = 1" in refused.output and "+VALUE = 2" in refused.output
    assert "--accept-code" in refused.output and untouched == []
    assert accepted.exit_code == 0, accepted.output
    assert "+VALUE = 2" in accepted.output
    assert len(json.loads(ledger.read_text())["destination_policies"]) == 1


def test_what_is_accepted_is_exactly_what_was_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    hooks = evaluator(feature, "codex", policy_data(["any-type"], []))
    ledger = caller / ".lup/preflight" / f"{sentinels.nonce}.json"
    written = ledger.read_text()

    shown_data = (hooks / "runtime" / "policy_data.py").read_bytes()

    def changed_and_changed_back(path: Path, text: str | None = None) -> dict:
        """The checkout rewritten while the preview reads, then put back."""
        if path.is_relative_to(feature):
            path.write_text(policy_data(["dict-get"], []))
        try:
            return policy_data_literals(path, text)
        finally:
            if path.is_relative_to(feature):
                path.write_bytes(shown_data)

    def regenerated_while_asked(preview: PolicyPreview) -> bool:
        (hooks / "runtime" / "policy_data.py").write_text(policy_data([], []))
        return True

    monkeypatch.setattr(
        "lup.devtools.harness.policy_refresh.policy_data_literals",
        changed_and_changed_back,
    )
    accepted = refresh_destination_policy(
        caller, sentinels.nonce, feature, regenerated_while_asked
    )

    assert ledger.read_text() != written
    snapshot = Path(accepted.snapshot)
    assert (snapshot / "runtime" / "policy_data.py").read_bytes() == shown_data
    assert accepted.digest == policy_snapshot_digest(snapshot)


@pytest.mark.parametrize(
    "appended, refusal",
    [
        ("import os\n", "is a statement generation never writes"),
        ("LIMIT: print('ran') = 3\n", "is a statement generation never writes"),
        ("LIMIT = len('ran')\n", "assigns LIMIT something other than a literal"),
        (
            "from kernel.rows import PathRuleRow as LIMIT\n",
            "imports a row type under another name",
        ),
    ],
)
def test_a_policy_holding_more_than_data_is_refused_before_it_is_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    appended: str,
    refusal: str,
) -> None:
    """Whatever generation never writes would run once accepted, so none of it is read."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(feature, "codex", policy_data(["any-type"], []) + appended)
    approve = Mock(return_value=True)

    with pytest.raises(ValueError, match=rf"policy_data\.py:\d+ {refusal}"):
        refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    assert not approve.called


def test_a_name_both_imported_and_assigned_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which of the two a name holds is decided by run order, which no reading shows."""
    monkeypatch.delenv("LUP_BOUNDARY_NONCE", raising=False)
    bare, caller, sentinels = launched_in_own_repository(tmp_path)
    feature = cut(bare, bare / "tree" / "feature", "feature")
    evaluator(
        feature,
        "codex",
        policy_data([], []) + "from kernel.rows import MAXIMUM_ADDED_LINES\n",
    )
    approve = Mock(return_value=True)

    with pytest.raises(
        ValueError, match="both imports and assigns MAXIMUM_ADDED_LINES"
    ):
        refresh_destination_policy(caller, sentinels.nonce, feature, approve)

    assert not approve.called


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
