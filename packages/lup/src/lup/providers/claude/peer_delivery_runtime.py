# lup: ignore[constant-declaration]
# Two vocabularies meet here and a caller may replace neither. The store's
# file names are the typed writer's, restated because a verbatim copy cannot
# import them and pinned back to it by a test; the envelope's names are this
# runtime's own wire spelling, a fact about Claude Code rather than a taste.
"""Put a peer's mail in front of its next tool call, from inside the plugin.

Shipped verbatim into each plugin's `hooks/runtime/`, so everything here has
to resolve on a bare interpreter: standard library only, no `lup` import, no
third-party package. That is the constraint the compiled dispatcher runs under
and it is what lets this reach a session nobody opened in-process — a person's
own `claude`, which has the plugin and no live object to close over.

**A reader, never the authority.** The typed implementation in
:mod:`lup.coordination.mail` writes the stream and owns what a message means;
this reads two settled formats — an append-only JSONL stream, and one reader
position spelled `{"offset": N}` — and hands what it finds to the session. The
spellings the two halves share are pinned by a test rather than shared by an
import, because an import is the one thing a verbatim copy cannot have.

**It fails open, and that is the whole of its safety story.** This runs before
*every* tool call, so a delivery that cannot answer must not be able to stop
one: every failure path returns silently and the call proceeds. The policy
dispatcher fails closed because a permission it cannot decide is one it must
not grant. Mail is not a permission, and a session that cannot receive should
lose its mail rather than its ability to work.

``TypedDict`` throughout for the reason the kernel uses them: pydantic is not
here to be imported, and neither is ``lup.types``.
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

MESSAGE_FILE = "messages.jsonl"
DELIVERY_DIR = "delivery"
MEMBER_KIND = "session"
EVERYONE = "*"
"""The store's own spelling, restated because a verbatim copy cannot import it.

