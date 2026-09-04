"""Which path a redirection actually writes, and which of them destroy nothing.

Two readings that had drifted from what the shell does. A target behind a
parameter was judged as the literal text `$B`, which spells no path and earns
no role, so it fell to the fallback and was retired by the recovery row --
spending a capture's discharge on a write to scratch. And every stream but
`/dev/null` fell there too, which told the reader that "the affected paths are
captured and restorable" about a terminal.
"""

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.lex import shell_write_targets
from lup.policy.kernel.rows import PathRoleRow, ShellRuleRow
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary

SCRATCH = [PathRoleRow(root="tmp", role="scratch")]


def rows() -> list[ShellRuleRow]:
    """The library's offered table, which is what the contract describes."""
    return erase_shell_rules(default_vocabulary())


def verdict(command: str) -> KernelDecision:
    """One command judged with a scratch role declared over `tmp`."""
    return decide_shell(command, rows(), path_roles=SCRATCH)


def test_a_stream_target_raises_no_question_at_all() -> None:
    """Nothing prior is lost, so there is nothing for anybody to answer.

    Asserted as the absence of a question rather than as an allow, because
    these were already reaching allow -- by spending the recovery discharge,
    on the strength of a claim about captured paths that no stream has.
    """
    for target in ("/dev/null", "/dev/stderr", "/dev/stdout", "/dev/tty", "/dev/fd/2"):
        settled = verdict(f"echo hi > {target}")
        assert settled.effect == "allow", target
        assert "redirection" not in settled.reason, target


def test_a_descriptor_the_shell_opened_onto_a_file_is_not_a_stream() -> None:
    """`exec 3>notes.txt` makes `> /dev/fd/3` a write to `notes.txt`.

    So the family is named entry by entry rather than matched by shape, and
    `/dev/stdin` is left out for the same reason: a command run with
    `< notes.txt` would truncate it.
    """
    for target in ("/dev/fd/3", "/dev/fd/9", "/dev/stdin"):
        assert verdict(f"echo hi > {target}").effect == "ask", target


def test_a_device_that_destroys_is_not_a_stream() -> None:
    """The allowlist is named entry by entry because `/dev` is not a safe prefix.

    A prefix match would hand `> /dev/sda` the same silence it hands
    `> /dev/null`, and seeding the kernel's entropy pool is not a local loss a
    capture puts back either.
    """
    for target in ("/dev/sda", "/dev/urandom", "/dev/mem", "/dev/nvme0n1"):
        assert verdict(f"cat > {target}").effect == "ask", target


def test_a_standalone_assignment_names_the_path_that_is_written() -> None:
    """The shell wrote to `tmp/x`, and now so does the reading of it."""
    assert shell_write_targets("B=tmp/x; cat > $B") == ["tmp/x"]
    assert shell_write_targets("B=tmp/x; cat > ${B}") == ["tmp/x"]
    assert verdict("B=tmp/x; cat > $B").effect == "allow"


def test_a_command_prefix_assignment_is_not_the_shell_s_value() -> None:
    """`VAR=x cmd > $VAR` expands the redirection from the value already held.

    So the assignment beside it says nothing about where the write lands, and
    reading it would resolve a path the command never writes -- in the
    permissive direction, which is the one that matters.
    """
    assert shell_write_targets("B=tmp/x cat > $B") == ["$B"]
    assert verdict("B=tmp/x cat > $B").effect == "ask"


def test_only_a_literal_assignment_resolves() -> None:
    """A value carrying its own expansion names no path this can reconstruct."""
    assert shell_write_targets("B=$OTHER; cat > $B") == ["$B"]
    assert shell_write_targets("B=$(hostname); cat > $B") == ["$B"]
    assert verdict("B=$(hostname); cat > $B").effect == "ask"


def test_the_last_assignment_wins_as_the_shell_s_does() -> None:
    """Two assignments to one name leave the second standing, not the first."""
    assert shell_write_targets("B=tmp/x; B=tmp/y; cat > $B") == ["tmp/y"]


def test_an_unknown_name_stays_unresolved() -> None:
    """Nothing assigned it here, so the word keeps the only meaning we have."""
    assert shell_write_targets("cat > $B") == ["$B"]
    assert verdict("cat > $B").effect == "ask"
