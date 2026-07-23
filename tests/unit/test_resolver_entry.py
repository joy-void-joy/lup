"""Behavioral contract of the Claude resolver workflow entry's args handling."""

import json
import shutil
from importlib import resources
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from lup.harness.process import LaunchRequest, LocalProcessLauncher
from lup.types import JsonObject, JsonValue

DRIVER = Path(__file__).parent / "assets" / "resolve_entry_driver.js"
RESOLVER_ENTRY = (
    resources.files("lup_template.devtools.harness.content")
    .joinpath("assets/resolve.js")
    .read_text("utf-8")
)
BASE_COMMAND = [
    "uv",
    "run",
    "lup-devtools",
    "harness",
    "resolve",
    "--adapter",
    "claude",
]

needs_bun = pytest.mark.skipif(
    shutil.which("bun") is None, reason="needs the bun runtime"
)


class EntryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_code: int


class EntryRun(BaseModel):
    """One recorded driver execution of the workflow entry."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str = ""
    spawned: list[list[str]]
    result: EntryResult | None = None


def run_entry(tmp_path: Path, envelope: JsonObject) -> EntryRun:
    entry = tmp_path / "resolve.js"
    entry.write_text(RESOLVER_ENTRY, encoding="utf-8")
    status = LocalProcessLauncher().launch(
        LaunchRequest(
            arguments=["bun", str(DRIVER), str(entry), json.dumps(envelope)],
            cwd=tmp_path,
        )
    )
    assert status.code == 0, status.stderr
    return EntryRun.model_validate_json(status.stdout)


def test_committed_workflow_entry_matches_the_canonical_source() -> None:
    committed = Path(".claude/workflows/commands/resolve.js").read_text(
        encoding="utf-8"
    )
    assert committed == RESOLVER_ENTRY


@needs_bun
def test_entry_accepts_parsed_encoded_and_double_encoded_args(
    tmp_path: Path,
) -> None:
    options: JsonValue = {"run_id": "run-7", "accept": True}
    deliveries: list[JsonValue] = [
        options,
        json.dumps(options),
        json.dumps(json.dumps(options)),
    ]
    for delivered in deliveries:
        run = run_entry(tmp_path, {"delivery": "value", "value": delivered})
        assert run.ok, run.message
        assert run.spawned == [[*BASE_COMMAND, "--run-id", "run-7", "--accept"]]
        assert run.result == EntryResult(exit_code=0)


@needs_bun
def test_entry_treats_absent_empty_and_null_args_as_defaults(
    tmp_path: Path,
) -> None:
    envelopes: list[JsonObject] = [
        {"delivery": "absent"},
        {"delivery": "value", "value": None},
        {"delivery": "value", "value": ""},
        {"delivery": "value", "value": "   "},
        {"delivery": "value", "value": "null"},
    ]
    for envelope in envelopes:
        run = run_entry(tmp_path, envelope)
        assert run.ok, run.message
        assert run.spawned == [BASE_COMMAND]


@needs_bun
def test_entry_rejects_undecodable_args_without_launching(tmp_path: Path) -> None:
    deliveries: list[JsonValue] = ["run-7", '"run-7"', '{"run_id":', [1], 7]
    for delivered in deliveries:
        run = run_entry(tmp_path, {"delivery": "value", "value": delivered})
        assert not run.ok
        assert "JSON object" in run.message
        assert run.spawned == []


@needs_bun
def test_entry_maps_rejection_and_surfaces_core_failure(tmp_path: Path) -> None:
    run = run_entry(
        tmp_path,
        {"delivery": "value", "value": {"accept": False}, "exit": 3},
    )
    assert not run.ok
    assert "exited with status 3" in run.message
    assert run.spawned == [[*BASE_COMMAND, "--reject"]]
