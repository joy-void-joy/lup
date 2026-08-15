"""What the final re-check has already asked, so a resume does not ask again.

Every other phase of a run skips work it has already done — the worker phase
from ``state.outcomes``, the join sequence from its landing checkpoint — and
the re-check was the one that did not. A resumed run re-examined all of it:
one measured run spent 47 reviewer turns on 21 concerns across a handful of
interruptions, and re-running a reviewer does not only cost a turn, it can
return a different verdict for the same unchanged tree and wedge the run on a
question already asked another way.

Keyed by the commit it examined. A re-check answers "do this concern's
criteria still hold in *that* tree", so a tree reassembled from different
parents is a different question and every concern is examined again.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

RECHECK_DIR = "rechecks"
"""Where under a run directory the finished re-checks are recorded."""


class RecheckRecord(BaseModel):
    """One concern's re-check, as the reviewer that ran it left it."""

    model_config = ConfigDict(frozen=True)

    concern_id: str
    commit: str
    """The integrated commit examined, which is what makes this reusable."""
    question_id: str = ""
    """The question it raised, or empty where every criterion still held.

    The question itself is not copied here. The mailbox owns it, and a second
    copy is a second thing to keep true — so a resume reads the record to
    learn a question exists and the mailbox to learn what it says.
    """


class RecheckDesk:
    """The run directory's record of which re-checks have already run."""

    def __init__(self, run_dir: Path) -> None:
        self.root = run_dir / RECHECK_DIR

    def path(self, concern_id: str) -> Path:
        return self.root / f"{concern_id}.json"

    def record(self, record: RecheckRecord) -> None:
        """Keep one finished re-check, written as it finishes.

        A file per concern rather than one document, because the readers run
        concurrently: a shared file would need every one of them to serialize
        against the others for a record none of them reads.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        self.path(record.concern_id).write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )

    def recorded(self, concern_id: str, commit: str) -> RecheckRecord | None:
        """This concern's re-check of that commit, where one has run."""
        path = self.path(concern_id)
        if not path.is_file():
            return None
        record = RecheckRecord.model_validate_json(path.read_text(encoding="utf-8"))
        return record if record.commit == commit else None

    def clear(self) -> None:
        """Drop every record, so a fresh assembly re-checks from nothing."""
        for path in sorted(self.root.glob("*.json")):
            path.unlink(missing_ok=True)
