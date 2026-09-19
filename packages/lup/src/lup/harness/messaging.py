"""Where lup puts its sessions' inboxes, so one can reach another.

Claude Code gives every session a private inbox on a Unix socket and takes a
newline-delimited JSON frame written to it, which arrives there as a message
and starts a turn. That is what :mod:`lup.coordination.wake` writes to, and
the only thing between a nudge and an idle peer is whether the waking process
can open the file.

A contained session cannot, left alone. Measured: ``/proc/self/mountinfo``
carries no mount for ``/tmp``, so each session's socket directory is its own.
Worse than invisible -- the runtime's own default is
``/tmp/cc-socks/<pid>.sock``, and a session that is pid 7 in its own namespace
names a path that exists, live, and belongs to somebody else in every sibling
container.

So lup places the sockets itself: the launcher passes
``--messaging-socket-path`` naming a file under this directory, one bind mount
arrives there, and a member's declared inbox is a path every peer can open and
exactly one session owns.

**The mount is path-preserving, which is the design rather than a
convenience.** The path is a datum that travels -- a member declares what it
bound and a peer in another container opens that same string -- so a source
and target that disagreed would leave every handle right inside the session
that wrote it and wrong everywhere it was read.

**This is deliberately not a directory the runtime scans.** Its own peer
discovery matches a socket directory against four anchored patterns --
``/tmp/cc-socks``, its ``/private/tmp`` and Termux spellings, and
``/run/user/<uid>/cc-socks`` -- and a directory lup names matches none of
them. Measured: a session launched with the flag bound here and left
``/tmp/cc-socks`` holding only the launcher's own socket. That is the whole
difference between this and mounting the runtime's own directory, which would
make every session on the machine natively reachable by every other through a
file channel :mod:`lup.policy.kernel.peers` cannot see, since that guards tool
calls rather than files.

What this does grant is worth naming rather than burying: any process that can
open these files can start a turn in any session that bound one. Two things
bound it. The record is always written before anything is nudged, so a wake
that goes astray costs latency and never a message; and a wake carries the
session id of the member it is for, which the receiving inbox checks against
its own and drops on a mismatch -- so a frame that reached the wrong session is
refused by it rather than delivered.
"""

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from lup.harness.notice import Notice

logger = logging.getLogger(__name__)


class SessionInboxes(BaseModel, frozen=True):
    """The one directory this machine's sessions publish their inboxes into.

    One model because three places have to agree on the same string: the
    launcher makes the directory and names a file in it on the command line,
    the image mounts it, and a peer reads the path back off the roster. Split
    up, a launch mounts somewhere the session does not bind and the failure is
    a peer that never looks while everything reports success.
    """

    directory: str = Field(
        default="/tmp/lup-inbox",
        description=(
            "Where every session this launcher starts binds its inbox, on the "
            "host and under that same path inside a container. Constrained "
            "rather than free: the runtime refuses a socket directory that is "
            "a symlink, that it does not own, or that is not mode 0700, and "
            "refuses the address outright past about 104 bytes -- which is "
            "why this stays short and shallow rather than living beside the "
            "checkout it serves. Emptying it declares sessions that reach "
            "each other only where the runtime's own default path already "
            "does, which is the posture every launch had before this existed"
        ),
    )

    def socket(self, name: str) -> str:
        """The inbox path one member binds, named after the member.

        After the member rather than after its process, because the name is
        what the launcher already disambiguates between live sessions in a
        worktree, and a pid is the one thing that does not survive the
        container boundary this directory exists to cross.
        """
        return str(Path(self.directory) / f"{name}.sock")

    def serve(self) -> Path | None:
        """Make the directory, and answer with it.

        Made here rather than left to whoever mounts it, because a bind mount
        whose source does not exist is one the engine refuses the whole
        container for, and because the runtime checks the mode before it binds
        rather than fixing it.

        Nothing comes back when it cannot be made, which is a launch whose
        sessions do not nudge each other rather than a launch that fails: the
        durable inbox is untouched and the notice says so.
        """
        if not self.directory:
            return None
        directory = Path(self.directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        except OSError as error:
            # Logged rather than swallowed, for the reason the clipboard's is:
            # a session nobody can nudge is an ordinary outcome, and "why" is
            # the difference between a machine that cannot have one and a path
            # this got wrong.
            logger.warning("session inboxes did not open: %s", error)
            return None
        return directory

    def notice(self, serving: bool) -> list[Notice]:
        """What an operator is told about their sessions being able to nudge each other.

        Said either way, because both answers change what the reader does
        next. One who does not know it is there will route a nudge through the
        person; one who does not know it is absent reads a peer that never
        looks as the coordination store being broken, and goes looking in the
        wrong half.
        """
        if not serving:
            return [
                Notice(
                    text=(
                        "peer wake: this session's inbox is its own — mail "
                        "still lands in the record, and waits until the peer "
                        "it is for next looks"
                    ),
                    urgency="boundary",
                )
            ]
        return [
            Notice(
                text=(
                    f"peer wake: sessions placed in {self.directory} can nudge "
                    "one another into reading their mail; what they say to "
                    "each other still goes through the recorded stream"
                ),
                urgency="boundary",
            )
        ]
