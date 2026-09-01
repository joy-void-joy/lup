"""The decisions every runtime reaches identically, over the shared kernel.

:mod:`lup.policy.dispatcher` compiles this half into every generated script
beside the host half and one runtime's own words, so a decision written here
is the decision every runtime makes. What belongs here is everything
downstream of a payload: the declarations a tool is judged against, and the
host-resolved facts the kernel needs to judge it. What does not belong is
anything a runtime spells for itself — the payload shape those values are read
out of, the root it installs trusted packages beneath, and the envelope a
verdict is returned in.

The split is drawn there because the arguments a kernel call carries are
exactly what drifted before. Each runtime passed its own set, nothing compared
them, and a fact one of them stopped passing was a rule that silently stopped
applying — with no failure anywhere, because a permission that never happens
looks like a permission that was granted. One call site cannot disagree with
itself.

The imports below resolve against the generated runtime this is compiled
beside, which is why this file is type-checked against that tree rather than
against the workspace.
"""

from pathlib import Path

from host import (
    contained,
    script_run_nudge,
    directory_write_targets,
    empty_directory_targets,
    existing_write_targets,
    foreign_repository,
    granted_allowances,
    managed_script_roots,
    recoverable_write_targets,
    record_deferral,
    resolved_refutations,
    undo_snapshot,
    worktree_path,
)
from kernel.decision import KernelDecision
from kernel.edit import (
    awaits_resolution,
    decide_edit,
    relocated_edit_text,
    relocated_suppressions,
)
from kernel.fetch import decide_fetch
from kernel.lex import (
    python_script_targets,
    shell_path_verb_targets,
    shell_write_targets,
)
from kernel.words import INTERPRETERS
from kernel.shell import decide_shell, sandbox_excluded
from kernel.tools import decide_tool
from policy_data import (
    ACCEPTANCE_GUARD,
    ALLOWANCE_GRANTS_ENV,
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    RESOLUTION_COMMAND,
    DENIED_FETCH_SCOPES,
    EDIT_RULES,
    KNOWN_ALLOWANCES,
    MAXIMUM_ADDED_LINES,
    PATH_ROLES,
    PATH_RULES,
    RECOVERABLE_TARGET_LIMIT,
    REFUSED_TOOLS,
    RUNNER_TARGET_TABLES,
    RUNNER_TARGETS,
    SANDBOX_EXCLUDED_COMMANDS,
    SHELL_RULES,
)


def bash_decision(
    command: str,
    managed_root: Path | None,
    sandboxed: bool,
    interactive: bool,
    escapable: bool,
    cwd: Path | None,
    relayed: bool = False,
) -> KernelDecision:
    """Judge one shell command against the declared vocabulary.

    The kernel reads no filesystem, so every fact about the paths this command
    would touch is resolved here and passed as data: which of the paths it
    would write already exist, which operands Git could restore, and which
    are directories.

    Existence and recoverability both cover redirection targets and path-verb
    operands alike, because the questions they ask are the same ones —
    whether writing here brings something into being or replaces it, and what
    replacing it would cost. Resolving them for only one of the two writing
    forms is what left ``rm f`` granted while ``echo x > f`` asked about the
    same clean, tracked file.

    ``cwd`` is where the calling session is, which the command's relative
    operands resolve against. It is a parameter rather than a read of this
    process, because a hook is promised nothing about where it runs, and
    resolving a target against the wrong tree answers a different question.

    ``escapable`` is the one thing here a runtime answers rather than the host:
    whether it can put a single call outside its own sandbox. It arrives as an
    argument for the same reason the rest does — a fact one dispatcher stopped
    passing is a rule that silently stopped applying.
    """
    acted_on = shell_path_verb_targets(command)
    # Before the verdict rather than after it, because the verdict reads it:
    # an approval question exists where a loss is permanent, and a tree the
    # object store already holds has no permanent loss to ask about. Ordered
    # the other way the relaxation would be judging a snapshot that did not
    # exist yet, and a refused command is snapshotted too -- one ref for a
    # state the tree was already in, which dedup collapses.
    reference = undo_snapshot(cwd, command)
    verdict = decide_shell(
        command,
        SHELL_RULES,
        ALLOWED_FETCH_SCOPES,
        DENIED_FETCH_SCOPES,
        sandboxed=sandboxed,
        excluded_commands=SANDBOX_EXCLUDED_COMMANDS,
        trusted_script_roots=managed_script_roots(managed_root),
        path_roles=PATH_ROLES,
        path_rules=PATH_RULES,
        existing_targets=existing_write_targets(
            [*shell_write_targets(command), *acted_on], cwd
        ),
        recoverable_targets=recoverable_write_targets(
            [*shell_write_targets(command), *acted_on], cwd
        ),
        directory_targets=directory_write_targets(acted_on, cwd),
        empty_directories=empty_directory_targets(acted_on, cwd),
        recoverable_target_limit=RECOVERABLE_TARGET_LIMIT,
        runner_targets=RUNNER_TARGETS,
        target_tables=RUNNER_TARGET_TABLES,
        interactive=interactive,
        # A reviewed worker is non-interactive and not therefore alone: it
        # holds a mailbox reaching the human supervising its run, and a
        # refusal that named no route sent it to queue a blocking question
        # instead.
        relayed=relayed,
        escapable=escapable,
        # Read here rather than passed by each dispatcher, unlike `escapable`
        # above: whether this process sits inside the container is a fact
        # about the host with no runtime variation to it, so neither
        # dispatcher is given the chance to forget it.
        contained=contained(),
        recovered=bool(reference),
    )
    if verdict.effect == "deny":
        return verdict
    # The log half of allow-and-log. A deferral is this policy declining to
    # interrupt, which is the one verdict that reaches nobody: the runtime's
    # own gate decides and the reason goes to no human. Written down here or
    # it is not written down anywhere.
    if verdict.effect == "defer":
        record_deferral(cwd, command, verdict.reason, verdict.checkpoint != "nothing")
    pointed = undo_point(verdict, reference)
    if pointed.effect != "allow":
        return pointed
    nudge = script_run_nudge(python_script_targets(command, INTERPRETERS), cwd)
    if not nudge:
        return pointed
    return KernelDecision(
        pointed.effect,
        pointed.reason + nudge,
        pointed.sandbox,
        pointed.escalated,
        checkpoint=pointed.checkpoint,
    )


