"""What the policy declines to interrupt about, written down and read back.

The relaxation's whole argument is that asking on everything unjudged was an
observability claim, and that logging serves it without spending anybody's
attention. That only holds if something is written down, so these pin what is
recorded, what is not, and the distinction the list is read for.
"""

from pathlib import Path

from lup.devtools.hooks.corpus import read_corpus
from lup.policy.assets.host import record_deferral


def test_a_deferral_is_written_down_with_the_kind_it_was(tmp_path: Path) -> None:
    """Both kinds reach one word and are worth opposite things.

    An unjudged deferral is a gap in the vocabulary and a candidate for a
    rule; a judged one is a rule having looked and the boundary having
    answered. Recorded rather than inferred later, because the only other
    thing telling them apart would be the wording of a reason.
    """
    record_deferral(tmp_path, "frobnicate --wibble", "not classified", judged=False)
    record_deferral(tmp_path, "git reset --hard", "the tree is held", judged=True)

    corpus = read_corpus(tmp_path)

    assert [item.command for item in corpus.gaps()] == ["frobnicate --wibble"]
    assert [item.command for item in corpus.settled()] == ["git reset --hard"]


def test_the_same_command_is_written_down_once(tmp_path: Path) -> None:
    """A session defers the same `grep` fifty times, and fifty lines is unreadable.

    The same failure the undo layer's dedup exists to prevent, in the same
    shape: a list nobody can scan is the feature failing at the thing it is
    for.
    """
    for _ in range(5):
        record_deferral(tmp_path, "grep -rn thing .", "not classified", judged=False)

    assert len(read_corpus(tmp_path).deferrals) == 1


def test_a_command_reached_twice_keeps_the_first_reason(tmp_path: Path) -> None:
    """Compared on the command alone, because the rest is what one session said."""
    record_deferral(tmp_path, "make build", "first", judged=False)
    record_deferral(tmp_path, "make build", "second", judged=True)

    held = read_corpus(tmp_path).deferrals

    assert [(item.reason, item.judged) for item in held] == [("first", False)]


def test_a_checkout_that_cannot_be_written_records_nothing(tmp_path: Path) -> None:
    """A read-only checkout is an ordinary place to be running.

    This sits in front of a command somebody asked for, so it is silent about
    its own failure for the reason the snapshot is: none of the ways it can
    fail is a reason to stop the command. A missing directory is *not* that
    case -- the writer creates one -- so the corpus path is blocked by a file
    standing where its directory would go.
    """
    blocked = tmp_path / ".lup" / "hooks"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("not a directory", encoding="utf-8")

    assert record_deferral(tmp_path, "ls", "reason", judged=False) == ""


def test_no_root_records_nothing() -> None:
    """A hook is promised nothing about where it runs."""
    assert record_deferral(None, "ls", "reason", judged=False) == ""


def test_a_torn_line_is_skipped_rather_than_refusing_the_whole_corpus(
    tmp_path: Path,
) -> None:
    """Two processes append here and one may be part-way through a write.

    A reader that refused to load over a torn line would stop working exactly
    when the session it reviews is busiest.
    """
    record_deferral(tmp_path, "ls src", "not classified", judged=False)
    path = tmp_path / ".lup" / "hooks" / "learned.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + '{"command": "tr', "utf-8")

    assert [item.command for item in read_corpus(tmp_path).deferrals] == ["ls src"]


def test_a_checkout_with_nothing_recorded_reads_as_empty(tmp_path: Path) -> None:
    """No corpus and an empty one are the same answer to the reader."""
    assert read_corpus(tmp_path).deferrals == []
