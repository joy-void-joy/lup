"""The persisted question mailbox every answer door writes through.

A resolver run holds its state lock for its entire life, so nothing outside
that process can take it. The mailbox is therefore lock-free by
construction: one file per question, written with an atomic rename, in
directories the state machine never prunes.

Three directories rather than two. Doors write ``offers/``, which is
correctable — a mistyped free-text answer can be replaced right up until it
counts, and an offer may arrive before its question exists, which is what
lets a flag answer a question the run has not asked yet. Exactly one writer
promotes offers into ``answers/``, taking the earliest valid one, so "first
answer wins" is a deterministic decision rather than a race between whoever
reached the filesystem first.
"""

import asyncio
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.resolver.models import FROZEN, MaterialQuestion, QuestionAnswer

QUESTION_DIR = "questions"
OFFER_DIR = "offers"
ANSWER_DIR = "answers"
PARK_FILE = "park.request"
ANSWER_POLL_SECONDS = 0.25


class MailboxConflictError(RuntimeError):
    """A write contradicted a record the mailbox already holds."""


class MailboxCorruptionError(RuntimeError):
    """A mailbox file could not be read as the record it should hold."""


class AnswerDoor(StrEnum):
    """Which surface an answer came through."""

    FLAG = "flag"
    PAGE = "page"
    CONSOLE = "console"


class PendingQuestion(BaseModel):
    """One question a run is waiting on, written once by whoever asked."""

    model_config = FROZEN

    run_id: str
    question: MaterialQuestion
    asked_by: str
    asked_at: datetime


class AnswerOffer(BaseModel):
    """One door's proposed answer, correctable until it is promoted."""

    model_config = FROZEN

    run_id: str
    question_id: str
    value: str
    door: AnswerDoor
    offered_at: datetime


class RecordedAnswer(BaseModel):
    """The promoted answer to one question. Written once, never revised."""

    model_config = FROZEN

    run_id: str
    answer: QuestionAnswer
    door: AnswerDoor
    answered_at: datetime


class ParkRequest(BaseModel):
    """A door asking every open wait in this run to give up now."""

    model_config = FROZEN

    run_id: str
    reason: str


class MailboxWait(BaseModel):
    """How one wait ended. ``reason`` is empty only on a complete answer."""

    model_config = ConfigDict(frozen=True)

    answered: list[RecordedAnswer]
    unanswered: list[str]
    reason: str = ""


type MailboxRecord = PendingQuestion | AnswerOffer | RecordedAnswer | ParkRequest


def utc_now() -> datetime:
    return datetime.now(UTC)


class QuestionMailbox:
    """File-backed question and answer exchange for one resolver run."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, directory: str, question_id: str) -> Path:
        return self.root / directory / f"{question_id}.json"

    def write_atomic(self, path: Path, payload: MailboxRecord) -> None:
        """Publish one record so no reader can observe it half-written."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            payload.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        temporary.replace(path)  # lup: ignore[string-replace] — atomic Path rename

    def read_records[T: BaseModel](self, directory: str, model: type[T]) -> list[T]:
        source = self.root / directory
        if not source.is_dir():
            return []
        records: list[T] = []
        for path in sorted(source.glob("*.json")):
            try:
                records.append(model.model_validate_json(path.read_text("utf-8")))
            except ValueError as error:
                raise MailboxCorruptionError(
                    f"{path} is not a {model.__name__}"
                ) from error
        return records

    def queue(self, pending: PendingQuestion) -> None:
        """Record a question once; re-asking the same question is a no-op."""
        path = self.path_for(QUESTION_DIR, pending.question.id)
        if path.exists():
            existing = PendingQuestion.model_validate_json(path.read_text("utf-8"))
            if existing.question != pending.question:
                raise MailboxConflictError(
                    f"question {pending.question.id!r} is already asked differently"
                )
            return
        self.write_atomic(path, pending)

    def offer(self, offer: AnswerOffer) -> None:
        """Propose an answer, replacing any earlier proposal for that question."""
        self.write_atomic(self.path_for(OFFER_DIR, offer.question_id), offer)

    def record(self, answer: RecordedAnswer) -> bool:
        """Promote one answer, or report that another door already won."""
        path = self.path_for(ANSWER_DIR, answer.answer.question_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(answer.model_dump_json(indent=2) + "\n")
        except FileExistsError:
            return False
        return True

    def questions(self) -> list[PendingQuestion]:
        return self.read_records(QUESTION_DIR, PendingQuestion)

    def offers(self) -> list[AnswerOffer]:
        return self.read_records(OFFER_DIR, AnswerOffer)

    def answers(self) -> list[RecordedAnswer]:
        return self.read_records(ANSWER_DIR, RecordedAnswer)

    def answered_ids(self) -> list[str]:
        return [record.answer.question_id for record in self.answers()]

    def park(self, request: ParkRequest) -> None:
        self.write_atomic(self.root / PARK_FILE, request)

    def parked(self) -> ParkRequest | None:
        path = self.root / PARK_FILE
        if not path.exists():
            return None
        try:
            return ParkRequest.model_validate_json(path.read_text("utf-8"))
        except ValueError as error:
            raise MailboxCorruptionError(f"{path} is not a ParkRequest") from error

    def clear_park(self) -> None:
        """Drop a stale park marker so a resumed run can wait again."""
        (self.root / PARK_FILE).unlink(missing_ok=True)


async def wait_for_answers(
    mailbox: QuestionMailbox,
    question_ids: list[str],
    *,
    wait_seconds: float,
    poll_interval_seconds: float = ANSWER_POLL_SECONDS,
    wake: asyncio.Event | None = None,
) -> MailboxWait:
    """Wait for every named answer, a park request, or the deadline.

    The tick bounds how late an out-of-process answer can be noticed; the
    optional event lets an in-process promoter deliver one with no delay at
    all. Both surfaces observe the same promotion, so there is one mechanism
    rather than a fast path and a slow path that can disagree.
    """
    wanted = list(dict.fromkeys(question_ids))
    deadline = time.monotonic() + wait_seconds
    while True:
        recorded = {record.answer.question_id: record for record in mailbox.answers()}
        answered = [recorded[name] for name in wanted if name in recorded]
        outstanding = [name for name in wanted if name not in recorded]
        if not outstanding:
            return MailboxWait(answered=answered, unanswered=[])
        request = mailbox.parked()
        if request is not None:
            return MailboxWait(
                answered=answered, unanswered=outstanding, reason=request.reason
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return MailboxWait(
                answered=answered,
                unanswered=outstanding,
                reason="no answer arrived before the wait elapsed",
            )
        if wake is None:
            await asyncio.sleep(min(poll_interval_seconds, remaining))
            continue
        try:
            async with asyncio.timeout(min(poll_interval_seconds, remaining)):
                await wake.wait()
        except TimeoutError:
            continue
        wake.clear()
