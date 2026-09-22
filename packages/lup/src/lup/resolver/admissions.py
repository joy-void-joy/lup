"""Durable proposals a running resolver plans at its next scheduling boundary."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from lup.channels.models import publish_atomic, utc_now
from lup.resolver.models import AdmissionRequest, ConcernAdmission


class AdmissionStatus(StrEnum):
    QUEUED = "queued"
    PLANNED = "planned"
    APPLIED = "applied"
    REJECTED = "rejected"


class AdmissionReceipt(BaseModel, frozen=True):
    id: str
    run_id: str
    request: AdmissionRequest
    requested_at: datetime = Field(default_factory=utc_now)
    status: AdmissionStatus = AdmissionStatus.QUEUED
    result: ConcernAdmission | None = None
    error: str = ""


class ResolverAdmissionsPending(Exception):
    """A worker boundary must revisit gates for evidence waiting in the mailbox."""


class AdmissionMailbox:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.root = run_dir / "admissions"

    def submit(self, request: AdmissionRequest) -> AdmissionReceipt:
        receipt = AdmissionReceipt(
            id=uuid4().hex, run_id=self.run_dir.name, request=request
        )
        self.write(receipt)
        return receipt

    def write(self, receipt: AdmissionReceipt) -> None:
        if Path(receipt.id).name != receipt.id or receipt.run_id != self.run_dir.name:
            raise ValueError("an admission receipt must belong to this run")
        publish_atomic(self.root / f"{receipt.id}.json", receipt)

    def receipts(self) -> list[AdmissionReceipt]:
        return sorted(
            [
                AdmissionReceipt.model_validate_json(path.read_text(encoding="utf-8"))
                for path in self.root.glob("*.json")
            ],
            key=lambda item: (item.requested_at, item.id),
        )

    def pending(self) -> list[AdmissionReceipt]:
        return [
            item
            for item in self.receipts()
            if item.status in {AdmissionStatus.QUEUED, AdmissionStatus.PLANNED}
        ]
