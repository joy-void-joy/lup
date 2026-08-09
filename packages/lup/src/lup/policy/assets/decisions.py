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
    directory_write_targets,
    existing_write_targets,
    granted_allowances,
    managed_script_roots,
    recoverable_write_targets,
    worktree_path,
)
from kernel.decision import KernelDecision
from kernel.edit import decide_edit
from kernel.fetch import decide_fetch
from kernel.lex import shell_path_verb_targets, shell_write_targets
from kernel.shell import decide_shell
from policy_data import (
    ALLOWED_FETCH_SCOPES,
    ANTI_PATTERN_ROWS,
    CONCERN_ALLOWANCES_ENV,
    DENIED_FETCH_SCOPES,
    KNOWN_ALLOWANCES,
    MAXIMUM_ADDED_LINES,
    PATH_ROLES,
    PATH_RULES,
    RECOVERABLE_TARGET_LIMIT,
    RUNNER_TARGETS,
    SHELL_RULES,
)


def bash_decision(
    command: str, managed_root: Path | None, sandboxed: bool, interactive: bool
) -> KernelDecision:
    """Judge one shell command against the declared vocabulary.

    The kernel reads no filesystem, so every fact about the paths this command
    would touch is resolved here and passed as data: which redirection targets
    already exist, which operands Git could restore, and which are directories.
    """
    acted_on = shell_path_verb_targets(command)
    return decide_shell(
        command,
        SHELL_RULES,
        ALLOWED_FETCH_SCOPES,
        DENIED_FETCH_SCOPES,
        sandboxed=sandboxed,
        trusted_script_roots=managed_script_roots(managed_root),
        path_roles=PATH_ROLES,
        path_rules=PATH_RULES,
        existing_targets=existing_write_targets(shell_write_targets(command)),
        recoverable_targets=recoverable_write_targets(acted_on),
        directory_targets=directory_write_targets(acted_on),
        recoverable_target_limit=RECOVERABLE_TARGET_LIMIT,
        runner_targets=RUNNER_TARGETS,
        interactive=interactive,
    )


def fetch_decision(url: str) -> KernelDecision:
    """Judge one outbound fetch against the declared scopes."""
    return decide_fetch(url, ALLOWED_FETCH_SCOPES, DENIED_FETCH_SCOPES)


def edit_decision(
    path_text: str,
    before: str | None,
    after: str | None,
    path_exists: bool,
    autonomous: bool,
) -> KernelDecision:
    """Judge one file's before and after against the declared edit policy.

    The path is relativized against the worktree holding it rather than the
    directory the runtime started in, because every repo-relative rule matches
    on that answer and a session may be launched anywhere.
    """
    suffix = Path(path_text).suffix.lower()
    return decide_edit(
        worktree_path(path_text),
        before,
        after,
        path_exists=path_exists,
        path_rules=PATH_RULES,
        antipattern_rows=ANTI_PATTERN_ROWS[suffix]
        if suffix in ANTI_PATTERN_ROWS
        else [],
        path_roles=PATH_ROLES,
        maximum_added_lines=MAXIMUM_ADDED_LINES,
        autonomous=autonomous,
        allowances=granted_allowances(CONCERN_ALLOWANCES_ENV, KNOWN_ALLOWANCES),
        python_source=suffix in (".py", ".pyi"),
    )
