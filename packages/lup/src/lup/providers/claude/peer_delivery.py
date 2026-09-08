# lup: ignore[constant-declaration]
# The file names below are a handshake across three processes: the generator
# writes them, the guard execs one by the other, and the shipped reader
# answers to both. A caller free to spell them differently is a caller free
# to ship a guard that reaches nothing.
"""What a plugin ships so a peer's mail reaches a session nobody opened in-process.

The in-process hook closes over a live inbox, which is why it reaches only the
sessions lup itself opened. A person's own session has the plugin and no live
object, so delivery has to arrive as files a script can read — and the script
has to be cheap enough to run before *every* tool call, because the tools a
session uses while it is only reading are the ones the policy matcher does not
name.

Two artifacts answer that. A shell guard compares the mailbox's length against
the position this member has been delivered to and exits without starting an
interpreter where they agree, which is almost always. Only when the mailbox
has grown does it hand over to
:mod:`lup.coordination.delivery_runtime`, shipped verbatim beside it.

Every name the guard needs is interpolated from the definition that owns it
rather than written twice: a store directory renamed in one place moves the
guard with it, instead of leaving a script that reads a path nobody writes.
"""

from importlib import resources
from pathlib import Path

from lup.coordination.identity import MEMBER_KIND
from lup.coordination.mail import DELIVERY_DIR, MESSAGE_FILE
from lup.coordination.store import COORDINATION_DIR, STORE_DIR
from lup.formats.banner import (
    REGENERATE_COMMAND,
    VERBATIM_COPY,
    GeneratedBanner,
)
from lup.harness.models import Artifact

RUNTIME_MODULE = "coordination_delivery.py"
GUARD_SCRIPT = "coordination_delivery.sh"
RUNTIME_ORIGIN = "lup.providers.claude.peer_delivery_runtime"
"""The two files a plugin carries for delivery, and where the reader comes from.

Beside the policy dispatcher's own pair rather than inside it, because they
answer different questions and fail in opposite directions: a policy that
cannot decide refuses, and a delivery that cannot answer stands aside.
"""


def delivery_runtime_source() -> str:
    """The reader, read from the module that owns it rather than restated here."""
    return (
        resources.files("lup.providers.claude")
        .joinpath("peer_delivery_runtime.py")
        .read_text("utf-8")
    )


def guard_body() -> str:
    """A mailbox-length check that answers "nothing waiting" without Python.

    Append-only is what makes length the right question: the stream only
    grows, so a delivered position that already covers its whole length means
    nothing has arrived since. Length rather than a modification time, because
    two writes inside one filesystem tick leave the times equal and a guard
    reading them would skip mail that is really there — a silent loss, where
    the opposite mistake costs one interpreter start.

    Every failure exits zero. This runs before every tool call, so a guard
    that cannot tell must let the call through: the cost of being wrong that
    way is mail arriving one call later, and the cost of the other way is a
    session that cannot work.
    """
    return f"""#!/bin/sh
[ -n "$LUP_COORDINATION_MEMBER" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
shared=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
case "$shared" in
    /*) ;;
    *) shared="$PWD/$shared" ;;
esac
root="$shared/{STORE_DIR}/{COORDINATION_DIR}"
mailbox="$root/{MESSAGE_FILE}"
[ -f "$mailbox" ] || exit 0
size=$(wc -c < "$mailbox" 2>/dev/null | tr -d ' ') || exit 0
[ -n "$size" ] || exit 0
cursor="$root/{DELIVERY_DIR}/{MEMBER_KIND}-$LUP_COORDINATION_MEMBER.json"
delivered=0
if [ -f "$cursor" ]; then
    delivered=$(tr -dc '0-9' < "$cursor" 2>/dev/null)
    [ -n "$delivered" ] || delivered=0
fi
[ "$size" -gt "$delivered" ] || exit 0
exec python3 "${{0%/*}}/../runtime/{RUNTIME_MODULE}" "$root" "$LUP_COORDINATION_MEMBER"
"""


def delivery_command(plugin_root_env: str) -> str:
    """The hooks entry, which never refuses however badly it goes.

    No `|| exit 2` beside it, unlike the policy guard's: a delivery that fails
    is a session that did not hear something, and turning that into a refused
    tool call would make an unreachable mailbox stop the work it was trying to
    inform.
    """
    return f'sh "${plugin_root_env}/hooks/scripts/{GUARD_SCRIPT}" || exit 0'


def delivery_artifacts(plugin_root: Path, semantic_id: str) -> list[Artifact]:
    """The guard and the reader, as one plugin carries them."""
    return [
        Artifact.generated(
            path=plugin_root / "hooks" / "scripts" / GUARD_SCRIPT,
            body=guard_body(),
            semantic_id=semantic_id,
            banner=GeneratedBanner(source=__name__, command=REGENERATE_COMMAND),
            executable=True,
        ),
        Artifact(
            path=plugin_root / "hooks" / "runtime" / RUNTIME_MODULE,
            content=delivery_runtime_source(),
            semantic_id=semantic_id,
            banner=VERBATIM_COPY.compiled_from(RUNTIME_ORIGIN),
        ),
    ]
