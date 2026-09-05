"""What a verb destroys is read off its own targets, not off its row.

A row carries one value for every path it might touch, and for `rm`, `cp`,
`mv`, `ln` and the archive verbs that value is `boundary_wide`: a glob or a
variable prevents an exact footprint, so the wider capture is what the opacity
costs. That is the right reading inside the checkout and a false one the
moment a path leaves it, because the capture it names is a snapshot of the
checkout.

Measured before this, with a snapshot taken: `rm /etc/hosts` was *allowed*,
and the reason it gave was "the affected paths are captured and restorable" —
said of a file no snapshot of this checkout has ever held. The settlement row
that discharges a covered loss had been handed a claim nothing backed, which
is the same defect `write_checkpoint` closed for a redirection, still open on
the other spelling of a write.
"""

from pathlib import Path

from lup.policy.kernel.rows import PathRoleRow
from lup.policy.models import Decision, ShellCommand
from lup.policy.rules import ShellPolicy
from lup.policy.vocabulary import default_vocabulary

SCRATCH = [PathRoleRow(root="tmp", role="scratch")]


def recovered(command: str, root: Path) -> Decision:
    """One command in a session whose checkout is held by a proven capture."""
    return ShellPolicy(default_vocabulary(), path_roles=SCRATCH, recovered=True).decide(
        ShellCommand(command=command, cwd=root)
    )


def test_a_capture_of_this_checkout_does_not_discharge_a_loss_beyond_it(
    tmp_path: Path,
) -> None:
    """The hole, stated against the claim the settlement row was making."""
    verdict = recovered("rm /etc/hosts", tmp_path)

    assert verdict.effect == "ask"
    assert "captured and restorable" not in verdict.reason


def test_one_operand_outside_the_checkout_answers_for_the_line(
    tmp_path: Path,
) -> None:
    """A mixed command is judged by the loss nothing holds, not by the other one.

    The scope is the strongest of the operands, on the same reasoning the
    segment join uses: a command that destroys scratch *and* a file beyond the
    boundary is the second of those, and nothing about the harmless half
    weakens it.
    """
    assert recovered("rm tmp/a /etc/hosts", tmp_path).effect == "ask"


def test_only_the_operands_the_verb_writes_are_read(tmp_path: Path) -> None:
    """A source `cp` merely reads is an ordinary read, however far out it sits.

    Reading every operand would have been the conservative mistake: it keeps a
    question, and it keeps it for a command that destroys nothing at all.
    """
    scratch = tmp_path / "tmp"
    scratch.mkdir()

    assert recovered("cp /etc/hosts tmp/hosts", tmp_path).effect == "allow"
    assert recovered("cp README.md /etc/hosts", tmp_path).effect == "ask"


def test_an_archive_verb_is_read_the_same_way_its_targets_already_were(
    tmp_path: Path,
) -> None:
    """The verbs that named their targets and still answered from the row.

    `archive_lands_on_nothing` reads exactly these paths to grant an
    extraction that replaces nothing, so the targets were there to be had —
    and where the grant did not apply, the row's own `boundary_wide` stood
    and the settlement row discharged it. Measured before this, with a
    snapshot taken: `gzip /etc/hosts` and `tar -xf a.tgz -C /etc` were both
    allowed as "captured and restorable".
    """
    assert recovered("gzip /etc/hosts", tmp_path).effect == "ask"
    assert recovered("gunzip /etc/hosts.gz", tmp_path).effect == "ask"
    assert recovered("tar -xf a.tgz -C /etc", tmp_path).effect == "ask"


def test_work_inside_the_checkout_keeps_the_answer_it_had(tmp_path: Path) -> None:
    """The everyday case, which the row was already right about.

    Scratch is disposable by declaration and the object store holds the rest,
    so nothing here changes: this reads the targets to find the losses a
    capture cannot cover, not to find more of them.
    """
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    (scratch / "scratch.txt").write_text("x", encoding="utf-8")

    assert recovered("rm tmp/scratch.txt", tmp_path).effect == "allow"
    assert recovered("rm -r tmp/build", tmp_path).effect == "allow"
    assert recovered("mv tmp/a tmp/b", tmp_path).effect == "allow"
    assert recovered("gzip tmp/notes.txt", tmp_path).effect == "allow"
    assert recovered("tar -xf a.tgz -C tmp/out", tmp_path).effect == "allow"
