# lup: ignore[constant-declaration]
# The envelope's names are this runtime's own wire spelling, a fact about
# Claude Code rather than a taste. Everything the store itself is spelled with
# comes from the shipped package beside this, which is imported rather than
# restated.
"""Put a peer's mail in front of its next tool call, from inside the plugin.

Shipped into the plugin's ``hooks/runtime/``, so everything here has to
resolve on a bare interpreter: the standard library, and the coordination
package sitting beside it. That is the constraint the compiled dispatcher runs
under and it is what lets this reach a session nobody opened in-process — a
person's own ``claude``, which has the plugin and no live object to close over.

**A reader, never the authority.** :mod:`lup.coordination.mail` owns what a
message means; this lists one member's inbox, hands what is there to the
session, and deletes what it handed over. The inbox *is* the position: there
is no offset to commit, nothing to re-read after a crash but what was never
handed over, and no token a reader has to recognize — a message in this
member's inbox is this member's, and a sender that meant everyone resolved
that against the roster before writing.

**Mail only.** A standing notice is not delivered, so it is not here: it is
read at the head of a turn by the prompt fold, restated for as long as it
stays true, where this consumes what it hands over exactly once.

**It fails open, and that is the whole of its safety story.** This runs before
*every* tool call, so a delivery that cannot answer must not be able to stop
one: every failure path returns silently and the call proceeds. The policy
dispatcher fails closed because a permission it cannot decide is one it must
not grant. Mail is not a permission, and a session that cannot receive should
lose its mail rather than its ability to work.
"""

import json
import sys
from pathlib import Path
from typing import TypedDict

# The hook is launched as a bare script, promised no cwd, PYTHONPATH, or
# interpreter environment, and the coordination package is a plain sibling
# directory rather than an installed distribution. Naming this file's own
# directory as a search path is what lets the import below resolve, for the
# interpreter and for a type checker alike.
sys.path.insert(0, str(Path(__file__).parent))
from coordination.mail import Message, consume, spoken, waiting
from coordination.store import MEMBER_KIND, Actor, conversation_of

EVENT_FIELD = "hookEventName"
EVENT_NAME = "PreToolUse"


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


def envelope(messages: list[Message]) -> HookOutput:
    """The hook output carrying this mail, as telling or as stopping.

    A redirect denies the call and hands the text back as the reason, so an
    agent going the wrong way cannot take one more step down it. An ordinary
    message rides alongside and the call proceeds.
    """
    delivered = spoken(messages)
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
    """Take this member's mail and say what the session should be told.

    The inbox is keyed by the conversation this session is on the roster as,
    spelled by the shipped fold rather than assembled here: a sender writes to
    the same key through the typed half, and a directory only one of them
    could name is a message nobody receives.

    Consumed by deleting exactly what is being handed over, so a message that
    arrived between the listing and the deletion waits for the next call
    rather than leaving unseen.
    """
    inbox = conversation_of(Actor(kind=MEMBER_KIND, id=member_id))
    messages = waiting(root, inbox)
    if not messages:
        return None
    consume(root, inbox, messages)
    return envelope(messages)


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
