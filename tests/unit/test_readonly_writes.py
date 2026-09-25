"""A write landing in a read-only region the launch measured is refused.

The container binds each repository's shared `config` and `hooks/` read-only
inside the writable share around them, because git runs on the host what they
name. The launch records the same holes as read-only roots, and these hold the
reading that carries them to every verb on a host posture: a `cp`, `mv` or
`ln` placing bytes in `hooks/` reached only the loss row, which a capture of
the session's own checkout discharged for a tree it never held.
"""

from pathlib import Path

import pytest

from lup.policy.assets.host import readonly_write_targets
from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.lex import shell_write_targets, shell_written_targets
from lup.policy.kernel.settlement import SettlementFacts, settle
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary

CLONE = "/home/u/.cache/lup/sync/lup.git"
"""A cache clone a launch mounted whole, as the registry materializes one."""

MEASURED = {
    "writable_roots": ["/repo", CLONE],
    "read_only_roots": [f"{CLONE}/config", f"{CLONE}/hooks"],
}
"""The lease a launch records for it: the clone writable, its two holes not."""

VOCABULARY = erase_shell_rules(default_vocabulary())


def held(command: str) -> list[str]:
    """The targets the hook hands the row: every write this command names."""
    return readonly_write_targets(
        [*shell_write_targets(command), *shell_written_targets(command, VOCABULARY)],
        MEASURED,
        Path("/repo"),
    )


def judged(
    command: str, sandboxed: bool = False, existing: list[str] | None = None
) -> KernelDecision:
    """One command on a host posture whose checkout a capture already holds."""
    return decide_shell(
        command,
        VOCABULARY,
        sandboxed=sandboxed,
        existing_targets=existing or [],
        recovered=True,
        readonly_targets=held(command),
    )


WRITES = {
    "redirection": f"echo x > {CLONE}/hooks/post-checkout",
    "copy": f"cp notes.txt {CLONE}/hooks/post-checkout",
    "move": f"mv notes.txt {CLONE}/hooks/post-checkout",
    "tee": f"echo x | tee {CLONE}/hooks/post-checkout",
    "symlink": f"ln -s /repo/notes.txt {CLONE}/hooks/post-checkout",
    "config append": f"printf 'x' >> {CLONE}/config",
    "config copy": f"cp notes.txt {CLONE}/config",
}


@pytest.mark.parametrize("command", WRITES.values(), ids=list(WRITES))
def test_every_spelling_of_a_write_into_a_hole_is_reported(command: str) -> None:
    """The hole is a place, so which verb reached it cannot matter."""
    assert held(command)


@pytest.mark.parametrize("command", WRITES.values(), ids=list(WRITES))
@pytest.mark.parametrize("sandboxed", [True, False], ids=["inner", "none"])
def test_every_spelling_of_a_write_into_a_hole_is_refused(
    command: str, sandboxed: bool
) -> None:
    """What the container's read-only bind does, on either host posture."""
    verdict = judged(command, sandboxed)

    assert verdict.effect == "deny"
    assert verdict.rule == "read-only-write"
    assert "read-only" in verdict.reason


@pytest.mark.parametrize(
    ("command", "existing"),
    [
        (f"cp notes.txt {CLONE}/hooks/post-checkout", []),
        (f"ln -s /repo/notes.txt {CLONE}/hooks/post-checkout", []),
        (f"cp notes.txt {CLONE}/config", [f"{CLONE}/config"]),
    ],
    ids=["copy creating a hook", "link creating a hook", "copy over config"],
)
def test_the_refusal_is_the_measurement_s_and_not_the_loss_row_s(
    command: str, existing: list[str]
) -> None:
    """What the vocabulary alone says about the same write, and what moves it.

    A path verb carries only the loss row, which has nothing to refuse in a
    file that is not there yet and asks about one it replaces -- so without
    the measured hole a hook is created unprompted, and a copy over `config`
    becomes a question somebody could approve.
    """
    unmeasured = decide_shell(
        command, VOCABULARY, existing_targets=existing, recovered=True
    )

    assert unmeasured.effect != "deny"
    assert judged(command, existing=existing).effect == "deny"


@pytest.mark.parametrize(
    "command",
    [
        f"cat {CLONE}/config",
        f"ls {CLONE}/hooks",
        f"sed -n 1,20p {CLONE}/hooks/pre-push",
        f"cp {CLONE}/hooks/pre-push /repo/notes.txt",
    ],
)
def test_reading_a_hole_is_not_a_write_into_it(command: str) -> None:
    """A copy *out of* `hooks/` reads it, and a read is what the bind permits."""
    assert held(command) == []


def test_moving_a_hook_out_is_a_write_to_the_hole() -> None:
    """A move unlinks its source, which the bind refuses as surely as a create."""
    assert held(f"mv {CLONE}/hooks/pre-push /repo/notes.txt") == [
        f"{CLONE}/hooks/pre-push"
    ]


@pytest.mark.parametrize(
    "target",
    [
        f"{CLONE}/tree/main/notes.txt",
        f"{CLONE}/objects/ab/cdef",
        f"{CLONE}/info/attributes",
        "/repo/notes.txt",
    ],
)
def test_the_writable_rest_of_the_clone_is_not_a_hole(target: str) -> None:
    """Only what the container binds read-only; its worktrees and store are not."""
    assert held(f"cp notes.txt {target}") == []


def test_a_writable_subtree_inside_a_read_only_region_stays_writable() -> None:
    """The deepest scope decides, as it does for the mount table and the edits."""
    measured = {"writable_roots": ["/data/scratch"], "read_only_roots": ["/data"]}

    assert readonly_write_targets(["/data/scratch/x"], measured, Path("/")) == []
    assert readonly_write_targets(["/data/x"], measured, Path("/")) == ["/data/x"]


def test_a_target_outside_every_root_is_left_to_the_unleased_row() -> None:
    """Nothing encloses it, so it is not in a hole -- it is outside the lease."""
    assert readonly_write_targets(["/elsewhere/x"], MEASURED, Path("/repo")) == []


def test_no_read_only_measurement_reports_nothing() -> None:
    """A launch that measured no holes has none for a write to land in."""
    measured = {"writable_roots": ["/repo", CLONE]}

    assert readonly_write_targets([f"{CLONE}/hooks/x"], measured, Path("/repo")) == []


def test_a_refusal_already_standing_keeps_its_own_reason() -> None:
    """The row adds nothing to a verdict that already refuses."""
    refused = KernelDecision("deny", "a rule refused this", rule="some-rule")

    settled = settle(SettlementFacts(refused, readonly=[f"{CLONE}/config"]))

    assert (settled.effect, settled.rule) == ("deny", "some-rule")