Pinned against :mod:`lup.coordination.mail` and
:mod:`lup.coordination.identity` by a test, which is what stands in for the
import: a rename there fails the suite here rather than quietly delivering
into a directory nobody writes.
"""

EVENT_FIELD = "hookEventName"
EVENT_NAME = "PreToolUse"


class Message(TypedDict, total=False):
    """One record on the mail stream, as far as delivering it needs to know.

    Partial because the typed writer owns this record: a field added there
    must not make the record unreadable here, and a field this never reads is
    not this reader's business to declare.
    """

    to_actor: str
    text: str
    door: str
    redirect: bool


class Arrived(TypedDict):
    """What one call takes: the messages for this member, and what they consume."""

    messages: list[Message]
    consumed: int


class Delivered(TypedDict, total=False):
    """The runtime's own envelope fields, in the runtime's own spelling."""

    hookEventName: str
    additionalContext: str
    permissionDecision: str
    permissionDecisionReason: str


class HookOutput(TypedDict):
    """What this hook prints. `additionalContext` nested here is what is read.

    At the top level the runtime accepts it and ignores it, which is the one
    way to be wrong here that leaves no evidence.
    """

    hookSpecificOutput: Delivered


def reader_name(member_id: str) -> str:
    """The cursor this member reads through, spelled as `ActorRef.conversation`."""
    return f"{MEMBER_KIND}-{member_id}"


def reaches(to_actor: str, member_id: str) -> bool:
    """Whether a message addressed this way reaches this member.

    Recognizing rather than parsing, because the spellings a sender may have
    written down are a closed list: the bare id, the kind-qualified form, that
    form with the only round a roster member ever holds, and the broadcast
    token. A redirect sent to a spelling one surface printed must not reach
    nobody, and a reader that parsed instead would have to decide for itself
    what an unfamiliar suffix meant.
    """
    return to_actor in (
        EVERYONE,
        member_id,
        f"{MEMBER_KIND}:{member_id}",
        f"{MEMBER_KIND}:{member_id}#1",
    )


def committed_offset(cursor: Path) -> int:
    """Where this member has been delivered to, zero where it never has.

    A position that will not parse reads as zero rather than as the head. Both
    wrong answers cost something — one re-reads history, the other drops it —
    and only the re-read is visible to the person it happens to.
    """
    try:
        return int(json.loads(cursor.read_text("utf-8"))["offset"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def framed(data: bytes) -> list[bytes]:
    """Every complete line in this region, dropping a partial one at the end.

    A writer appending while this reads leaves the last line unterminated. It
    is left behind rather than parsed, so the next call takes it whole.
    """
    return [line for line in data.splitlines(keepends=True) if line.endswith(b"\n")]


def parsed(line: bytes) -> Message | None:
    """One record, or nothing where the line is not a JSON object.

    A malformed line is skipped rather than raised on: the stream is written
    by another process, and one unreadable record must not stop the session
    receiving the messages around it.
    """
    try:
        record: Message = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def waiting(stream: Path, offset: int, member_id: str) -> Arrived:
    """Every message for this member after *offset*, and the offset consuming them.

    The consumed region covers records addressed elsewhere too, because a
    reader that advanced only past its own would re-read every other member's
    mail on every call.
    """
    try:
        with stream.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return Arrived(messages=[], consumed=offset)
    complete = framed(data)
    return Arrived(
        messages=[
            record
            for record in (parsed(line) for line in complete)
            if record is not None and reaches(record.get("to_actor", ""), member_id)
        ],
        consumed=offset + sum(len(line) for line in complete),
    )


def commit(cursor: Path, offset: int) -> None:
    """Record what was handed over, atomically, so a crash re-delivers instead.

    Written to a neighbouring temporary file and renamed, because a partial
    write here is a position that will not parse. That is recoverable — it
    reads as zero — but it costs the session its whole history at once.
    """
    cursor.parent.mkdir(parents=True, exist_ok=True)
    temporary = cursor.with_suffix(".writing")
    temporary.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    temporary.replace(cursor)


def rendered(messages: list[Message]) -> str:
    """What the session reads, one line per message, naming what carried each."""
    return "\n".join(
        f"[{'redirected' if message.get('redirect') else 'message'} by "
        f"{message.get('door', 'peer')}] {message.get('text', '')}"
        for message in messages
    )


def envelope(messages: list[Message]) -> HookOutput:
    """The hook output carrying this mail, as telling or as stopping.

    A redirect denies the call and hands the text back as the reason, so an
    agent going the wrong way cannot take one more step down it. An ordinary
    message rides alongside and the call proceeds.
    """
    delivered = rendered(messages)
    if any(message.get("redirect") for message in messages):
        return HookOutput(
            hookSpecificOutput=Delivered(
                hookEventName=EVENT_NAME,
                permissionDecision="deny",
                permissionDecisionReason=(
                    f"{delivered}\n\nStop what this call was part of and act "
                    "on the above."
                ),
            )
        )
    return HookOutput(
        hookSpecificOutput=Delivered(
            hookEventName=EVENT_NAME, additionalContext=delivered
        )
    )


def deliver(root: Path, member_id: str) -> HookOutput | None:
    """Take this member's mail and say what the session should be told."""
    cursor = root / DELIVERY_DIR / f"{reader_name(member_id)}.json"
    arrived = waiting(root / MESSAGE_FILE, committed_offset(cursor), member_id)
    if arrived["consumed"]:
        commit(cursor, arrived["consumed"])
    return envelope(arrived["messages"]) if arrived["messages"] else None


def main() -> None:
    """Deliver, or say nothing at all and let the call through.

    Every failure is silence. This runs before every tool call in the session,
    so an exception escaping here would stop the session working rather than
    stop its mail arriving, and of those two only one is worth doing.
    """
    try:
        answer = deliver(Path(sys.argv[1]), sys.argv[2])
    except Exception:
        return
    if answer is not None:
        print(json.dumps(answer))


if __name__ == "__main__":
    main()
