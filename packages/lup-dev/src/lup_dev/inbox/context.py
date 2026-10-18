"""An item's moment in the conversation that sent it, read from its runtime's record as it stands.

`docs/host-tools.md`, *An item's moment*. An item an agent's call made keeps the
runtime's id for that call (`Item.call`), which the call's hook stamped, and the
record keeps the same id beside the call (`Called.id`). Its moment is the steps
around it: from the operator's last words before the call, through the call, to
their next words or the record's end. A session's main conversation and each
subagent's have records of their own, so a subagent's item reads its own.
"""

from lup.types import Model
from lup_dev.host.records import Called, Entry, Recorded, Said, Transcript
from lup_dev.inbox.delivery import who
from lup_dev.inbox.store import Conversation, InboxError, Item


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
            message = f"item {item.number} was made by no agent's call"
            raise InboxError(message)
    runtime = recorded.get(sender.runtime)
    if runtime is None:
        message = f"lup can't read the records of {sender.runtime}, which sent item {item.number}"
        raise InboxError(message)
    record = runtime.records.conversation(sender.session, sender.agent)
    if record is None:
        message = f"the record of {who(sender)}, which sent item {item.number}, isn't on this machine"
        raise InboxError(message)
    found = moment(runtime.reader.read(record), call)
    if found is None:
        message = f"{record} doesn't hold call {call}, which made item {item.number}"
        raise InboxError(message)
    return found
