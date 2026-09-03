"""The reports this overhaul answers, each pinned to the behaviour that answers it.

A search roster is not proof of resolution, so each of these was read for what
it actually asked and mapped to one executable expectation. What that buys is
the direction nobody usually gets: a regression re-opens the issue here rather
than being noticed months later by whoever hits it again.

Reports the overhaul does *not* answer are named in the module docstring
below rather than quietly omitted, because a roster that lists only the
resolved half reads as a complete one.

Not answered here, and independent:

- **#188** (a session rooted in lup enforces lup's rules against another
  repository's files) — answered by the foreign-repository branch, which
  predates this work and is about scope rather than judgement.
- **#216** (a project's shell rules replace rather than extend the library's)
  and **#304** (edit gates have no vocabulary a project can declare) — both
  about the *declaration* surface. The edit half now carries reviewer and
  purpose per gate, which narrows #304 without closing it.
- **#347** (a conflicted generated tree bricks the dispatcher) — a generation
  and recovery concern, untouched by the semantic model.
"""

from lup.policy.kernel.shell import decide_shell, sandbox_excluded
from lup.policy.kernel.rows import ShellRuleRow
from lup.policy.shell_rules import erase_shell_rules
from lup.policy.vocabulary import default_vocabulary
from lup_template.devtools.harness.catalog import portable_harness


def rows() -> list[ShellRuleRow]:
    """The library's offered table, erased to the rows the kernel reads."""
    return erase_shell_rules(default_vocabulary())


def test_65_a_worker_has_a_route_past_a_gate() -> None:
    """#65: an escalation marker was a guaranteed denial in a worker session.

    Non-interactive was read as alone, so an ask had nobody to answer it and
    the documented escape hatch had no effect in precisely the context that
    most needs one. A worker holds a mailbox reaching whoever supervises the
    run, so the question is parked for them.
    """
    worker = decide_shell(
        "# lup: escalate[decision]: I need to clean my own scratch\nrm -rf tmp/x",
        rows(),
        interactive=False,
        relayed=True,
    )

    assert worker.effect == "ask"
    assert "I need to clean my own scratch" in worker.reason


def test_202_a_worker_can_remove_what_it_created() -> None:
    """#202: every deletion shape was refused, so scratch stranded a whole run.

    A worker copied two files to its own worktree to read them and could not
    remove them, then parked a material question asking a human what to do
    about files it had made itself. Local loss a capture puts back is settled
    rather than asked, and the capture is what makes that honest.
    """
    with_capture = decide_shell(
        "rm scratch.txt",
        rows(),
        interactive=False,
        relayed=True,
        recovered=True,
        contained=True,
        sandboxed=True,
    )

    assert with_capture.effect == "allow"


def test_86_a_judged_question_is_not_run_because_nobody_can_be_asked() -> None:
    """#86: a judged ask became a run wherever the host was sandboxed.

    On the reasoning that the OS boundary confines it either way — which
    confuses confining an operation with reviewing it, and converted every
    deliberately-guarded command into a run, including anything carrying an
    escalation marker.
    """
    headless = decide_shell(
        "git push --delete origin feat",
        rows(),
        sandboxed=True,
        contained=True,
        interactive=False,
    )

    assert headless.effect == "deny"
    assert "no eligible reviewer" in headless.reason


def test_137_an_unprompted_crossing_needs_a_measured_channel() -> None:
    """#137: allow+outside rendered an escape nothing had tested end to end.

    The concern's own criterion said the experiment had to be run, and it was
    not. It is no longer a question about rendering: the crossing needs a
    declared host executor, measured at launch, and a profile without one
    refuses rather than emitting a key it hopes the runtime honours.
    """
    # The offered table declares no crossing at all, which is the other half
    # of the answer: nothing in a general-purpose toolchain needs the host,
    # so there is no unprompted escape left to have gone untested.
    assert all(row["sandbox"] != "outside" for row in rows())


def test_180_a_native_escalation_of_an_excluded_command_is_honoured() -> None:
    """#180: Codex rejected a read-only diff after its own escalation was accepted.

    The hook read the placement alone, which was right while the toolchain
    declared one. It declares an exclusion instead — the same requirement
    where a launch can measure it — so reading the placement alone refused an
    escape the boundary had already granted.
    """
    hooks = portable_harness().plugins[0].hooks
    assert hooks is not None

    assert sandbox_excluded("git diff --stat", hooks.excluded_commands())


def test_351_the_verbs_that_drive_git_are_excluded_like_git() -> None:
    """#351: `git *` was excluded and the command that drives it was not.

    So the mandated worktree workflow could not run sandboxed, while the
    identical `git config --local` succeeded one call away. A child of a
    confined command is confined too, which is the argument the `gh` entry
    beside it already made.
    """
    hooks = portable_harness().plugins[0].hooks
    assert hooks is not None
    excluded = hooks.excluded_commands()

    assert sandbox_excluded("uv run lup-devtools dev worktree create feat-x", excluded)
    assert not sandbox_excluded("uv run lup-devtools py info lup.policy", excluded)


def test_191_a_read_only_builtin_is_not_refused() -> None:
    """#191: the classifier denied `command -v`, which only reports a path."""
    assert decide_shell("command -v python3", rows()).effect == "allow"
