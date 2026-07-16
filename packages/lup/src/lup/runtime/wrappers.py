"""Concrete runtime decorators with explicit whole-logical-turn boundaries."""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from lup.runtime.composition import is_output_model
from lup.runtime.contracts import (
    EventStream,
    Interrupt,
    Session,
    SessionFactory,
    Steer,
    Turn,
)
from lup.runtime.errors import (
    BudgetExceededError,
    ProviderTurnError,
    StructuredOutputError,
    TurnError,
    TurnFailure,
    TurnTimeoutError,
    ValidationAttempt,
)
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    TurnBlock,
    TurnHandle,
    TurnIdentifiers,
    TurnEvent,
    TurnInput,
    TurnMessage,
    TurnRequest,
    TurnResult,
)
from lup.types import Usage, UsageCost


class TimeoutConfig(BaseModel):
    """Deadline covering native acceptance through terminal completion."""

    model_config = ConfigDict(frozen=True)

    seconds: float = Field(gt=0)


class BudgetConfig(BaseModel):
    """Whole-logical-turn cost limit and independent usage estimator."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    maximum_usd: float = Field(ge=0)
    usage_cost: UsageCost


class RecoveryConfig(BaseModel):
    """Bounded provider-failure retries inside one logical turn."""

    model_config = ConfigDict(frozen=True)

    retries: int = Field(default=1, ge=0)


class CorrectionConfig(BaseModel):
    """Bounded missing-output correction cycles inside one logical turn."""

    model_config = ConfigDict(frozen=True)

    cycles: int = Field(default=2, ge=0)
    instruction: str = (
        "The previous response completed without a valid submit_output call. "
        "Submit a value matching the requested schema before completing."
    )


class PersistenceConfig(BaseModel):
    """Directory receiving one successful immutable result document per turn."""

    model_config = ConfigDict(frozen=True)

    directory: Path


class TraceRecord(BaseModel):
    """Terminal evidence emitted once for a complete logical turn."""

    model_config = ConfigDict(frozen=True)

    succeeded: bool
    identifiers: TurnIdentifiers | None = None
    failure: TurnFailure | None = None


class UsageRecord(BaseModel):
    """Portable usage observed after a successful logical turn."""

    model_config = ConfigDict(frozen=True)

    identifiers: TurnIdentifiers
    usage: Usage
    duration: timedelta


class DisplayRecord(BaseModel):
    """Completed replay data, deliberately distinct from live events."""

    model_config = ConfigDict(frozen=True)

    identifiers: TurnIdentifiers
    messages: list[TurnMessage]
    blocks: list[TurnBlock]


type TraceSink = Callable[[TraceRecord], Awaitable[None]]
type UsageSink = Callable[[UsageRecord], Awaitable[None]]
type DisplaySink = Callable[[DisplayRecord], Awaitable[None]]


class TracingConfig(BaseModel):
    """Terminal logical-turn trace callback."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    sink: TraceSink


class UsageConfig(BaseModel):
    """Successful logical-turn usage callback."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    sink: UsageSink


class DisplayConfig(BaseModel):
    """Successful completed-replay callback."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    sink: DisplaySink


class SwitchingInterrupt(Interrupt):
    """Delegate interruption to the currently active native retry attempt."""

    def __init__(self, current: Interrupt) -> None:
        self.current: Interrupt | None = current

    async def interrupt(self) -> None:
        current = self.current
        if current is not None:
            await current.interrupt()


class SwitchingSteer(Steer):
    """Delegate steering to the currently active native retry attempt."""

    def __init__(self, current: Steer) -> None:
        self.current: Steer | None = current

    async def steer(self, input: TurnInput) -> None:
        current = self.current
        if current is None:
            raise RuntimeError("the logical turn has no active steer capability")
        await current.steer(input)


