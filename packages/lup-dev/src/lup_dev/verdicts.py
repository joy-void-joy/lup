"""The verdict log: every judgement, one JSON line each, and its summary.

Every judgement is logged from day one, so how often lup asks, refuses and allows
can be measured and tuned rather than guessed (`docs/judging-writes.md`, *The
verdict log*). The log is kept per repository, beside the stores, so one place
measures a repository's verdicts across its worktrees.

An ask's answer comes later than the ask: when the call it asked about finishes,
or when a hold is answered. The answer is appended as the same verdict again,
under the same key, with its answer; a reader takes the last line for each key.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from filelock import FileLock

from lup.types import Model
from lup_dev.roles import Role

type VerdictOutcome = Literal["allow", "ask", "refuse", "hold"]
type Answer = Literal["approved", "declined", "unanswered"]


class Verdict(Model):
    """One judgement of one file."""

    key: str
    """Names the verdict, so a later answer is recorded against it."""
    time: datetime
    session: str
    runtime: str
    tool: str
    """The runtime's tool the judgement was about, or `checkpoint`."""
    path: Path
    role: Role
    outcome: VerdictOutcome
    reasons: list[str]
    """The rules that refused, the kinds of ask, or the role that allowed."""
    answer: Answer | None = None
    """The operator's answer to an ask or a hold, once there is one."""


class Tally(Model):
    """How many verdicts share an outcome and a reason, and how asks were answered."""

    outcome: VerdictOutcome
    reason: str
    count: int
    approved: int = 0
    declined: int = 0
    unanswered: int = 0


class VerdictLog(Model):
    """The verdict log of one repository."""

    path: Path

    def append(self, verdicts: list[Verdict]) -> None:
        """Append `verdicts`, one line each, while no other hook writes."""
        if not verdicts:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(f"{verdict.model_dump_json()}\n" for verdict in verdicts)
        with (
            FileLock(self.path.with_name(f"{self.path.name}.lock")),
            self.path.open("a") as log,
        ):
            log.write(lines)

    def read(self) -> list[Verdict]:
        """Read every verdict, the last line for each key, in the order first logged."""
        if not self.path.is_file():
            return []
        lines = [
            Verdict.model_validate_json(line)
            for line in self.path.read_text().splitlines()
            if line
        ]
        latest = {verdict.key: verdict for verdict in lines}
        return list(latest.values())

    def summary(self, since: datetime) -> list[Tally]:
        """Tally the verdicts since `since` by outcome and reason, most frequent first.

        A verdict with several reasons counts once under each.
        """

        class Group(Model):
            """An outcome and one of its reasons, which a tally counts."""

            outcome: VerdictOutcome
            reason: str

        recent = [verdict for verdict in self.read() if verdict.time >= since]
        groups = dict.fromkeys(
            Group(outcome=verdict.outcome, reason=reason)
            for verdict in recent
            for reason in verdict.reasons
        )

        def tally(outcome: VerdictOutcome, reason: str) -> Tally:
            matching = [
                verdict
                for verdict in recent
                if verdict.outcome == outcome and reason in verdict.reasons
            ]
            answers = [verdict.answer for verdict in matching]
            return Tally(
                outcome=outcome,
                reason=reason,
                count=len(matching),
                approved=answers.count("approved"),
                declined=answers.count("declined"),
                unanswered=answers.count("unanswered"),
            )

        tallies = [tally(group.outcome, group.reason) for group in groups]
        by_name = sorted(tallies, key=lambda each: f"{each.outcome} {each.reason}")
        return sorted(by_name, key=lambda each: each.count, reverse=True)
