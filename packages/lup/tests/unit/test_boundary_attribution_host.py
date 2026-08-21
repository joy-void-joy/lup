"""Telling a confined command's failure from a broken one, inside the dispatcher.

The reading :mod:`lup.sandbox.attribution` already does, in the pinned
standard library, because this copy runs where that module cannot be
imported. What is pinned here is the discipline rather than the mechanism:
a claim is made only where the mount table agrees, and everything else says
nothing. A wrong boundary claim is worse than none, because it teaches an
agent to reach for the host when the bug was in its own code, and that lesson
outlives the one command it was wrong about.
"""

import json
from pathlib import Path

from lup.policy.assets.host import boundary_description, boundary_refusal

CONFINED = {
    "read_only": ["/repo/tree/dev", "/repo/tree/other"],
    "write_refusals": ["Read-only file system", "Permission denied"],
    "allowed_hosts": [],
}


def test_a_refused_write_under_a_declared_mount_is_attributed() -> None:
    """Both halves agreed: the kernel said refused, the table says this is ours."""
    spoken = boundary_refusal(
        "touch: cannot touch '/repo/tree/dev/x.py': Read-only file system", CONFINED
    )
    assert "/repo/tree/dev" in spoken
    assert "not the filesystem" in spoken


def test_the_sentence_says_what_will_not_help() -> None:
    """An agent that reads `Read-only file system` retries, chmods, and mkdirs.

    None of those can work, and none of them says so. Naming them is what
    turns the sentence from a label into an instruction.
    """
    spoken = boundary_refusal(
        "cannot write '/repo/tree/dev/x': Read-only file system", CONFINED
    )
    assert "retrying" in spoken and "permissions" in spoken


def test_a_read_only_disk_outside_the_table_is_not_claimed() -> None:
    """The marker alone never suffices, and this is why.

    A genuinely read-only disk says exactly the same thing. Claiming it would
    send the agent looking for a boundary that was not involved -- and the
    branch that matched every unmentioned path matched most paths on the
    machine.
    """
    assert boundary_refusal("mount: /dev/sda1: Read-only file system", CONFINED) == ""


def test_a_path_under_a_writable_tree_is_not_claimed() -> None:
    """The lease's own worktree is writable, so a failure there is the code's."""
    assert boundary_refusal("/repo/tree/mine/x: Read-only file system", CONFINED) == ""


def test_an_ordinary_failure_is_not_claimed() -> None:
    """Silence is the right answer far more often than a claim is."""
    assert boundary_refusal("ModuleNotFoundError: no module named 'x'", CONFINED) == ""


def test_a_session_with_no_boundary_recorded_claims_nothing() -> None:
    """An uncontained session has no boundary to attribute anything to."""
    assert boundary_refusal("/anything: Read-only file system", {}) == ""


def test_a_path_that_merely_starts_alike_is_not_covered() -> None:
    """`/repo/tree/development` is not under `/repo/tree/dev`."""
    spoken = boundary_refusal(
        "/repo/tree/development/x: Read-only file system", CONFINED
    )
    assert spoken == ""


def test_a_quoted_path_is_still_found(tmp_path: Path) -> None:
    """Error messages are prose with a path in them, and prose has no parser."""
    for quoted in ("'/repo/tree/dev/x'", '"/repo/tree/dev/x"', "(/repo/tree/dev/x)"):
        assert boundary_refusal(f"failed {quoted}: Permission denied", CONFINED)


def test_an_absent_description_reads_as_no_boundary(tmp_path: Path) -> None:
    """The ordinary answer for an uncontained session, not a failure."""
    assert boundary_description(tmp_path) == {}
    assert boundary_description(None) == {}


def test_an_unparseable_description_reads_as_no_boundary(tmp_path: Path) -> None:
    """A wrecked ledger must not make every later command fail in a hook."""
    ledger = tmp_path / ".lup" / "boundary.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json", encoding="utf-8")
    assert boundary_description(tmp_path) == {}


def test_a_description_the_launcher_wrote_is_read_back(tmp_path: Path) -> None:
    """The launch fact the dispatcher was compiled too early to know."""
    ledger = tmp_path / ".lup" / "boundary.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(CONFINED), encoding="utf-8")
    assert boundary_description(tmp_path)["read_only"] == CONFINED["read_only"]