class SwitchingEventStream(EventStream):
    """Join successive native retry streams into one logical live stream."""

    def __init__(self, current: EventStream) -> None:
        self.current: EventStream | None = current
        self.version = 0
        self.changed = asyncio.Event()
        self.closed = False
        self.consumed = False

    def switch(self, current: EventStream | None) -> None:
        self.current = current
        self.version += 1
        self.changed.set()

    def close(self) -> None:
        self.closed = True
        self.changed.set()

    async def iterate(self) -> AsyncIterator[TurnEvent]:
        if self.consumed:
            raise RuntimeError("logical live event stream can only be consumed once")
        self.consumed = True
        observed = -1
        while True:
            current = self.current
            version = self.version
            if current is not None and version != observed:
                observed = version
                async for event in current.events():
                    yield event
                continue
            if self.closed:
                return
            self.changed.clear()
            if self.closed or self.version != version:
                continue
            await self.changed.wait()

    def events(self) -> AsyncIterator[TurnEvent]:
        return self.iterate()


class TimeoutTurn[T: BaseModel | None](Turn[T]):
    """Apply the acceptance-time deadline to the remaining result operation."""

    def __init__(
        self,
        inner: Turn[T],
        config: TimeoutConfig,
        deadline: float,
        interrupt: Interrupt | None,
    ) -> None:
        self.inner = inner
        self.config = config
        self.deadline = deadline
        self.interrupt = interrupt

    async def result(self) -> TurnResult[T]:
        try:
            async with asyncio.timeout_at(self.deadline):
                return await self.inner.result()
        except TimeoutError as error:
            message = f"turn exceeded {self.config.seconds:g} seconds"
            if self.interrupt is not None:
                try:
                    await self.interrupt.interrupt()
                except Exception as interrupt_error:
                    message += f"; interruption also failed: {interrupt_error}"
            raise TurnTimeoutError(
                TurnFailure(
                    message=message,
                    duration=timedelta(seconds=self.config.seconds),
                )
            ) from error


class BudgetTurn[T: BaseModel | None](Turn[T]):
    """Reject a completed result whose complete accumulated usage is over budget."""

    def __init__(self, inner: Turn[T], config: BudgetConfig) -> None:
        self.inner = inner
        self.config = config

    async def result(self) -> TurnResult[T]:
        result = await self.inner.result()
        actual = self.config.usage_cost(result.usage)
        if actual > self.config.maximum_usd:
            raise BudgetExceededError(
                TurnFailure(
                    message=(
                        f"turn cost ${actual:.6f} exceeded budget "
                        f"${self.config.maximum_usd:.6f}"
                    ),
                    blocks=result.blocks,
                    usage=result.usage,
                    duration=result.duration,
                    identifiers=result.identifiers,
                )
            )
        return result


class ResilientTurn[T: BaseModel | None](Turn[T]):
    """Coordinate provider retries and output corrections across one logical turn."""

    def __init__(
        self,
        inner: Turn[T],
        session: Session,
        request: TurnRequest[T],
        recovery: RecoveryConfig | None,
        correction: CorrectionConfig | None,
        interrupt: SwitchingInterrupt | None,
        events: SwitchingEventStream | None,
        steer: SwitchingSteer | None,
    ) -> None:
        self.inner = inner
        self.session = session
        self.request = request
        self.recovery = recovery
        self.correction = correction
        self.interrupt = interrupt
        self.events = events
        self.steer = steer

    async def result(self) -> TurnResult[T]:
        current = self.inner
        current_request = self.request
        failures: list[TurnFailure] = []
        provider_attempts = 0
        correction_cycles = 0
        try:
            while True:
                try:
                    result = await current.result()
                    return accumulated_result(result, failures)
                except ProviderTurnError as error:
                    failures.append(error.failure)
                    retries = self.recovery.retries if self.recovery is not None else 0
                    if provider_attempts >= retries:
                        raise accumulated_error(error, failures) from error
                    provider_attempts += 1
                except StructuredOutputError as error:
                    failures.append(error.failure)
                    cycles = (
                        self.correction.cycles if self.correction is not None else 0
                    )
                    if correction_cycles >= cycles:
                        raise StructuredOutputError(
                            combined_failure(error.failure, failures)
                        ) from error
                    correction_cycles += 1
                    correction = self.correction
                    if correction is None:
                        raise RuntimeError("correction cycle has no configuration")
                    current_request = self.request.model_copy(
                        update={
                            "input": self.request.input.model_copy(
                                update={
                                    "text": (
                                        f"{self.request.input.text}\n\n"
                                        "Correction required: "
                                        f"{correction.instruction}"
                                    )
                                }
                            )
                        }
                    )
                try:
                    handle = await self.session.start(current_request)
                except TurnError:
                    raise
                except Exception as error:
                    failure = combined_failure(
                        TurnFailure(message=str(error)), failures
                    )
                    raise ProviderTurnError(failure) from error
                if self.interrupt is not None:
                    self.interrupt.current = handle.interrupt
                if self.events is not None:
                    self.events.switch(handle.events)
                if self.steer is not None:
                    self.steer.current = handle.steer
                current = handle.turn
        finally:
            if self.events is not None:
                self.events.close()


