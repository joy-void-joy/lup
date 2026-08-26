"""The job store: durability across processes, and refusing an unsafe id."""

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest
from pydantic import ValidationError

from lup.orchestration.jobs import (
    DockerJobConfig,
    JobExecutionResult,
    JobInputFile,
    JobRecord,
    JobSpec,
    JobStore,
)

SUBMITTED = datetime(2026, 1, 1, tzinfo=UTC)


def record(job_id: str = "abc", state: str = "queued") -> JobRecord:
    return JobRecord.model_validate(
        {
            "job_id": job_id,
            "state": state,
            "submitted_at": SUBMITTED,
            "updated_at": SUBMITTED,
            "container_name": f"lup-sandbox-job-{job_id}",
        }
    )


def test_a_record_survives_a_store_that_never_saw_it_written(tmp_path: Path) -> None:
    # The point of the store: a later process holding only the job id reads
    # back what an earlier one wrote.
    JobStore(tmp_path).write_record(record())

    assert JobStore(tmp_path).read_record("abc").container_name == (
        "lup-sandbox-job-abc"
    )


def test_an_unknown_job_is_an_error_rather_than_an_empty_record(
    tmp_path: Path,
) -> None:
    with pytest.raises(KeyError):
        JobStore(tmp_path).read_record("missing")


@pytest.mark.parametrize("job_id", ["", ".", "..", "../escape", "a/b"])
def test_a_job_id_that_could_name_another_directory_is_refused(
    tmp_path: Path, job_id: str
) -> None:
    # Job ids reach this from tool calls, so a traversal here would let a
    # caller read or write outside the store.
    with pytest.raises(ValueError):
        JobStore(tmp_path).directory(job_id)


def test_no_terminal_artifact_reads_as_none_rather_than_failing(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path)
    store.write_record(record())

    assert store.read_execution("abc") is None


def test_a_written_artifact_is_read_back(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.write_record(record())
    result_path = store.result_path("abc")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        JobExecutionResult(
            exit_code=0,
            started_at=SUBMITTED,
            finished_at=SUBMITTED,
            stdout_path=Path("stdout.txt"),
            stderr_path=Path("stderr.txt"),
        ).model_dump_json(),
        encoding="utf-8",
    )

    execution = store.read_execution("abc")

    assert execution is not None
    assert execution.exit_code == 0


def test_records_list_newest_first(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.write_record(record("old"))
    store.write_record(
        record("new").model_copy(
            update={"submitted_at": datetime(2026, 6, 1, tzinfo=UTC)}
        )
    )

    assert [item.job_id for item in store.list_records()] == ["new", "old"]


def test_an_empty_store_lists_nothing(tmp_path: Path) -> None:
    assert JobStore(tmp_path / "absent").list_records() == []


def test_job_inputs_are_mounted_as_files_instead_of_python_literals(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path / "jobs")
    directories = store.write_inputs(
        "payload",
        JobSpec(
            code="print('done')",
            input_files=[
                JobInputFile(
                    path=PurePosixPath("problems/000.cnf.gz"), content=b"compressed"
                )
            ],
        ),
    )

    assert (directories.input_dir / "job.py").read_text(encoding="utf-8") == (
        "print('done')"
    )
    assert (directories.input_dir / "problems/000.cnf.gz").read_bytes() == (
        b"compressed"
    )
    assert "compressed" not in (directories.input_dir / "spec.json").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "job.py", "runner.py/child"]
)
def test_job_inputs_cannot_replace_control_files_or_escape(path: str) -> None:
    with pytest.raises(ValidationError):
        JobInputFile(path=PurePosixPath(path), content=b"payload")


def test_job_input_paths_are_unique() -> None:
    duplicate = JobInputFile(path=PurePosixPath("problem.cnf"), content=b"payload")

    with pytest.raises(ValidationError, match="must be unique"):
        JobSpec(code="pass", input_files=[duplicate, duplicate])


def test_docker_job_roots_are_absolute_bind_mounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert DockerJobConfig(root=Path("jobs")).root == tmp_path / "jobs"


def test_a_settled_job_reports_itself_as_settled() -> None:
    assert record(state="succeeded").settled
    assert record(state="cancelled").settled
    assert not record(state="running").settled
