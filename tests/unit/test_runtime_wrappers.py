"""Whole-turn timeout, recovery, correction, persistence, and queue tests."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from lup.runtime.composition import (
    AcceptedTurn,
    CompletedTurn,
    CompleteTurn,
    ComposedSession,
)
from lup.runtime.errors import (
    BudgetExceededError,
    ProviderTurnError,
    TurnFailure,
    TurnTimeoutError,
)
from lup.runtime.models import (
    SessionId,
    TurnIdentifiers,
    TurnId,
    TurnInput,
    turn_request,
)
from lup.runtime.wrappers import (
    BudgetConfig,
    CorrectionConfig,
    DecoratingSession,
    DisplayConfig,
    DisplayRecord,
    PersistenceConfig,
    RecoveryConfig,
    SerializedSession,
    TimeoutConfig,
    TraceRecord,
    TracingConfig,
    UsageConfig,
    UsageRecord,
)
from lup.types import Usage
from tests.unit.test_capability_runtime import RecordingBinder, RecordingInterrupt


class WrappedOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


def accepted(
    sequence: int,
    complete: CompleteTurn,
    interrupt: RecordingInterrupt | None = None,
) -> AcceptedTurn:
    return AcceptedTurn(
        identifiers=TurnIdentifiers(
            session=SessionId(value="wrapped"),
            turn=TurnId(value=f"turn-{sequence}"),
        ),
        complete=complete,
        interrupt=interrupt,
    )


@pytest.mark.asyncio
async def test_timeout_covers_terminal_completion_and_interrupts() -> None:
    binder = RecordingBinder()
    interrupt = RecordingInterrupt()

    async def start(_text: str) -> AcceptedTurn:
        async def complete() -> CompletedTurn:
            await asyncio.sleep(1)
            return CompletedTurn()

        return accepted(1, complete, interrupt)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=TimeoutConfig(seconds=0.001),
        budget=None,
        recovery=None,
        correction=None,
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="slow")))

    with pytest.raises(TurnTimeoutError):
        await handle.turn.result()
    assert interrupt.calls == 1


@pytest.mark.asyncio
async def test_timeout_interrupts_the_current_recovery_attempt() -> None:
    binder = RecordingBinder()
    first_interrupt = RecordingInterrupt()
    second_interrupt = RecordingInterrupt()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1
        turn_sequence = sequence

        async def complete() -> CompletedTurn:
            if turn_sequence == 1:
                raise ProviderTurnError(TurnFailure(message="retry"))
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        interrupt = first_interrupt if turn_sequence == 1 else second_interrupt
        return accepted(turn_sequence, complete, interrupt)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=TimeoutConfig(seconds=0.01),
        budget=None,
        recovery=RecoveryConfig(retries=1),
        correction=None,
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="retry then wait")))

    with pytest.raises(TurnTimeoutError):
        await handle.turn.result()
    assert first_interrupt.calls == 0
    assert second_interrupt.calls == 1


@pytest.mark.asyncio
async def test_recovery_accumulates_failed_attempt_usage() -> None:
    binder = RecordingBinder()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1

        async def complete() -> CompletedTurn:
            if sequence == 1:
                raise RuntimeError("transient")
            return CompletedTurn(
                usage=Usage(input_tokens=3),
                duration=timedelta(milliseconds=2),
            )

        return accepted(sequence, complete)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=None,
        recovery=RecoveryConfig(retries=1),
        correction=None,
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="retry")))
    result = await handle.turn.result()

    assert sequence == 2
    assert result.usage.input_tokens == 3


@pytest.mark.asyncio
async def test_correction_rebinds_a_fresh_store_and_aggregates_usage() -> None:
    binder = RecordingBinder()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1
        turn_sequence = sequence

        async def complete() -> CompletedTurn:
            if turn_sequence == 2:
                assert binder.current is not None
                binder.current.store.write(WrappedOutput(value=7))
            return CompletedTurn(
                usage=Usage(input_tokens=turn_sequence),
                duration=timedelta(milliseconds=turn_sequence),
            )

        return accepted(turn_sequence, complete)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=None,
        recovery=None,
        correction=CorrectionConfig(cycles=1),
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="typed"), WrappedOutput))
    result = await handle.turn.result()

    assert result.output == WrappedOutput(value=7)
    assert result.usage.input_tokens == 3
    assert len(binder.stores) == len(dict.fromkeys(binder.stores)) == 2


@pytest.mark.asyncio
async def test_recovery_and_correction_share_one_logical_retry_loop() -> None:
    binder = RecordingBinder()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1
        turn_sequence = sequence

        async def complete() -> CompletedTurn:
            evidence = TurnFailure(
                message=f"provider failure {turn_sequence}",
                usage=Usage(input_tokens=turn_sequence),
                duration=timedelta(milliseconds=turn_sequence),
            )
            if turn_sequence in {1, 3}:
                raise ProviderTurnError(evidence)
            if turn_sequence == 4:
                assert binder.current is not None
                binder.current.store.write(WrappedOutput(value=9))
            return CompletedTurn(
                usage=Usage(input_tokens=turn_sequence),
                duration=timedelta(milliseconds=turn_sequence),
            )

        return accepted(turn_sequence, complete)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=None,
        recovery=RecoveryConfig(retries=2),
        correction=CorrectionConfig(cycles=1),
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="typed"), WrappedOutput))
    result = await handle.turn.result()

    assert sequence == 4
    assert result.output == WrappedOutput(value=9)
    assert result.usage.input_tokens == 10
    assert len(binder.stores) == len(dict.fromkeys(binder.stores)) == 4


@pytest.mark.asyncio
async def test_serialized_session_queues_until_prior_result_finishes() -> None:
    binder = RecordingBinder()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1

        async def complete() -> CompletedTurn:
            return CompletedTurn()

        return accepted(sequence, complete)

    session = SerializedSession(ComposedSession(start, binder))
    first = await session.start(turn_request(TurnInput(text="first")))
    second_task = asyncio.create_task(
        session.start(turn_request(TurnInput(text="second")))
    )
    await asyncio.sleep(0)
    assert not second_task.done()

    await first.turn.result()
    second = await second_task
    await second.turn.result()
    assert sequence == 2


@pytest.mark.asyncio
async def test_consumed_serialized_turn_cannot_release_a_new_owner() -> None:
    binder = RecordingBinder()
    sequence = 0

    async def start(_text: str) -> AcceptedTurn:
        nonlocal sequence
        sequence += 1

        async def complete() -> CompletedTurn:
            return CompletedTurn()

        return accepted(sequence, complete)

    session = SerializedSession(ComposedSession(start, binder))
    first = await session.start(turn_request(TurnInput(text="first")))
    await first.turn.result()
    second = await session.start(turn_request(TurnInput(text="second")))

    with pytest.raises(RuntimeError):
        await first.turn.result()
    assert session.lock.locked()

    await second.turn.result()


@pytest.mark.asyncio
async def test_budget_exhaustion_preserves_completed_evidence() -> None:
    binder = RecordingBinder()

    async def start(_text: str) -> AcceptedTurn:
        async def complete() -> CompletedTurn:
            return CompletedTurn(
                usage=Usage(input_tokens=20, output_tokens=10),
                duration=timedelta(milliseconds=7),
            )

        return accepted(1, complete)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=BudgetConfig(
            maximum_usd=1.0,
            usage_cost=lambda usage: usage.input_tokens / 10,
        ),
        recovery=None,
        correction=None,
        persistence=None,
    )
    handle = await session.start(turn_request(TurnInput(text="expensive")))

    with pytest.raises(BudgetExceededError) as raised:
        await handle.turn.result()
    assert raised.value.failure.usage.input_tokens == 20
    assert raised.value.failure.duration == timedelta(milliseconds=7)


@pytest.mark.asyncio
async def test_cancelled_serialized_acceptance_releases_queue_lock() -> None:
    binder = RecordingBinder()
    entered = asyncio.Event()

    async def start(_text: str) -> AcceptedTurn:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    session = SerializedSession(ComposedSession(start, binder))
    task = asyncio.create_task(session.start(turn_request(TurnInput(text="cancel"))))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not session.lock.locked()


@pytest.mark.asyncio
async def test_successful_result_is_persisted_atomically(tmp_path: Path) -> None:
    binder = RecordingBinder()

    async def start(_text: str) -> AcceptedTurn:
        async def complete() -> CompletedTurn:
            return CompletedTurn()

        return accepted(1, complete)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=None,
        recovery=None,
        correction=None,
        persistence=PersistenceConfig(directory=tmp_path),
    )
    handle = await session.start(turn_request(TurnInput(text="persist")))
    await handle.turn.result()

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".json"
    assert not files[0].name.startswith(".")


@pytest.mark.asyncio
async def test_trace_usage_and_display_observe_one_complete_logical_turn() -> None:
    binder = RecordingBinder()
    traces: list[TraceRecord] = []
    usages: list[UsageRecord] = []
    displays: list[DisplayRecord] = []

    async def start(_text: str) -> AcceptedTurn:
        async def complete() -> CompletedTurn:
            from lup.runtime.models import TurnMessage, TurnTextBlock

            block = TurnTextBlock(text="done")
            return CompletedTurn(
                messages=[TurnMessage(role="assistant", blocks=[block])],
                blocks=[block],
                usage=Usage(input_tokens=4),
                duration=timedelta(milliseconds=3),
            )

        return accepted(1, complete)

    async def trace(record: TraceRecord) -> None:
        traces.append(record)

    async def usage(record: UsageRecord) -> None:
        usages.append(record)

    async def display(record: DisplayRecord) -> None:
        displays.append(record)

    session = DecoratingSession(
        ComposedSession(start, binder),
        timeout=None,
        budget=None,
        recovery=None,
        correction=None,
        persistence=None,
        tracing=TracingConfig(sink=trace),
        usage=UsageConfig(sink=usage),
        display=DisplayConfig(sink=display),
    )
    handle = await session.start(turn_request(TurnInput(text="observe")))
    result = await handle.turn.result()

    assert result.usage.input_tokens == 4
    assert [record.succeeded for record in traces] == [True]
    assert [record.usage.input_tokens for record in usages] == [4]
    displayed = displays[0].blocks[0]
    from lup.runtime.models import TurnTextBlock

    assert isinstance(displayed, TurnTextBlock)
    assert displayed.text == "done"