def unconfined_by_declaration(command: str) -> bool:
    """Whether the boundary declaration takes this command out of isolation.

    A command excluded from the boundary runs unconfined because the profile
    said so, which is a grant a native escape request is spending rather than
    circumventing. Read here, beside every other reading of the same table, so
    a runtime cannot answer it differently from the classifier.
    """
    return sandbox_excluded(command, SANDBOX_EXCLUDED_COMMANDS)


def undo_point(verdict: KernelDecision, reference: str) -> KernelDecision:
    """Say the tree was snapshotted, on the one verdict that changes for it.

    The snapshot itself is taken above, before the verdict, because the
    verdict reads it. What is left here is what the human is told.

    On an approval question, which is the one moment the information changes
    an answer: somebody deciding whether to permit something destructive is
    weighing exactly whether it can be undone. On an allowed command the
    snapshot is silent, because a line appended to every mutating command is
    one nobody reads by the third time — and ``dev undo`` is where a snapshot
    is looked for anyway. On a deferral the reason reaches no human at all;
    it reaches the record, which is where the relaxation is reviewed.
    """
    if not reference or verdict.effect != "ask":
        return verdict
    return KernelDecision(
        verdict.effect,
        f"{verdict.reason} — the tree was snapshotted first; "
        f"`lup-devtools dev undo` lists it as {reference}",
        verdict.sandbox,
        verdict.escalated,
        checkpoint=verdict.checkpoint,
    )


def fetch_decision(url: str) -> KernelDecision:
    """Judge one outbound fetch against the declared scopes."""
    return decide_fetch(url, ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES)


def refused_tool_decision(name: str, values: list[str]) -> KernelDecision | None:
    """Judge one native call against the calls this project refuses outright.

    ``None`` leaves the routing runtime's own answer for a tool no refusal
    mentions, because the table says what a project decided against and never
    what it approved — an unmentioned tool is still unclassified.
    """
    return decide_tool(name, values, REFUSED_TOOLS)


def placed_document(path_text: str, after: str) -> str:
    """One file's text with every suppression at its canonical placement.

    Only Python has a placement to settle here: the policy is written in terms
    of a comment the formatter cannot wrap, and the tokenizer that says where
    a comment really opens is Python's.
    """
    if Path(path_text).suffix.lower() not in (".py", ".pyi"):
        return after
    return relocated_suppressions(after)


def placed_edit_text(path_text: str, after: str, start: int, end: int) -> str | None:
    """The replacement for an edit's own span, or ``None`` to place nothing."""
    if Path(path_text).suffix.lower() not in (".py", ".pyi"):
        return None
    return relocated_edit_text(after, start, end)


def edit_decision(
    path_text: str,
    before: str | None,
    after: str | None,
    path_exists: bool,
    autonomous: bool,
    operation: str = "modify",
    cwd: Path | None = None,
) -> KernelDecision:
    """Judge one file's before and after against the declared edit policy.

    The path is relativized against the worktree holding it rather than the
    directory the runtime started in, because every repo-relative rule matches
    on that answer and a session may be launched anywhere.

    The gates this lease holds are read here, per call, rather than resolved
    when the session started: a grant is answered by a human while the session
    that asked for it is still running, and one resolved at launch could not
    have carried the answer.

    A checker is started only where its answer decides something. The kernel
    is asked first, from the tree and the tables alone, whether this edit
    trips a rule whose verdict turns on a resolved declaration; almost none
    do, and those are judged for nothing. Only the rest pay for a language
    server, which is the difference between a gate that costs a second per
    edit and one that costs a second on the edits that need it.
    """
    outside_this_repository = foreign_repository(path_text, cwd)
    suffix = Path(path_text).suffix.lower()
    python_source = suffix in (".py", ".pyi")
    rows = ANTI_PATTERN_ROWS[suffix] if suffix in ANTI_PATTERN_ROWS else []
    # A checker is not started for a file this policy has already decided it
    # has nothing to say about. It would resolve another repository's imports
    # against another repository's environment to answer a rule that will not
    # be applied, and pay a language server's second for the privilege.
    refuted = (
        resolved_refutations(path_text, after, RESOLUTION_COMMAND)
        if not outside_this_repository
        and after is not None
        and awaits_resolution(before, after, rows, python_source)
        else None
    )
    return decide_edit(
        worktree_path(path_text),
        before,
        after,
        path_exists=path_exists,
        path_rules=PATH_RULES,
        antipattern_rows=rows,
        path_roles=PATH_ROLES,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=autonomous,
        allowances=granted_allowances(ALLOWANCE_GRANTS_ENV, KNOWN_ALLOWANCES),
        python_source=python_source,
        acceptance_guard=ACCEPTANCE_GUARD,
        refuted=refuted,
        suffix=suffix,
        operation=operation,
        edit_rules=EDIT_RULES,
        foreign=outside_this_repository,
    )
