"""Server-sent transition events, derived by watching a run's own files.

Nothing publishes into this module. The resolver records every transition to
``state.json`` and every answer to the mailbox, so a connected page is a
reader like any other door: it re-projects the run on a fixed tick and emits
one event per observed difference. That is what lets a page follow a run no
process in this program is attached to, and why there is no hub, no queue,
and no thread to hand events across.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lup.resolver.models import ConcernProgress, ResolvePhase
from lup_template.devtools.supervisor.projection import (
    PendingQuestionView,
    ReviewView,
    RunStatus,
    SupervisorState,
)

HEARTBEAT_SECONDS = 15.0
RETRY_MILLISECONDS = 3000
WATCH_INTERVAL_SECONDS = 0.5


class PhaseEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["phase"] = "phase"
    phase: ResolvePhase


class ConcernEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["concern"] = "concern"
    progress: ConcernProgress


class QuestionsEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["questions"] = "questions"
    pending: list[PendingQuestionView]


class ReviewEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["review"] = "review"
    review: ReviewView


class StatusEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["status"] = "status"
    status: RunStatus
    detail: str = ""


type SupervisorEvent = (
    PhaseEvent | ConcernEvent | QuestionsEvent | ReviewEvent | StatusEvent
)
type StateReader = Callable[[], SupervisorState | None]


def run_events(
    previous: SupervisorState | None, current: SupervisorState
) -> list[SupervisorEvent]:
    """Every event that reports the difference between two projections.

    The first observation emits nothing: a page hydrates from ``/api/state``
    before it connects, so replaying the whole run as transitions would only
    restate what it already drew.
    """
    if previous is None:
        return []
    events: list[SupervisorEvent] = []  # lup: ignore[empty-collection]
    if previous.phase != current.phase:
        events.append(PhaseEvent(phase=current.phase))
    before = {concern.id: concern for concern in previous.concerns}
    for concern in current.concerns:
        prior = before[concern.id] if concern.id in before else None
        if prior is not None and prior.status == concern.status:
            if prior.reason == concern.reason:
                continue
        events.append(
            ConcernEvent(
                progress=ConcernProgress(
                    concern_id=concern.id,
                    status=concern.status,
                    reason=concern.reason,
                )
            )
        )
    if previous.pending != current.pending:
        events.append(QuestionsEvent(pending=current.pending))
    if previous.review != current.review and current.review is not None:
        events.append(ReviewEvent(review=current.review))
    if previous.status != current.status:
        events.append(StatusEvent(status=current.status))
    return events


async def stream(
    read: StateReader,
    interval: float = WATCH_INTERVAL_SECONDS,
    heartbeat: float = HEARTBEAT_SECONDS,
) -> AsyncGenerator[str, None]:
    """Frame observed differences as an SSE body until the client leaves.

    The tick drives both the events and the keep-alive, so no await is ever
    cancelled to deliver a heartbeat — an async generator interrupted that
    way would be closed rather than resumed, and the stream would go silent
    exactly when the run went quiet.
    """
    yield f"retry: {RETRY_MILLISECONDS}\n\n"
    previous: SupervisorState | None = None
    silent = 0.0
    while True:
        current = read()
        events = run_events(previous, current) if current is not None else []
        if current is not None:
            previous = current
        for event in events:
            yield f"data: {event.model_dump_json()}\n\n"
        silent = 0.0 if events else silent + interval
        if silent >= heartbeat:
            yield ": keep-alive\n\n"
            silent = 0.0
        await asyncio.sleep(interval)
