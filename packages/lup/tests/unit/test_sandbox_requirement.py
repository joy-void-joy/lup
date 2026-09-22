"""Setup must exercise the sandbox, not equate daemon access with execution."""

from pathlib import Path
from unittest.mock import Mock

import grp
import pytest
from docker.errors import APIError
from typer.testing import CliRunner

from lup.devtools.harness.app import create_harness_app
from lup.devtools.harness.composition import NativeTargets
from lup.devtools.harness.sandbox import check_sandbox
from lup.harness.requirements import ExerciseOutcome, Manifest, SupplementaryGroup
from lup.harness.toolchain import sandbox_requirement
from lup.sandbox.container import Sandbox
from lup.sandbox.models import ExecuteCodeResult


@pytest.fixture
def exercise(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Keep the real sandbox configuration and replace only external operations."""
    simulated = Mock()
    simulated.run_code.return_value = ExecuteCodeResult(exit_code=0, result="2")
    monkeypatch.setattr(Sandbox, "start", lambda sandbox: simulated.start(sandbox))
    monkeypatch.setattr(Sandbox, "stop", lambda sandbox: simulated.stop(sandbox))
    monkeypatch.setattr(
        Sandbox,
        "run_code",
        lambda sandbox, code, timeout_seconds: simulated.run_code(
            code, timeout_seconds
        ),
    )
    return simulated


def test_setup_evaluates_through_an_owned_network_disabled_sandbox(
    exercise: Mock,
) -> None:
    outcome = check_sandbox("example/sandbox:tested")

    assert outcome.proved
    sandbox = exercise.start.call_args.args[0]
    assert sandbox.docker_image == "example/sandbox:tested"
    assert sandbox.network_mode == "none"
    assert sandbox.pre_install is None
    exercise.run_code.assert_called_once_with("1 + 1", 10)
    exercise.stop.assert_called_once_with(sandbox)
    assert not Path(sandbox.shared_dir).exists()


def test_daemon_access_does_not_hide_forbidden_container_creation(
    exercise: Mock,
) -> None:
    exercise.start.side_effect = APIError("403 Forbidden: container creation denied")

    outcome = check_sandbox()

    assert not outcome.proved
    assert "startup before evaluating" in outcome.detail
    assert "403 Forbidden: container creation denied" in outcome.detail
    exercise.run_code.assert_not_called()
    exercise.stop.assert_called_once()


@pytest.mark.parametrize(
    "result",
    [
        ExecuteCodeResult(exit_code=1, stderr="ModuleNotFoundError: missing runtime"),
        ExecuteCodeResult(exit_code=0, result="3"),
    ],
)
def test_wrong_or_failed_evaluation_remains_a_failed_requirement(
    exercise: Mock, result: ExecuteCodeResult
) -> None:
    exercise.run_code.return_value = result

    outcome = check_sandbox()

    assert not outcome.proved
    assert result.model_dump_json() in outcome.detail
    exercise.stop.assert_called_once()


def test_cleanup_failure_retains_the_original_failure(exercise: Mock) -> None:
    exercise.start.side_effect = RuntimeError("cannot start container")
    exercise.stop.side_effect = RuntimeError("cannot remove container")

    outcome = check_sandbox()

    assert not outcome.proved
    assert "cannot start container" in outcome.detail
    assert "cannot remove container" in outcome.detail


def test_sandbox_check_is_setup_only_and_does_not_nest_inside_the_image() -> None:
    required = sandbox_requirement("example/sandbox:tested")
    manifest = Manifest(requirements=[required])

    assert manifest.on_the_host() == []
    assert manifest.on_the_host(setting_up=True) == [required]
    assert manifest.inside_the_image() == []
    assert required.exercise.programs() == ["uv"]


def test_cli_reports_execution_refusal_with_nonzero_status(exercise: Mock) -> None:
    exercise.start.side_effect = APIError("403 Forbidden: container creation denied")
    app = create_harness_app(NativeTargets(builders={}), [])

    result = CliRunner().invoke(app, ["sandbox-check"])

    assert result.exit_code == 1
    assert "container creation denied" in result.stderr
    exercise.stop.assert_called_once()


def test_stale_process_groups_name_the_required_session_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lup.harness.requirements.grp.getgrnam",
        lambda name: grp.struct_group((name, "x", 1234, ["operator"])),
    )
    monkeypatch.setattr("lup.harness.requirements.os.getgroups", lambda: [1000])

    cause = SupplementaryGroup(group="docker").cause(
        {"USER": "operator"},
        ExerciseOutcome(proved=False, detail="permission denied opening socket"),
    )

    assert "belongs to docker" in cause
    assert "current process does not have that membership" in cause
    assert "Log out and back in" in cause
