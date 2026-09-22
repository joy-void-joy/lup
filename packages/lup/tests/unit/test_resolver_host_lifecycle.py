"""A sleeping driver remains the owner, and a stopped driver leaves no live wait."""

import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest

from lup.providers.claude.runtime import may_be_a_rotation, needs_a_person
from lup.resolver.contracts import ResolverEnvironmentFault
from lup.resolver.lifecycle import HostWait, HostWaitStore, drive_with_host_retries
from lup.resolver.state import ResolverStateRepository, StateTransitionError
from lup.resolver.status import run_status


@pytest.mark.parametrize("cancel", [False, True])
async def test_host_wait_keeps_the_run_lease_and_reports_its_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    repository = ResolverStateRepository(tmp_path, "sleeping")
    entered = asyncio.Event()
    released = asyncio.Event()
    calls: list[bool] = []

    async def sleep(_seconds: float) -> None:
        entered.set()
        await released.wait()

    async def drive() -> None:
        calls.append(repository.held())
        if len(calls) == 1:
            raise ResolverEnvironmentFault("host unavailable", [])

    monkeypatch.setattr(asyncio, "sleep", sleep)
    task = asyncio.create_task(
        drive_with_host_retries(
            drive,
            repository,
            retries=2,
            retry_delay=lambda _: 60,
            auth_probe_delay=1,
            needs_a_person=needs_a_person,
            may_be_a_rotation=may_be_a_rotation,
            announce=lambda _: None,
        )
    )
    await entered.wait()
    status = run_status(repository, "sleeping")
    assert status.held and status.host_wait is not None
    assert status.host_wait.cause == "host unavailable"
    assert "running, host retry until" in status.verdict()
    assert not status.settled(running_yet=True)
    with (
        pytest.raises(StateTransitionError, match="already active"),
        repository.exclusive(),
    ):
        pytest.fail(
            "a waiting driver must exclude duplicate drivers and binding recovery"
        )
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        released.set()
        await task
    assert all(calls)
    assert not repository.held()
    assert HostWaitStore(repository.root).read() is None
    assert run_status(repository, "sleeping").host_wait is None


async def test_allowance_exhaustion_stops_for_an_account_choice(tmp_path: Path) -> None:
    repository = ResolverStateRepository(tmp_path, "exhausted")
    calls: list[bool] = []
    announce = Mock()

    async def drive() -> None:
        calls.append(True)
        raise ResolverEnvironmentFault(
            "Claude account allowance exhausted until tomorrow", []
        )

    with pytest.raises(ResolverEnvironmentFault, match="allowance exhausted"):
        await drive_with_host_retries(
            drive,
            repository,
            retries=20,
            retry_delay=lambda _: 60,
            auth_probe_delay=1,
            needs_a_person=needs_a_person,
            may_be_a_rotation=may_be_a_rotation,
            announce=announce,
        )
    assert calls == [True]
    announce.assert_not_called()
    assert not repository.held()


@pytest.mark.parametrize("retries,expected", [(0, 1), (1, 2), (5, 2)])
async def test_rotation_probe_never_silently_completes_a_refused_run(
    tmp_path: Path, retries: int, expected: int
) -> None:
    repository = ResolverStateRepository(tmp_path, "credential")
    calls: list[bool] = []

    async def drive() -> None:
        calls.append(True)
        raise ResolverEnvironmentFault("OAuth access token has been revoked", [])

    with pytest.raises(ResolverEnvironmentFault, match="revoked"):
        await drive_with_host_retries(
            drive,
            repository,
            retries=retries,
            retry_delay=lambda _: 0,
            auth_probe_delay=0,
            needs_a_person=needs_a_person,
            may_be_a_rotation=may_be_a_rotation,
            announce=lambda _: None,
        )
    assert len(calls) == expected
    assert not repository.held()


def test_stale_wait_evidence_cannot_make_a_dead_driver_look_live(
    tmp_path: Path,
) -> None:
    from lup.channels.models import utc_now

    repository = ResolverStateRepository(tmp_path, "dead")
    HostWaitStore(repository.root).publish(
        HostWait(cause="old refusal", retry_at=utc_now())
    )
    status = run_status(repository, "dead")
    assert not status.held
    assert status.host_wait is None
    assert status.verdict() == "stopped before initialization"
