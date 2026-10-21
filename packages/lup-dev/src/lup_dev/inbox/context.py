"""A conversation as its runtime records it, and an item's moment in it, read from the record as it stands.

`docs/inbox.md`, *An item's moment*. An item an agent's call made keeps the
runtime's id for that call (`Item.call`), which the call's hook stamped, and the
record keeps the same id beside the call (`Called.id`). Its moment is the steps
around it: from the operator's last words before the call, through the call, to
their next words or the record's end. A session's main conversation and each
subagent's have records of their own, so a subagent's item reads its own.

The dashboard reads a whole conversation the same way (`Records`), step by step
from where it last read, so a conversation growing as the agent works is read
again only from its record's latest change (`Recording`).
"""

from pathlib import Path

from lup.types import Model, MutableModel
from lup_dev.host.records import Called, Entry, Recorded, Said, Transcript
from lup_dev.inbox.store import Conversation, InboxError, Item, cited


class Moment(Model):
    """The steps around one call in a record, and which of them is the call."""

    entries: list[Entry]
    anchor: int


def moment(transcript: Transcript, call: str) -> Moment | None:
    """Return the steps around the call `call` in `transcript`: from the operator's last words before it, through it, to their next words or the record's end; none where the record doesn't hold it."""
    steps = transcript.entries
    at = next(
        (
            index
            for index, each in enumerate(steps)
            if isinstance(each, Called) and each.id == call
        ),
        None,
    )
    if at is None:
        return None
    spoke = [
        index
        for index, each in enumerate(steps)
        if isinstance(each, Said) and each.by == "operator"
    ]
    start = max((index for index in spoke if index < at), default=0)
    end = min((index for index in spoke if index > at), default=len(steps))
    return Moment(entries=steps[start:end], anchor=at - start)


def read(item: Item, recorded: dict[str, Recorded]) -> Moment:
    """Read item's moment from its sender's record as it stands.

    Raise `InboxError` saying why where it has none: no agent's call made the
    item, lup can't read its runtime's records, the record isn't on this
    machine, or it doesn't hold the call.
    """
    match item:
        case Item(sender=Conversation() as sender, call=str() as call):
            pass
        case _:
            message = f"{cited(item.number)} was made by no agent's call"
            raise InboxError(message)
    read = Recording().read(recorded, sender.runtime, sender.session, sender.agent)
    found = moment(read.transcript, call)
    if found is None:
        message = (
            f"{read.record} doesn't hold call {call}, which made {cited(item.number)}"
        )
        raise InboxError(message)
    return found


class Read(Model):
    """A record as last read: where it is, its size and time then, and what it held."""

    record: Path
    size: int
    changed: int
    """Its modification time, in nanoseconds."""
    transcript: Transcript


class Recording(MutableModel):
    """Reads conversations from their records, keeping each as last read, so a record unchanged since isn't read again."""

    kept: dict[Path, Read] = {}

    def read(
        self,
        recorded: dict[str, Recorded],
        runtime: str,
        session: str,
        agent: str | None,
    ) -> Read:
        """Return the record of session `session` of `runtime`, or of its subagent `agent`, and what it holds as it stands.

        Raise `InboxError` saying why where it can't be read: lup can't read the
        runtime's records, or the record isn't on this machine.
        """
        reading = recorded.get(runtime)
        if reading is None:
            message = f"lup can't read the records of {runtime}"
            raise InboxError(message)
        record = reading.records.conversation(session, agent)
        if record is None:
            whose = f"{runtime} session {session}" + (
                "" if agent is None else f", subagent {agent},"
            )
            message = f"the record of {whose} isn't on this machine"
            raise InboxError(message)
        stat = record.stat()
        last = self.kept.get(record)
        if (
            last is not None
            and last.size == stat.st_size
            and last.changed == stat.st_mtime_ns
        ):
            return last
        read = Read(
            record=record,
            size=stat.st_size,
            changed=stat.st_mtime_ns,
            transcript=reading.reader.read(record),
        )
        self.kept = {**self.kept, record: read}
        return read
