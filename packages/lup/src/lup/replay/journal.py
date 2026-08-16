"""A durable journal of executed cells, and the divergence check on replay.

The mechanism is the same wherever it is used: record every executed cell in
order with whether it succeeded, and reconstruct state by re-running the
journal rather than by serializing objects. What differs between users is the
*contract* they attach to it.

An environment that claims determinism — a sealed, networkless kernel — is
saying a replay must reproduce the recorded outcomes, so a divergence there is
a defect in a claim. An environment that claims nothing — a sandbox with
network access and package installs — still gets a replayable record and a
divergence report, and there the divergence is not a defect, it *is* the
finding: it says the result depended on something outside the journal.

Both are replayable; only the first is certifiable. Keeping one mechanism with
two contracts is what makes that distinction legible, instead of leaving the
environment that cannot promise determinism with no durable record at all.
"""

import hashlib
from datetime import datetime

from pydantic import BaseModel, Field, TypeAdapter


def timestamp_now() -> str:
    """The wall clock a journal records itself as created at."""
    return datetime.now().astimezone().isoformat()


class JournalCell(BaseModel, frozen=True):
    """One executed unit, recorded so the sequence can be re-run."""

    kind: str = Field(
        default="code",
        description="What sort of cell this is, for environments with several",
    )
    source: str = Field(description="Exactly what was executed")
    ok: bool = Field(description="Whether it succeeded when it was first run")


class ReplayDivergence(BaseModel, frozen=True):
    """One cell whose replayed outcome differed from what was recorded."""

    index: int
    recorded_ok: bool
    replayed_ok: bool
    detail: str = ""


class ReplayReport(BaseModel, frozen=True):
    """The result of re-running one journal."""

    journal_id: str
    cells_replayed: int
    divergences: list[ReplayDivergence] = []
    determinism_claimed: bool = False

    @property
    def reproduced(self) -> bool:
        """Whether every cell replayed to its recorded outcome."""
        return not self.divergences

    def finding(self) -> str:
        """What this replay established, in the terms of its own contract."""
        if not self.divergences:
            return f"replayed {self.cells_replayed} cells with no divergence"
        indices = ", ".join(str(item.index) for item in self.divergences)
        if self.determinism_claimed:
            return (
                f"determinism was claimed but cells [{indices}] replayed "
                "differently — the recorded outcome is not reproducible and "
                "nothing built on it should be treated as established"
            )
        return (
            f"cells [{indices}] replayed differently, which is the finding: "
            "these results depended on network or install state rather than "
            "on the journal alone"
        )


class ReplayJournal(BaseModel, frozen=True):
    """An ordered execution record plus its lineage and its contract."""

    id: str
    parent: str | None = Field(
        default=None, description="Journal this one was forked from"
    )
    created_at: str = Field(default_factory=timestamp_now)
    cells: list[JournalCell] = []
    determinism_claimed: bool = Field(
        default=False,
        description=(
            "Whether this environment asserts a replay must reproduce the "
            "recorded outcomes. False means divergence is information, not a "
            "defect — and that this journal can never back a certified claim"
        ),
    )

    def digest(self) -> str:
        """SHA-256 identity of the ordered cells alone.

        The cells and not the envelope, so a journal forked from another, or
        re-created with a fresh id, still digests to the same value when it
        records the same execution.
        """
        payload = TypeAdapter(list[JournalCell]).dump_json(self.cells)
        return hashlib.sha256(payload).hexdigest()

    def compare(
        self, replayed_ok: list[bool], details: list[str] | None = None
    ) -> ReplayReport:
        """Compare a replay's per-cell outcomes against what was recorded.

        A short replay is compared as far as it went rather than refused: a
        run that stopped early still establishes something about the cells it
        reached, and reporting nothing would discard that.
        """
        notes = details or [""] * len(replayed_ok)
        return ReplayReport(
            journal_id=self.id,
            cells_replayed=len(replayed_ok),
            divergences=[
                ReplayDivergence(
                    index=index,
                    recorded_ok=cell.ok,
                    replayed_ok=actual,
                    detail=note,
                )
                for index, (cell, actual, note) in enumerate(
                    zip(self.cells, replayed_ok, notes, strict=False)
                )
                if cell.ok != actual
            ],
            determinism_claimed=self.determinism_claimed,
        )
