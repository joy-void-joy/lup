"""Mail reaching a session through the plugin, where no live inbox exists.

The in-process hook closes over an `ActorInbox`, so it reaches only sessions
lup opened itself. This reader is what a person's own session has instead: two
files and a script, with no import of the code that wrote them.

That missing import is the thing to pin. A verbatim copy cannot share a
constant with the module it copies, so the spellings the two halves agree on
are asserted here — a rename on the typed side fails this suite rather than
quietly delivering into a directory nobody writes.
"""

import json
from pathlib import Path

from lup.coordination.identity import MEMBER_KIND, member_ref
from lup.coordination.mail import DELIVERY_DIR, EVERYONE, MESSAGE_FILE
from lup.providers.claude import peer_delivery_runtime as delivery_runtime


def written(root: Path, *records: dict[str, str | bool]) -> None:
    """Put records on the stream the way an appending writer leaves them."""
    root.mkdir(parents=True, exist_ok=True)
    (root / MESSAGE_FILE).write_text(
        "".join(f"{json.dumps(record)}\n" for record in records), encoding="utf-8"
    )


def carried(answer: delivery_runtime.HookOutput | None) -> str:
    """What one delivery puts in front of the session, however it was framed."""
    assert answer is not None
    delivered = answer["hookSpecificOutput"]
    return delivered.get("additionalContext", "") or delivered.get(
        "permissionDecisionReason", ""
    )


def test_the_copy_and_its_source_spell_the_store_alike() -> None:
    """What stands in for the import the verbatim copy cannot have.

    Each of these is read by the copy and written by the typed half. A rename
    on either side that did not move the other would leave delivery reading a
    path nothing writes — working, silent, and wrong.
    """
    assert delivery_runtime.MESSAGE_FILE == MESSAGE_FILE
    assert delivery_runtime.DELIVERY_DIR == DELIVERY_DIR
    assert delivery_runtime.MEMBER_KIND == MEMBER_KIND
    assert delivery_runtime.EVERYONE == EVERYONE


def test_the_copy_names_the_cursor_the_roster_names() -> None:
    """The reader name is `ActorRef.conversation`, derived twice and pinned once."""
    assert delivery_runtime.reader_name("abc123") == member_ref("abc123").conversation()


def test_every_spelling_a_sender_may_have_written_reaches_the_member() -> None:
    """Addresses are recognized, so a redirect cannot be lost to a spelling.

    Each of these is a form some surface prints or accepts; a reader that knew
    only one would drop mail sent to the others with nothing to report.
    """
    for spelling in ("abc123", "session:abc123", "session:abc123#1", EVERYONE):
        assert delivery_runtime.reaches(spelling, "abc123")


def test_another_member_s_mail_is_not_taken() -> None:
    """Addressed elsewhere is not addressed here, however near the id looks."""
    assert not delivery_runtime.reaches("session:abc124", "abc123")
    assert not delivery_runtime.reaches("", "abc123")


def test_mail_is_delivered_once_and_the_position_moves(tmp_path: Path) -> None:
    """The ordinary path: what is addressed here arrives, and arrives once."""
    written(
        tmp_path,
        {"to_actor": "session:abc123#1", "text": "first", "door": "peer"},
        {"to_actor": "somebody-else", "text": "not yours", "door": "peer"},
        {"to_actor": EVERYONE, "text": "broadcast", "door": "peer"},
    )

    delivered = carried(delivery_runtime.deliver(tmp_path, "abc123"))

    assert "first" in delivered
    assert "broadcast" in delivered
    assert "not yours" not in delivered
    assert delivery_runtime.deliver(tmp_path, "abc123") is None


def test_the_position_passes_mail_addressed_to_somebody_else(tmp_path: Path) -> None:
    """The consumed region covers the whole read, not this member's share of it.

    A reader that advanced only past its own would meet every other member's
    mail again on every call, and pay for reading it every time.
    """
    written(tmp_path, {"to_actor": "somebody-else", "text": "theirs", "door": "peer"})

    assert delivery_runtime.deliver(tmp_path, "abc123") is None
    recorded = tmp_path / DELIVERY_DIR / f"{MEMBER_KIND}-abc123.json"
    assert json.loads(recorded.read_text("utf-8"))["offset"] > 0


def test_a_redirect_stops_the_call_it_arrived_before(tmp_path: Path) -> None:
    """Telling and stopping are different acts and get different verdicts."""
    written(
        tmp_path,
        {
            "to_actor": "abc123",
            "text": "wrong branch",
            "door": "peer",
            "redirect": True,
        },
    )

    answer = delivery_runtime.deliver(tmp_path, "abc123")

    assert answer is not None
    assert answer["hookSpecificOutput"].get("permissionDecision") == "deny"
    assert "wrong branch" in carried(answer)


def test_a_record_still_being_written_is_left_for_the_next_call(
    tmp_path: Path,
) -> None:
    """A writer appending while this reads is mid-record, and mid is not a record."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    whole = json.dumps({"to_actor": "abc123", "text": "whole", "door": "peer"})
    (tmp_path / MESSAGE_FILE).write_text(
        f"{whole}\n" + '{"to_actor": "abc123", "text": "half', encoding="utf-8"
    )

    delivered = carried(delivery_runtime.deliver(tmp_path, "abc123"))

    assert "whole" in delivered
    assert "half" not in delivered


def test_a_store_that_is_not_there_delivers_nothing_and_raises_nothing(
    tmp_path: Path,
) -> None:
    """The failure that must not stop a call, since this runs before all of them."""
    assert delivery_runtime.deliver(tmp_path / "absent", "abc123") is None


def test_an_unreadable_position_re_reads_rather_than_skips(tmp_path: Path) -> None:
    """Of the two ways to be wrong about a position, only one is visible.

    Re-reading history is noticed by whoever reads it twice; resuming at the
    head drops everything before it and reads exactly like an empty mailbox.
    """
    written(tmp_path, {"to_actor": "abc123", "text": "kept", "door": "peer"})
    cursor = tmp_path / DELIVERY_DIR / f"{MEMBER_KIND}-abc123.json"
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("not a position", encoding="utf-8")

    assert "kept" in carried(delivery_runtime.deliver(tmp_path, "abc123"))
