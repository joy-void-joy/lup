"""Where a session's inbox is placed, and the three ways placement silently fails.

All three look like success from the launcher's side. A bind mount whose
source does not exist takes the whole container down with an engine error
naming neither the directory nor the session. A mount whose target renames
its source produces a session that binds cleanly and publishes a path no peer
can open. And a directory the runtime refuses -- because it is a symlink, is
not ours, or is not private -- produces a session with no inbox at all, which
reads exactly like a peer that is merely busy.
"""

import re
import stat
from pathlib import Path

from lup.harness.image import Image
from lup.harness.messaging import SessionInboxes

# The four directories Claude Code will scan for peers, as its own binary
# spells them. Written out rather than imported because they are the runtime's
# and this repository's interest in them is the opposite of the usual one: not
# to match, but to stay out.
RUNTIME_SCANNED = [
    r"^/tmp/cc-socks(?:-(0|[1-9]\d*))?$",
    r"^/private/tmp/cc-socks(?:-(0|[1-9]\d*))?$",
    r"^/run/user/(0|[1-9]\d*)/cc-socks$",
    r"^/data/data/com\.termux/files/usr/tmp/cc-socks(?:-(0|[1-9]\d*))?$",
]

# What the runtime will bind, as a Unix socket address: it refuses a longer
# path outright and says so. Its own message rounds it, and so does this.
ADDRESS_LIMIT = 104


def test_the_directory_is_made_rather_than_left_to_the_engine(tmp_path: Path) -> None:
    """A bind mount whose source is absent is one the engine refuses entirely.

    Ordinary rather than exotic: a machine where no session has ever run
    outside a container has never had anything create this directory, so the
    first contained launch is the one that would fail.
    """
    directory = tmp_path / "lup-inbox"
    served = SessionInboxes(directory=str(directory)).serve()

    assert served == directory
    assert directory.is_dir()


def test_the_directory_is_made_private_because_the_runtime_checks(
    tmp_path: Path,
) -> None:
    """The runtime refuses a socket directory that is not mode 0700 and says why.

    Refused there rather than here, which is the reason this is pinned: a
    directory left at the umask's mode produces a session that starts, reports
    nothing unusual, and has no inbox for anyone to nudge.
    """
    directory = tmp_path / "lup-inbox"
    directory.mkdir(mode=0o755)

    served = SessionInboxes(directory=str(directory)).serve()

    assert served == directory
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_serving_twice_is_the_second_session_arriving_rather_than_an_error(
    tmp_path: Path,
) -> None:
    """Every launch serves, and all but the first find it already there.

    That is the whole point of one directory -- several sessions arrive in it
    -- so the second arrival has to be unremarkable. Both postures serve for
    their own reasons, too: the mount needs the source to exist on the host,
    and an uncontained session needs the same directory with no mount at all.
    """
    directory = tmp_path / "lup-inbox"
    inboxes = SessionInboxes(directory=str(directory))

    assert inboxes.serve() == directory
    assert inboxes.serve() == directory


def test_a_directory_declared_empty_serves_nothing(tmp_path: Path) -> None:
    """Emptying it is how an adopter declines the nudge.

    The posture every launch had before placement existed, kept reachable
    rather than removed: a session nobody can nudge still has its durable
    inbox, and nothing about the launch fails.
    """
    assert SessionInboxes(directory="").serve() is None


def test_a_member_is_named_by_the_member_rather_than_its_process() -> None:
    """A pid is the one name that does not survive the boundary this crosses.

    Two sessions in sibling containers are each pid 7 in their own namespace,
    so a pid-named socket has two owners and one path. The launcher already
    disambiguates a member's name between live sessions in a worktree, which
    makes it the name that means one session everywhere it is read.
    """
    placed = SessionInboxes(directory="/tmp/lup-inbox").socket("dev-6")

    assert placed == "/tmp/lup-inbox/dev-6.sock"


def test_a_placed_address_stays_inside_what_a_unix_socket_holds() -> None:
    """Past about 104 bytes the runtime refuses the address and binds nothing.

    Which is why this directory is short and shallow rather than living beside
    the checkout it serves. Measured against a real member name: the default
    spends 25 of the budget and leaves the rest for however many sessions a
    worktree numbers its way up to.
    """
    placed = SessionInboxes().socket("dev-6")

    assert len(placed) < ADDRESS_LIMIT
    assert len(SessionInboxes().socket("dev-" + "9" * 40)) < ADDRESS_LIMIT


def test_the_default_is_not_a_directory_the_runtime_scans_for_peers() -> None:
    """Staying out of those four is what keeps this a nudge and not a channel.

    A directory the runtime scans makes every session in it natively
    reachable by every other, through files that `lup.policy.kernel.peers`
    cannot see because it guards tool calls. Measured the other way round too:
    a session launched into this directory left the runtime's own holding only
    the launcher's socket.
    """
    directory = SessionInboxes().directory

    assert not [scanned for scanned in RUNTIME_SCANNED if re.match(scanned, directory)]


def test_the_mount_keeps_the_path_it_had_outside() -> None:
    """The path is a datum, so source and target renaming it apart breaks it.

    A member publishes the path it bound and a peer in another container opens
    that same text. A target that differed would leave every handle correct
    inside the session that wrote it and wrong everywhere it was read -- and
    the launch would report success either way.
    """
    started = Image().session_arguments(
        tag="lup-agent:x",
        checkout=Path("/home/u/repo"),
        uid=1000,
        gid=1000,
        writable={Path("/home/u/repo"): "/home/u/repo"},
        read_only={},
        state_volume="lup-cfg-x",
        config_home_env="CLAUDE_CONFIG_DIR",
        inbox_directory=Path("/tmp/lup-inbox"),
    )

    assert "/tmp/lup-inbox:/tmp/lup-inbox:rw" in started


def test_a_launch_that_placed_nothing_mounts_nothing() -> None:
    """The launch where serving failed on a machine that wanted it.

    Separate from the declined case on purpose: the argv this produces has to
    be the argv of a session without placement rather than one carrying a
    mount to nowhere.
    """
    started = Image().session_arguments(
        tag="lup-agent:x",
        checkout=Path("/home/u/repo"),
        uid=1000,
        gid=1000,
        writable={Path("/home/u/repo"): "/home/u/repo"},
        read_only={},
        state_volume="lup-cfg-x",
        config_home_env="CLAUDE_CONFIG_DIR",
    )

    assert not [argument for argument in started if "lup-inbox" in argument]


def test_an_operator_is_told_which_way_it_went() -> None:
    """Both answers change what the reader does next, so both are said.

    One who does not know placement happened routes a nudge through the
    person; one who does not know it failed reads a peer that never looks as
    the coordination store being broken, and goes looking in the wrong half.
    """
    inboxes = SessionInboxes()
    placed = inboxes.notice(True)
    absent = inboxes.notice(False)

    assert placed and absent
    assert [said.text for said in placed] != [said.text for said in absent]