class SerializedTurn[T: BaseModel | None](Turn[T]):
    """Release one queued-session slot after any terminal result outcome."""

    def __init__(self, inner: Turn[T], lock: asyncio.Lock) -> None:
        self.inner = inner
        self.lock = lock
        self.released = False

    async def result(self) -> TurnResult[T]:
        try:
            return await self.inner.result()
        finally:
            if not self.released and self.lock.locked():
                self.released = True
                self.lock.release()


class PersistingTurn[T: BaseModel | None](Turn[T]):
    """Atomically persist only successful typed turn results."""

    def __init__(self, inner: Turn[T], config: PersistenceConfig) -> None:
        self.inner = inner
        self.config = config

    async def result(self) -> TurnResult[T]:
        result = await self.inner.result()
        try:
            self.config.directory.mkdir(parents=True, exist_ok=True)
            identity = (
                f"{result.identifiers.session.value}\0{result.identifiers.turn.value}"
            )
            name = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24] + ".json"
            path = self.config.directory / name
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(
                result.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename
        except Exception as error:
            raise ProviderTurnError(failure_from_result(result, str(error))) from error
        return result


class TracingTurn[T: BaseModel | None](Turn[T]):
    """Trace exactly one terminal outcome after all bounded cycles finish."""

    def __init__(self, inner: Turn[T], config: TracingConfig) -> None:
        self.inner = inner
        self.config = config

    async def result(self) -> TurnResult[T]:
        try:
            result = await self.inner.result()
        except TurnError as error:
            try:
                await self.config.sink(
                    TraceRecord(
                        succeeded=False,
                        identifiers=error.failure.identifiers,
                        failure=error.failure,
                    )
                )
            except Exception as sink_error:
                error.add_note(f"trace sink also failed: {sink_error}")
            raise
        try:
            await self.config.sink(
                TraceRecord(succeeded=True, identifiers=result.identifiers)
            )
        except Exception as error:
            raise ProviderTurnError(failure_from_result(result, str(error))) from error
        return result


class UsageTurn[T: BaseModel | None](Turn[T]):
    """Report normalized usage after the whole logical turn succeeds."""

    def __init__(self, inner: Turn[T], config: UsageConfig) -> None:
        self.inner = inner
        self.config = config

    async def result(self) -> TurnResult[T]:
        try:
            result = await self.inner.result()
        except TurnError as error:
            failure = error.failure
            if failure.identifiers is not None:
                try:
                    await self.config.sink(
                        UsageRecord(
                            identifiers=failure.identifiers,
                            usage=failure.usage,
                            duration=failure.duration,
                        )
                    )
                except Exception as sink_error:
                    error.add_note(f"usage sink also failed: {sink_error}")
            raise
        try:
            await self.config.sink(
                UsageRecord(
                    identifiers=result.identifiers,
                    usage=result.usage,
                    duration=result.duration,
                )
            )
        except Exception as error:
            raise ProviderTurnError(failure_from_result(result, str(error))) from error
        return result


class DisplayTurn[T: BaseModel | None](Turn[T]):
    """Display completed replay without pretending it is a live stream."""

    def __init__(self, inner: Turn[T], config: DisplayConfig) -> None:
        self.inner = inner
        self.config = config

    async def result(self) -> TurnResult[T]:
        result = await self.inner.result()
        try:
            await self.config.sink(
                DisplayRecord(
                    identifiers=result.identifiers,
                    messages=result.messages,
                    blocks=result.blocks,
                )
            )
        except Exception as error:
            raise ProviderTurnError(failure_from_result(result, str(error))) from error
        return result


class DecoratingSession(Session):
    """Decorate accepted turns in an explicit, documented order."""

    def __init__(
        self,
        inner: Session,
        timeout: TimeoutConfig | None,
        budget: BudgetConfig | None,
        recovery: RecoveryConfig | None,
        correction: CorrectionConfig | None,
        persistence: PersistenceConfig | None,
        tracing: TracingConfig | None = None,
        usage: UsageConfig | None = None,
        display: DisplayConfig | None = None,
    ) -> None:
        self.inner = inner
        self.timeout = timeout
        self.budget = budget
        self.recovery = recovery
        self.correction = correction
        self.persistence = persistence
        self.tracing = tracing
        self.usage = usage
        self.display = display

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        deadline: float | None = None
        if self.timeout is None:
            handle = await self.inner.start(request)
        else:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout.seconds
            try:
                async with asyncio.timeout_at(deadline):
                    handle = await self.inner.start(request)
            except TimeoutError as error:
                raise TurnTimeoutError(
                    TurnFailure(
                        message=(
                            f"turn acceptance exceeded {self.timeout.seconds:g} seconds"
                        ),
                        duration=timedelta(seconds=self.timeout.seconds),
                    )
                ) from error
        turn: Turn[T] = handle.turn
        correction = self.correction if is_output_model(request.output_type) else None
        logical_interrupt = (
            SwitchingInterrupt(handle.interrupt)
            if handle.interrupt is not None
            else None
        )
        resilient = self.recovery is not None or correction is not None
        logical_events = (
            SwitchingEventStream(handle.events)
            if resilient and handle.events is not None
            else None
        )
        logical_steer = (
            SwitchingSteer(handle.steer)
            if resilient and handle.steer is not None
            else None
        )
        if resilient:
            turn = ResilientTurn(
                turn,
                self.inner,
                request,
                self.recovery,
                correction,
                logical_interrupt,
                logical_events,
                logical_steer,
            )
        if self.timeout is not None and deadline is not None:
            turn = TimeoutTurn(
                turn,
                self.timeout,
                deadline,
                logical_interrupt or handle.interrupt,
            )
        if self.budget is not None:
            turn = BudgetTurn(turn, self.budget)
        if self.persistence is not None:
            turn = PersistingTurn(turn, self.persistence)
        if self.display is not None:
            turn = DisplayTurn(turn, self.display)
        if self.usage is not None:
            turn = UsageTurn(turn, self.usage)
        if self.tracing is not None:
            turn = TracingTurn(turn, self.tracing)
        return TurnHandle[T](
            turn=turn,
            events=logical_events or handle.events,
            interrupt=logical_interrupt or handle.interrupt,
            steer=logical_steer or handle.steer,
        )


class SerializedSession(Session):
    """Queue independent turns only when callers explicitly request serialization."""

    def __init__(self, inner: Session) -> None:
        self.inner = inner
        self.lock = asyncio.Lock()

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        await self.lock.acquire()
        accepted = False
        try:
            handle = await self.inner.start(request)
            accepted = True
        finally:
            if not accepted and self.lock.locked():
                self.lock.release()
        return TurnHandle[T](
            turn=SerializedTurn(handle.turn, self.lock),
            events=handle.events,
            interrupt=handle.interrupt,
            steer=handle.steer,
        )


class DecoratingSessionFactory(SessionFactory):
    """Apply configured whole-turn decorators to every opened session."""

    def __init__(
        self,
        inner: SessionFactory,
        *,
        timeout: TimeoutConfig | None = None,
        budget: BudgetConfig | None = None,
        recovery: RecoveryConfig | None = None,
        correction: CorrectionConfig | None = None,
        persistence: PersistenceConfig | None = None,
        tracing: TracingConfig | None = None,
        usage: UsageConfig | None = None,
        display: DisplayConfig | None = None,
        serialized: bool = False,
    ) -> None:
        self.inner = inner
        self.timeout = timeout
        self.budget = budget
        self.recovery = recovery
        self.correction = correction
        self.persistence = persistence
        self.tracing = tracing
        self.usage = usage
        self.display = display
        self.serialized = serialized

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_decorated(resume)

    @asynccontextmanager
    async def open_decorated(
        self, resume: SessionId | None
    ) -> AsyncIterator[SessionHandle]:
        async with self.inner.open(resume) as handle:
            session: Session = DecoratingSession(
                handle.session,
                timeout=self.timeout,
                budget=self.budget,
                recovery=self.recovery,
                correction=self.correction,
                persistence=self.persistence,
                tracing=self.tracing,
                usage=self.usage,
                display=self.display,
            )
            if self.serialized:
                session = SerializedSession(session)
            yield SessionHandle(session=session, fork=handle.fork)


def failure_from_result[T: BaseModel | None](
    result: TurnResult[T], message: str
) -> TurnFailure:
    """Preserve completed evidence when a post-provider decorator fails."""
    return TurnFailure(
        message=message,
        blocks=result.blocks,
        usage=result.usage,
        duration=result.duration,
        identifiers=result.identifiers,
    )


def add_usage(left: Usage, right: Usage) -> Usage:
    """Add portable usage without conflating provider-specific cost estimation."""
    return Usage(
        cost_usd=(
            None
            if left.cost_usd is None and right.cost_usd is None
            else (left.cost_usd or 0) + (right.cost_usd or 0)
        ),
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cache_read_input_tokens=(
            left.cache_read_input_tokens + right.cache_read_input_tokens
        ),
        cache_creation_input_tokens=(
            left.cache_creation_input_tokens + right.cache_creation_input_tokens
        ),
    )


def accumulated_result[T: BaseModel | None](
    result: TurnResult[T], failures: list[TurnFailure]
) -> TurnResult[T]:
    """Fold partial failed-cycle evidence into one successful logical result."""
    blocks = [block for failure in failures for block in failure.blocks]
    usage = Usage()
    duration = timedelta()
    for failure in failures:
        usage = add_usage(usage, failure.usage)
        duration += failure.duration
    return result.model_copy(
        update={
            "blocks": [*blocks, *result.blocks],
            "usage": add_usage(usage, result.usage),
            "duration": duration + result.duration,
        }
    )


def combined_failure(last: TurnFailure, failures: list[TurnFailure]) -> TurnFailure:
    """Combine all bounded-attempt evidence into one terminal failure."""
    blocks = [block for failure in failures for block in failure.blocks]
    usage = Usage()
    duration = timedelta()
    history: list[ValidationAttempt] = []  # lup: ignore[empty-collection]
    for failure in failures:
        usage = add_usage(usage, failure.usage)
        duration += failure.duration
        history.extend(failure.validation_history)
    return last.model_copy(
        update={
            "blocks": blocks,
            "usage": usage,
            "duration": duration,
            "validation_history": history,
        }
    )


def accumulated_error(
    error: ProviderTurnError, failures: list[TurnFailure]
) -> ProviderTurnError:
    """Retain the provider error type while combining retry evidence."""
    return ProviderTurnError(combined_failure(error.failure, failures))
