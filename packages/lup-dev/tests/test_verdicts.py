"""The verdict log and its summary."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from lup_dev.verdicts import Tally, Verdict, VerdictLog

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def verdict(
    key: str,
    outcome: str,
    reasons: list[str],
    *,
    days_ago: int = 0,
    answer: str | None = None,
) -> Verdict:
    return Verdict.model_validate(
        {
            "key": key,
            "time": NOW - timedelta(days=days_ago),
            "session": "s1",
            "runtime": "claude",
            "tool": "Edit",
            "path": "src/a.py",
            "role": "production",
            "outcome": outcome,
            "reasons": reasons,
            "answer": answer,
        }
    )


def test_an_answer_updates_its_verdict(tmp_path: Path) -> None:
    log = VerdictLog(path=tmp_path / "verdicts.jsonl")
    log.append(
        [verdict("a", "ask", ["new-file"]), verdict("b", "allow", ["rules-pass"])]
    )
    log.append([verdict("a", "ask", ["new-file"], answer="approved")])
    assert [(each.key, each.answer) for each in log.read()] == [
        ("a", "approved"),
        ("b", None),
    ]


def test_the_summary_counts_by_outcome_and_reason_over_a_period(tmp_path: Path) -> None:
    log = VerdictLog(path=tmp_path / "verdicts.jsonl")
    log.append(
        [
            verdict("1", "ask", ["new-file"], answer="approved"),
            verdict("2", "ask", ["new-file"], answer="declined"),
            verdict("3", "ask", ["public-api", "ignore"]),
            verdict("4", "refuse", ["regex"]),
            verdict("5", "refuse", ["regex"], days_ago=30),
        ]
    )
    assert log.summary(NOW - timedelta(days=7)) == [
        Tally(outcome="ask", reason="new-file", count=2, approved=1, declined=1),
        Tally(outcome="ask", reason="ignore", count=1),
        Tally(outcome="ask", reason="public-api", count=1),
        Tally(outcome="refuse", reason="regex", count=1),
    ]


def test_an_empty_log_reads_as_nothing(tmp_path: Path) -> None:
    assert VerdictLog(path=tmp_path / "none.jsonl").read() == []
