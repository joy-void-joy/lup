"""Host probes cannot turn an operator launcher into an inherited agent session."""

import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

import lup.devtools.harness.launch as launch
from lup.devtools.dev.review_service import require_review_operator
from lup.devtools.harness.preflight import NONCE_VARIABLE, LaunchSentinels
from lup.harness.requirements import SENTINEL_VARIABLE, Manifest


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_host_preflight_preserves_operator_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inherited: bool,
    fails: bool,
) -> None:
    monkeypatch.setenv(NONCE_VARIABLE, "inherited-boundary" if inherited else "")
    monkeypatch.setenv(SENTINEL_VARIABLE, "original-sentinel")
    original = dict(os.environ)
    sentinels = LaunchSentinels()
    probe = Mock()
    probe.check.return_value = []
    if fails:
        probe.check.side_effect = RuntimeError("host probe failed")
    monkeypatch.setattr(launch, "for_host", Mock(return_value=probe))
    monkeypatch.setattr(launch, "container_client", Mock())
    monkeypatch.setattr(launch, "granted_devices", lambda: [])
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)

    with (
        pytest.raises(RuntimeError, match="host probe failed")
        if fails
        else nullcontext()
    ):
        launch.report_requirements(Manifest(), sentinels=sentinels, in_passing=True)

    with (
        pytest.raises(ValueError, match="independent operator terminal")
        if inherited
        else nullcontext()
    ):
        require_review_operator()
    assert dict(os.environ) == original
    forwarded = probe.check.call_args.args[0]
    assert forwarded[NONCE_VARIABLE] == sentinels.nonce
    assert forwarded[SENTINEL_VARIABLE] == sentinels.host
