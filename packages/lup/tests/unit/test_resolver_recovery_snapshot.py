"""Recovery evidence survives index formats, submodules and Git pruning."""

import shutil
from pathlib import Path

from lup.execution.shell import git
from lup.resolver.recovery import (
    IntegrationRecoveryDesk,
    IntegrationRecoveryMode,
    RecoverySnapshot,
)
from tests.unit.test_resolver_recovery import RecoveryFixture
from tests.unit.test_resolver_recovery import recovery as integration_recovery

recovery = integration_recovery


def test_saved_merge_metadata_objects_survive_pruning(
    recovery: RecoveryFixture,
) -> None:
    recovery.command("checkout", "-b", "other")
    (recovery.lease.root / "README.md").write_text("other\n")
    recovery.command("commit", "-am", "other")
    other = recovery.command("rev-parse", "HEAD")
    recovery.command("checkout", "review")
    (recovery.lease.root / "README.md").write_text("review\n")
    recovery.command("commit", "-am", "review")
    git("merge", "other", _cwd=str(recovery.lease.root), _ok_code=1)
    auto_merge = recovery.command("rev-parse", "AUTO_MERGE")
    conflict = (recovery.lease.root / "README.md").read_text()

    report = IntegrationRecoveryDesk(recovery.repository).recover(
        IntegrationRecoveryMode.RESTORE
    )
    saved = RecoverySnapshot.model_validate_json(
        (report.evidence / "references.json").read_text()
    )
    references = {item.source: item for item in saved.references}
    assert references["AUTO_MERGE"].object_id == auto_merge
    assert references["MERGE_HEAD"].object_id == other
    assert references["HEAD"].reference == report.backup_ref
    recovery.command("branch", "-D", "other")
    recovery.command("reflog", "expire", "--expire=now", "--all")
    recovery.command("gc", "--prune=now")
    assert (
        recovery.command("rev-parse", references["AUTO_MERGE"].reference) == auto_merge
    )
    assert recovery.command("cat-file", "-t", auto_merge) == "tree"
    assert recovery.command("show", f"{auto_merge}:README.md") == conflict.strip()
    assert recovery.command("cat-file", "-t", other) == "commit"


def test_foreign_gitlink_does_not_prevent_snapshot(
    recovery: RecoveryFixture, tmp_path: Path
) -> None:
    child = tmp_path / "submodule"
    child.mkdir()
    git("init", _cwd=str(child))
    git(
        "-c",
        "user.name=Probe",
        "-c",
        "user.email=probe@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "foreign child",
        _cwd=str(child),
    )
    foreign = str(git("rev-parse", "HEAD", _cwd=str(child))).strip()
    recovery.command("update-index", "--add", "--cacheinfo", f"160000,{foreign},nested")

    report = IntegrationRecoveryDesk(recovery.repository).recover(
        IntegrationRecoveryMode.RESTORE
    )

    isolated = tmp_path / "isolated"
    git("init", str(isolated))
    with (report.evidence / "index.pack").open("rb") as packed:
        git("unpack-objects", _in=packed, _cwd=str(isolated))
    listed = str(
        git(
            "ls-files",
            "--stage",
            _env={"GIT_INDEX_FILE": str(report.evidence / "git" / "index")},
            _cwd=str(isolated),
        )
    )
    assert f"160000 {foreign} 0\tnested" in listed
    assert (report.evidence / "completed.json").is_file()


def test_split_index_snapshot_reads_without_the_original_shared_index(
    recovery: RecoveryFixture, tmp_path: Path
) -> None:
    (recovery.lease.root / "staged").write_text("staged snapshot\n")
    recovery.command("add", "staged")
    recovery.command("update-index", "--split-index")
    report = IntegrationRecoveryDesk(recovery.repository).recover(
        IntegrationRecoveryMode.RESTORE
    )
    assert list((report.evidence / "git").glob("sharedindex.*"))
    isolated = tmp_path / "isolated"
    git("init", str(isolated))
    with (report.evidence / "index.pack").open("rb") as packed:
        git("unpack-objects", _in=packed, _cwd=str(isolated))
    copied = isolated / ".git" / "index"
    shutil.copy2(report.evidence / "git" / "index", copied)
    for path in (report.evidence / "git").glob("sharedindex.*"):
        shutil.copy2(path, copied.parent / path.name)
    assert str(git("show", ":staged", _cwd=str(isolated))) == "staged snapshot\n"


def test_sparse_index_snapshot_retains_skipped_tree_objects(
    recovery: RecoveryFixture, tmp_path: Path
) -> None:
    for directory in ("visible", "skipped"):
        (recovery.lease.root / directory).mkdir()
        (recovery.lease.root / directory / "file").write_text(f"{directory} contents\n")
    recovery.command("add", "visible", "skipped")
    recovery.command("commit", "-m", "directories")
    recovery.command("sparse-checkout", "init", "--cone", "--sparse-index")
    recovery.command("sparse-checkout", "set", "visible")
    saved_tree = recovery.command("rev-parse", "HEAD:skipped")
    report = IntegrationRecoveryDesk(recovery.repository).recover(
        IntegrationRecoveryMode.RESTORE
    )
    isolated = tmp_path / "isolated"
    git("init", str(isolated))
    with (report.evidence / "index.pack").open("rb") as packed:
        git("unpack-objects", _in=packed, _cwd=str(isolated))
    assert (
        str(git("show", f"{saved_tree}:file", _cwd=str(isolated)))
        == "skipped contents\n"
    )
